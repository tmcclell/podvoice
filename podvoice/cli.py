"""Typer-based command line interface for podvoice.

The main entrypoint is ``podvoice render``, which takes a Markdown
script and produces a single audio file.
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
import tempfile
import threading
import time

import typer
from pydub import AudioSegment
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.traceback import install as install_rich_traceback

from .chunking import chunk_segments
from .guardrails import LanguagePolicy, apply_language_policy
from .parser import parse_markdown_script, merge_adjacent_segments
from .tts import XTTSVoiceEngine
from .audio import build_podcast, export_audio, play_audio
from .utils import (
    PodvoiceError,
    ScriptParseError,
    ModelLoadError,
    SynthesisError,
    get_default_cache_dir,
)


app = typer.Typer(help="Convert Markdown scripts into multi-speaker audio.")
console = Console()
install_rich_traceback(show_locals=False)


def _synthesize_with_cache(
    engine: XTTSVoiceEngine,
    segments,
    no_cache: bool,
    cache_dir: Path | None,
) -> tuple[list[AudioSegment], int]:
    """Synthesize segments and optionally read/write deterministic cache."""

    resolved_cache_dir = cache_dir if cache_dir is not None else get_default_cache_dir()
    if not no_cache:
        try:
            resolved_cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            console.print(f"[yellow]Warning:[/] Unable to initialize cache dir: {exc}")
            no_cache = True

    segment_audio: list[AudioSegment] = []
    cache_hits = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Synthesizing speech segments…", total=len(segments)
        )

        for segment in segments:
            cache_path: Path | None = None
            if not no_cache:
                cache_key = engine.cache_key_for_segment(segment)
                cache_path = resolved_cache_dir / f"{cache_key}.wav"

            if cache_path is not None and cache_path.exists():
                try:
                    audio = AudioSegment.from_file(cache_path)
                    segment_audio.append(audio)
                    cache_hits += 1
                    progress.update(task, advance=1)
                    continue
                except Exception:
                    pass

            try:
                audio = engine.synthesize_to_audiosegment(segment)
            except SynthesisError as exc:
                console.print(f"[red]Synthesis failed:[/] {exc}")
                raise typer.Exit(code=1)

            segment_audio.append(audio)

            if cache_path is not None:
                try:
                    audio.export(cache_path, format="wav")
                except Exception:
                    pass

            progress.update(task, advance=1)

    return segment_audio, cache_hits


_LOW_WATERMARK_MS = 2000
"""Default low-watermark threshold in milliseconds.

When the remaining buffered audio in the playback queue drops below this
value the consumer thread inserts a brief silence pad so the producer has
time to catch up — preventing an abrupt stall.
"""


def _stream_synthesize_and_play(
    engine: XTTSVoiceEngine,
    segments,
    no_cache: bool,
    cache_dir: Path | None,
    collect_audio: bool,
    stream_gap_ms: int,
    stream_prebuffer_ms: int,
) -> tuple[list[AudioSegment], int]:
    """Synthesize and play segments as they complete.

    This mode is intentionally best-effort and is exposed as an
    experimental option because playback timing depends on local device
    behavior.

    *Prebuffering* is now duration-based: playback starts once the
    cumulative buffered audio reaches *stream_prebuffer_ms* milliseconds
    (or when the last segment is queued, whichever comes first).

    A *low-watermark* guard prevents audible stalls: if the remaining
    buffered duration drops below ``_LOW_WATERMARK_MS`` the consumer
    inserts brief padding silence to give the producer time to catch up.
    """

    resolved_cache_dir = cache_dir if cache_dir is not None else get_default_cache_dir()
    if not no_cache:
        try:
            resolved_cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            console.print(f"[yellow]Warning:[/] Unable to initialize cache dir: {exc}")
            no_cache = True

    segment_audio: list[AudioSegment] = []
    cache_hits = 0
    playback_queue: Queue[AudioSegment | None] = Queue()
    playback_errors: list[PodvoiceError] = []
    gap = AudioSegment.silent(duration=stream_gap_ms)
    playback_start_event = threading.Event()

    # Duration-based prebuffer tracking (shared with _play_worker via lock)
    buffered_duration_ms: float = 0.0
    buffer_lock = threading.Lock()
    producer_done = threading.Event()

    def _play_worker() -> None:
        nonlocal buffered_duration_ms
        playback_start_event.wait()
        while True:
            item = playback_queue.get()
            if item is None:
                break

            # Deduct the item's duration from the shared buffer total.
            item_ms = len(item)  # pydub: len(seg) == duration in ms
            with buffer_lock:
                buffered_duration_ms -= item_ms

            # Low-watermark: if buffer is running low and producer is
            # still working, insert a small silence pad so synthesis
            # has time to enqueue more audio.
            if not producer_done.is_set():
                with buffer_lock:
                    remaining = buffered_duration_ms
                if remaining < _LOW_WATERMARK_MS and not playback_queue.qsize():
                    pad = AudioSegment.silent(duration=stream_gap_ms)
                    item = item + pad

            try:
                play_audio(item)
            except PodvoiceError as exc:
                playback_errors.append(exc)
                break

    worker = threading.Thread(target=_play_worker, daemon=True)
    worker.start()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "Synthesizing and streaming speech…", total=len(segments)
        )

        try:
            for idx, segment in enumerate(segments):
                cache_path: Path | None = None
                if not no_cache:
                    cache_key = engine.cache_key_for_segment(segment)
                    cache_path = resolved_cache_dir / f"{cache_key}.wav"

                if cache_path is not None and cache_path.exists():
                    try:
                        audio = AudioSegment.from_file(cache_path)
                        cache_hits += 1
                    except Exception:
                        audio = engine.synthesize_to_audiosegment(segment)
                else:
                    audio = engine.synthesize_to_audiosegment(segment)

                if collect_audio:
                    segment_audio.append(audio)

                if cache_path is not None and not cache_path.exists():
                    try:
                        audio.export(cache_path, format="wav")
                    except Exception:
                        pass

                playback_item = audio if idx == len(segments) - 1 else audio + gap
                playback_queue.put(playback_item)

                with buffer_lock:
                    buffered_duration_ms += len(playback_item)

                if (
                    buffered_duration_ms >= stream_prebuffer_ms
                    or idx == len(segments) - 1
                ):
                    playback_start_event.set()
                progress.update(task, advance=1)

                if playback_errors:
                    break
        except SynthesisError as exc:
            console.print(f"[red]Synthesis failed:[/] {exc}")
            raise typer.Exit(code=1)
        finally:
            producer_done.set()
            playback_start_event.set()
            playback_queue.put(None)
            worker.join()

    if playback_errors:
        console.print(f"[red]Playback failed:[/] {playback_errors[0]}")
        raise typer.Exit(code=1)

    return segment_audio, cache_hits


@app.command()
def render(
    script: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Path to the input Markdown script (*.md).",
    ),
    out: Path = typer.Option(
        None,
        "--out",
        "-o",
        help="Output audio file (.wav or .mp3). Defaults to <script-name>.wav",
    ),
    language: str = typer.Option(
        "en",
        "--language",
        "-l",
        help="Language code for XTTS v2 (e.g. en, de, fr).",
    ),
    device: str = typer.Option(
        "auto",
        "--device",
        "-d",
        help=(
            "Torch device to run on. 'auto' (default) selects CUDA when "
            "available and falls back to CPU."
        ),
    ),
    cpu_threads: int | None = typer.Option(
        None,
        "--cpu-threads",
        help=(
            "Number of CPU threads for PyTorch inference. "
            "Defaults to PyTorch/OS default when not set."
        ),
    ),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Disable segment cache and always re-synthesize speech.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="Override cache directory for synthesized segments.",
    ),
    play: bool = typer.Option(
        False,
        "--play",
        help="Play rendered audio locally. Disabled by default.",
    ),
    play_stream: bool = typer.Option(
        False,
        "--play-stream",
        help=(
            "Experimental: stream playback as segments are synthesized. "
            "Disabled by default."
        ),
    ),
    stream_gap_ms: int = typer.Option(
        80,
        "--stream-gap-ms",
        help="Silence between streamed segments in milliseconds (default: 80).",
    ),
    stream_prebuffer_ms: int = typer.Option(
        5000,
        "--stream-prebuffer-ms",
        help="Milliseconds of audio to buffer before starting stream playback (default: 5000).",
    ),
    stream_prebuffer: int = typer.Option(
        -1,
        "--stream-prebuffer",
        hidden=True,
        help="Deprecated: use --stream-prebuffer-ms instead.",
    ),
    skip_normalize: bool = typer.Option(
        False,
        "--skip-normalize",
        help="Skip audio normalization for faster draft renders.",
    ),
    quality: str | None = typer.Option(
        None,
        "--quality",
        help="MP3 encoding quality preset: 'draft' (96k) or 'final' (192k).",
    ),
    language_policy: str | None = typer.Option(
        None,
        "--language-policy",
        help=(
            "Language drift guardrail policy: 'warn' logs non-target "
            "characters, 'fail' aborts on drift, 'sanitize' removes them. "
            "Disabled by default."
        ),
    ),
    max_segment_chars: int = typer.Option(
        500,
        "--max-segment-chars",
        help="Maximum character length per segment before chunking (default: 500).",
    ),
) -> None:
    """Render a Markdown script into a single audio file."""

    console.print(
        Panel.fit(
            "Podvoice v0.1 — Markdown to multi-speaker audio (XTTS v2)",
            style="bold cyan",
        )
    )

    if play and play_stream:
        console.print("[red]Error:[/] Use either --play or --play-stream, not both.")
        raise typer.Exit(code=1)

    if stream_gap_ms < 0:
        console.print("[red]Error:[/] --stream-gap-ms must be >= 0.")
        raise typer.Exit(code=1)

    if stream_prebuffer_ms < 0:
        console.print("[red]Error:[/] --stream-prebuffer-ms must be >= 0.")
        raise typer.Exit(code=1)

    # Deprecated --stream-prebuffer: convert segment count to a rough ms
    # estimate (assume ~1 700 ms per segment) and override.
    if stream_prebuffer >= 0:
        console.print(
            "[yellow]Warning:[/] --stream-prebuffer is deprecated. "
            "Use --stream-prebuffer-ms instead."
        )
        stream_prebuffer_ms = stream_prebuffer * 1700
    elif stream_prebuffer < -1:
        console.print("[red]Error:[/] --stream-prebuffer must be >= 0.")
        raise typer.Exit(code=1)

    if quality is not None and quality not in {"draft", "final"}:
        console.print(
            "[red]Error:[/] --quality must be 'draft' or 'final'."
        )
        raise typer.Exit(code=1)

    _VALID_POLICIES = {"warn", "fail", "sanitize"}
    if language_policy is not None and language_policy not in _VALID_POLICIES:
        console.print(
            f"[red]Error:[/] --language-policy must be one of {sorted(_VALID_POLICIES)}."
        )
        raise typer.Exit(code=1)

    should_export = out is not None
    if out is None and not (play or play_stream):
        out = script.with_suffix(".wav")
        should_export = True

    if out is not None and out.suffix.lower() not in {".wav", ".mp3"}:
        # If the user provided a path without extension, default to WAV.
        if out.suffix == "":
            out = out.with_suffix(".wav")
            should_export = True
        else:
            console.print(
                "[red]Error:[/] Output path must end with .wav or .mp3.",
            )
            raise typer.Exit(code=1)

    try:
        raw_text = script.read_text(encoding="utf-8")
    except OSError as exc:
        console.print(f"[red]Failed to read script:[/] {exc}")
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Parse script
    # ------------------------------------------------------------------
    try:
        segments = parse_markdown_script(raw_text, source=str(script))
    except ScriptParseError as exc:
        console.print(f"[red]Invalid script format:[/] {exc}")
        raise typer.Exit(code=1)

    segments = merge_adjacent_segments(segments)
    segments = chunk_segments(segments, max_chars=max_segment_chars)

    if not segments:
        console.print("[red]Script did not contain any speaker segments.[/]")
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Apply language guardrails
    # ------------------------------------------------------------------
    if language_policy is not None:
        policy_enum = LanguagePolicy(language_policy)
        try:
            for i, segment in enumerate(segments):
                info = f"segment {i + 1}: {segment.speaker}"
                segment.text = apply_language_policy(
                    segment.text, language, policy_enum, segment_info=info,
                )
        except ValueError as exc:
            console.print(f"[red]Language policy violation:[/] {exc}")
            raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Load XTTS model
    # ------------------------------------------------------------------
    console.print(
        f"[bold]Loading XTTS v2 model[/bold] on device '[green]{device}[/green]'…"
    )
    try:
        engine = XTTSVoiceEngine(
            language=language, device=device, cpu_threads=cpu_threads,
        )
    except ModelLoadError as exc:
        console.print(f"[red]Model load failed:[/] {exc}")
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Synthesize segments and stitch audio
    # ------------------------------------------------------------------
    if play_stream:
        segment_audio, cache_hits = _stream_synthesize_and_play(
            engine=engine,
            segments=segments,
            no_cache=no_cache,
            cache_dir=cache_dir,
            collect_audio=should_export,
            stream_gap_ms=stream_gap_ms,
            stream_prebuffer_ms=stream_prebuffer_ms,
        )
        combined = None
        if should_export:
            try:
                combined = build_podcast(segment_audio, normalize=not skip_normalize)
            except PodvoiceError as exc:
                console.print(f"[red]Audio processing failed:[/] {exc}")
                raise typer.Exit(code=1)
    else:
        segment_audio, cache_hits = _synthesize_with_cache(
            engine=engine,
            segments=segments,
            no_cache=no_cache,
            cache_dir=cache_dir,
        )

        try:
            combined = build_podcast(segment_audio, normalize=not skip_normalize)
        except PodvoiceError as exc:
            console.print(f"[red]Audio processing failed:[/] {exc}")
            raise typer.Exit(code=1)

        if play:
            try:
                play_audio(combined)
            except PodvoiceError as exc:
                console.print(f"[red]Playback failed:[/] {exc}")
                raise typer.Exit(code=1)

    if should_export and out is not None:
        try:
            export_audio(combined, out, quality=quality)
        except PodvoiceError as exc:
            console.print(f"[red]Export failed:[/] {exc}")
            raise typer.Exit(code=1)

    if not no_cache:
        console.print(f"[dim]Cache hits:[/] {cache_hits}/{len(segments)}")

    if should_export and out is not None:
        console.print(f"[green]Done.[/] Wrote [bold]{out}[/].")
    elif play_stream:
        console.print("[green]Done.[/] Streamed audio to local speakers.")
    else:
        console.print("[green]Done.[/] Played audio through local speakers.")


@app.command()
def benchmark(
    script: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        help="Path to the input Markdown script (*.md).",
    ),
    iterations: int = typer.Option(
        3,
        "--iterations",
        "-n",
        min=1,
        help="Number of benchmark runs.",
    ),
    language: str = typer.Option(
        "en",
        "--language",
        "-l",
        help="Language code for XTTS v2 (e.g. en, de, fr).",
    ),
    device: str = typer.Option(
        "auto",
        "--device",
        "-d",
        help=(
            "Torch device to run on. 'auto' (default) selects CUDA when "
            "available and falls back to CPU."
        ),
    ),
    cpu_threads: int | None = typer.Option(
        None,
        "--cpu-threads",
        help=(
            "Number of CPU threads for PyTorch inference. "
            "Defaults to PyTorch/OS default when not set."
        ),
    ),
    no_cache: bool = typer.Option(
        True,
        "--no-cache/--cache",
        help="Disable or enable segment cache during benchmark.",
    ),
    cache_dir: Path | None = typer.Option(
        None,
        "--cache-dir",
        help="Override cache directory for synthesized segments.",
    ),
) -> None:
    """Run benchmark and print per-phase timing metrics."""

    console.print(
        Panel.fit(
            f"Benchmarking {script.name} for {iterations} iteration(s)",
            style="bold magenta",
        )
    )

    totals = {
        "parse": 0.0,
        "model_load": 0.0,
        "synthesis": 0.0,
        "stitch": 0.0,
        "export": 0.0,
        "total": 0.0,
    }

    for run_idx in range(1, iterations + 1):
        run_start = time.perf_counter()

        parse_start = time.perf_counter()
        try:
            raw_text = script.read_text(encoding="utf-8")
            segments = parse_markdown_script(raw_text, source=str(script))
            segments = merge_adjacent_segments(segments)
            segments = chunk_segments(segments)
        except (OSError, ScriptParseError) as exc:
            console.print(f"[red]Benchmark parse failed:[/] {exc}")
            raise typer.Exit(code=1)
        parse_time = time.perf_counter() - parse_start

        load_start = time.perf_counter()
        try:
            engine = XTTSVoiceEngine(
                language=language, device=device, cpu_threads=cpu_threads,
            )
        except ModelLoadError as exc:
            console.print(f"[red]Benchmark model load failed:[/] {exc}")
            raise typer.Exit(code=1)
        load_time = time.perf_counter() - load_start

        synth_start = time.perf_counter()
        segment_audio, cache_hits = _synthesize_with_cache(
            engine=engine,
            segments=segments,
            no_cache=no_cache,
            cache_dir=cache_dir,
        )
        synth_time = time.perf_counter() - synth_start

        stitch_start = time.perf_counter()
        try:
            combined = build_podcast(segment_audio)
        except PodvoiceError as exc:
            console.print(f"[red]Benchmark stitch failed:[/] {exc}")
            raise typer.Exit(code=1)
        stitch_time = time.perf_counter() - stitch_start

        export_start = time.perf_counter()
        try:
            with tempfile.TemporaryDirectory(prefix="podvoice_bench_") as tmp_dir:
                bench_out = Path(tmp_dir) / f"bench_{run_idx}.wav"
                export_audio(combined, bench_out)
        except PodvoiceError as exc:
            console.print(f"[red]Benchmark export failed:[/] {exc}")
            raise typer.Exit(code=1)
        export_time = time.perf_counter() - export_start

        total_time = time.perf_counter() - run_start

        totals["parse"] += parse_time
        totals["model_load"] += load_time
        totals["synthesis"] += synth_time
        totals["stitch"] += stitch_time
        totals["export"] += export_time
        totals["total"] += total_time

        console.print(
            f"Run {run_idx}: total={total_time:.2f}s "
            f"(parse={parse_time:.2f}s, load={load_time:.2f}s, "
            f"synth={synth_time:.2f}s, stitch={stitch_time:.2f}s, export={export_time:.2f}s, "
            f"cache_hits={cache_hits}/{len(segments)})"
        )

    console.print("\n[bold]Averages[/bold]")
    console.print(f"parse:      {totals['parse']/iterations:.2f}s")
    console.print(f"model load: {totals['model_load']/iterations:.2f}s")
    console.print(f"synthesis:  {totals['synthesis']/iterations:.2f}s")
    console.print(f"stitch:     {totals['stitch']/iterations:.2f}s")
    console.print(f"export:     {totals['export']/iterations:.2f}s")
    console.print(f"total:      {totals['total']/iterations:.2f}s")


# -- Daemon sub-commands -----------------------------------------------

daemon_app = typer.Typer(
    help="Manage the podvoice daemon for amortized model loading."
)
app.add_typer(daemon_app, name="daemon")


@daemon_app.command("start")
def daemon_start(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Host to bind to."
    ),
    port: int = typer.Option(8473, "--port", help="Port to listen on."),
    language: str = typer.Option(
        "en", "--language", "-l", help="Language code for XTTS v2."
    ),
    device: str = typer.Option(
        "auto",
        "--device",
        "-d",
        help=(
            "Torch device to run on. 'auto' (default) selects CUDA when "
            "available and falls back to CPU."
        ),
    ),
    cpu_threads: int | None = typer.Option(
        None,
        "--cpu-threads",
        help=(
            "Number of CPU threads for PyTorch inference. "
            "Defaults to PyTorch/OS default when not set."
        ),
    ),
) -> None:
    """Start the podvoice daemon (foreground).

    The daemon loads the XTTS model once and serves render requests over
    HTTP, amortizing the expensive model load across many invocations.
    """
    import logging

    from .daemon import PodvoiceDaemon
    from .tts import _resolve_device, _apply_cpu_thread_settings

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    device = _resolve_device(device)
    if device == "cpu":
        _apply_cpu_thread_settings(cpu_threads)

    console.print(
        Panel.fit(
            f"Starting podvoice daemon on {host}:{port} (device={device})",
            style="bold cyan",
        )
    )

    try:
        daemon = PodvoiceDaemon(
            language=language,
            device=device,
            host=host,
            port=port,
        )
    except ModelLoadError as exc:
        console.print(f"[red]Model load failed:[/] {exc}")
        raise typer.Exit(code=1)

    daemon.start()


@daemon_app.command("stop")
def daemon_stop(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Daemon host."
    ),
    port: int = typer.Option(8473, "--port", help="Daemon port."),
) -> None:
    """Stop a running podvoice daemon."""
    import json
    import urllib.error
    import urllib.request

    url = f"http://{host}:{port}/shutdown"
    try:
        req = urllib.request.Request(url, data=b"", method="POST")
        resp = urllib.request.urlopen(req, timeout=5)
        data = json.loads(resp.read())
        console.print(
            f"[green]Daemon shutting down:[/] {data.get('status', 'ok')}"
        )
    except urllib.error.URLError:
        console.print(
            f"[red]Error:[/] Could not connect to daemon at {host}:{port}."
        )
        raise typer.Exit(code=1)


@daemon_app.command("status")
def daemon_status(
    host: str = typer.Option(
        "127.0.0.1", "--host", help="Daemon host."
    ),
    port: int = typer.Option(8473, "--port", help="Daemon port."),
) -> None:
    """Check if a podvoice daemon is running."""
    import json
    import urllib.error
    import urllib.request

    url = f"http://{host}:{port}/health"
    try:
        resp = urllib.request.urlopen(url, timeout=5)
        data = json.loads(resp.read())
        console.print("[green]Daemon is running.[/]")
        console.print(f"  Model:    {data.get('model', 'unknown')}")
        console.print(f"  Language: {data.get('language', 'unknown')}")
        console.print(f"  Device:   {data.get('device', 'unknown')}")
        console.print(f"  Uptime:   {data.get('uptime_seconds', 0):.1f}s")
    except urllib.error.URLError:
        console.print(
            f"[yellow]Daemon is not running[/] at {host}:{port}."
        )
        raise typer.Exit(code=1)


if __name__ == "__main__":  # pragma: no cover
    app()
