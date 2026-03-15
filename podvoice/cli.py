"""Typer-based command line interface for podvoice.

The main entrypoint is ``podvoice render``, which takes a Markdown
script and produces a single audio file.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import time

import typer
from pydub import AudioSegment
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.traceback import install as install_rich_traceback

from .parser import parse_markdown_script, merge_adjacent_segments
from .tts import XTTSVoiceEngine
from .audio import build_podcast, export_audio
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
        "cpu",
        "--device",
        "-d",
        help="Torch device to run on (default: 'cpu'). Use 'cuda' if you have a GPU.",
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
) -> None:
    """Render a Markdown script into a single audio file."""

    console.print(
        Panel.fit(
            "Podvoice v0.1 — Markdown to multi-speaker audio (XTTS v2)",
            style="bold cyan",
        )
    )

    if out is None:
        out = script.with_suffix(".wav")
    elif out.suffix.lower() not in {".wav", ".mp3"}:
        # If the user provided a path without extension, default to WAV.
        if out.suffix == "":
            out = out.with_suffix(".wav")
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

    if not segments:
        console.print("[red]Script did not contain any speaker segments.[/]")
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Load XTTS model
    # ------------------------------------------------------------------
    console.print(
        f"[bold]Loading XTTS v2 model[/bold] on device '[green]{device}[/green]'…"
    )
    try:
        engine = XTTSVoiceEngine(language=language, device=device)
    except ModelLoadError as exc:
        console.print(f"[red]Model load failed:[/] {exc}")
        raise typer.Exit(code=1)

    # ------------------------------------------------------------------
    # Synthesize segments and stitch audio
    # ------------------------------------------------------------------
    segment_audio, cache_hits = _synthesize_with_cache(
        engine=engine,
        segments=segments,
        no_cache=no_cache,
        cache_dir=cache_dir,
    )

    try:
        combined = build_podcast(segment_audio)
    except PodvoiceError as exc:
        console.print(f"[red]Audio processing failed:[/] {exc}")
        raise typer.Exit(code=1)

    try:
        export_audio(combined, out)
    except PodvoiceError as exc:
        console.print(f"[red]Export failed:[/] {exc}")
        raise typer.Exit(code=1)

    if not no_cache:
        console.print(f"[dim]Cache hits:[/] {cache_hits}/{len(segments)}")

    console.print(f"[green]Done.[/] Wrote [bold]{out}[/].")


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
        "cpu",
        "--device",
        "-d",
        help="Torch device to run on (default: 'cpu'). Use 'cuda' if you have a GPU.",
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
        except (OSError, ScriptParseError) as exc:
            console.print(f"[red]Benchmark parse failed:[/] {exc}")
            raise typer.Exit(code=1)
        parse_time = time.perf_counter() - parse_start

        load_start = time.perf_counter()
        try:
            engine = XTTSVoiceEngine(language=language, device=device)
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


if __name__ == "__main__":  # pragma: no cover
    app()
