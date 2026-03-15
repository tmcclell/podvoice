---

# 🧠 **Podvoice**

Local-first, open-source CLI that turns simple Markdown scripts into
**multi-speaker audio** using **Coqui XTTS v2**.

Podvoice is built for developers who want a **boring, reliable, offline**
text-to-speech workflow — no cloud APIs, no subscriptions, no vendor lock-in.

Runs on **Linux, Windows, macOS, and FreeBSD**.

---

## Why Podvoice exists

* Most modern TTS tools depend on proprietary cloud services
* Developers want reproducible, script-based workflows
* Podcasts and narration should not require paid APIs

Podvoice is intentionally:

* Small
* Honest
* Hackable
* Local-first

No training pipelines.
No research code.
Just a clean CLI built on stable open-source components.

---

## Features

* **Markdown-based scripts**
* **Multiple logical speakers**
* **Deterministic voice assignment**
* **Single stitched output file**
* **WAV or MP3 export** with quality presets
* **Local-only inference**
* **CPU-first (GPU auto-detected)**
* **Cross-platform support**
* **Segment chunking** for long-text stability
* **Language drift guardrails**
* **Daemon mode** to amortize model load time

---

## Supported platforms

| Platform | Status            | Notes                  |
| -------- | ----------------- | ---------------------- |
| Linux    | ✅ Fully supported | Primary dev platform   |
| macOS    | ✅ Fully supported | Intel + Apple Silicon  |
| Windows  | ✅ Fully supported | PowerShell             |
| FreeBSD  | ✅ Supported       | Requires ffmpeg        |
| WSL2     | ✅ Supported       | Recommended on Windows |

---

## Input format

Podvoice consumes Markdown files with speaker blocks:

```markdown
[Host | calm]
Welcome to the show.

[Guest | warm]
If this sounds useful, try writing your own script
and see how easily Markdown becomes audio.
```

Rules:

* Speaker name is **required**
* Emotion tag is **optional**
* Text continues until the next speaker block
* Blank lines are allowed


---

## ▶️ Demo Video

<div align="center">
  


https://github.com/user-attachments/assets/c9e9c5f0-ce03-4d71-952f-927cab55bd83



</div>

## 🎧 Demo Audio

<div align="center">
  


https://github.com/user-attachments/assets/6f468a4f-c4c9-446c-a6b9-b365c3e7f131






</div>

---

## Quick start (ALL operating systems)

### 1️⃣ System requirements (common)

Required everywhere:

* **Python 3.10+** (3.10, 3.11, 3.12, or 3.13)
* **ffmpeg**
* Internet access **only for first run**
* ~5–8 GB free disk space (model cache)

---

### 2️⃣ Install system dependencies

#### 🐧 Linux (Ubuntu / Debian)

```bash
sudo apt update
sudo apt install -y python3 python3-venv ffmpeg git
```

---

#### 🍎 macOS (Homebrew)

```bash
brew install python ffmpeg git
```

---

#### 🪟 Windows (PowerShell)

```powershell
winget install Python.Python.3.13
winget install ffmpeg
winget install Git.Git
```

Restart the terminal after installing Python.

---

#### 🐡 FreeBSD

```sh
pkg install python3 ffmpeg git
```

---

### 3️⃣ Clone the repository

```bash
git clone https://github.com/aman179102/podvoice.git
cd podvoice
```

---

## Setup (recommended path)

### 🐧 Linux / 🍎 macOS / 🐡 FreeBSD

```bash
chmod +x bootstrap.sh
./bootstrap.sh
```

### 🪟 Windows (PowerShell)

#### One-time: allow local scripts

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

#### Run bootstrap

```powershell
.\bootstrap.ps1
```

The bootstrap script will:

* Detect your Python version (3.10+)
* Use **uv** for instant setup if available, otherwise fall back to pip
* Create a local `.venv`
* Install `podvoice` in editable mode

---

### Activate the environment

#### Linux / macOS / FreeBSD

```bash
source .venv/bin/activate
```

#### Windows

```powershell
.venv\Scripts\Activate.ps1
```

---

## Run the demo

```bash
podvoice examples/demo.md --out demo.wav
```

Or export MP3:

```bash
podvoice examples/demo.md --out demo.mp3
```

On first run, Coqui XTTS v2 model weights will be downloaded and cached locally.
Subsequent runs reuse the cache.

---

## CLI usage

```bash
podvoice SCRIPT.md --out OUTPUT
```

Default behavior is unchanged: Podvoice renders and writes one stitched output file.
Playback is optional and disabled by default.

Examples:

```bash
podvoice examples/demo.md --out output.wav
```

```bash
podvoice examples/demo.md --out podcast.mp3 --language en
```

```bash
podvoice render examples/demo.md --play
```

```bash
podvoice render examples/demo.md --play-stream
```

```bash
podvoice render examples/podcastprep.md --play-stream --stream-prebuffer-ms 4000 --stream-gap-ms 40
```

```bash
podvoice render examples/demo.md --play --out output.wav
```

### Options

| Option             | Description               |
| ------------------ | ------------------------- |
| `SCRIPT`           | Input Markdown file       |
| `--out`, `-o`      | Output `.wav` or `.mp3`   |
| `--play`           | Play locally after render |
| `--play-stream`    | Experimental live streaming playback during synthesis |
| `--stream-gap-ms`  | Silence between streamed segments in ms (default: 80, must be `>= 0`) |
| `--stream-prebuffer-ms` | Buffered audio duration (ms) before stream playback starts (default: 5000) |
| `--no-cache`       | Disable segment cache     |
| `--cache-dir`      | Override cache directory  |
| `--language`, `-l` | XTTS language code        |
| `--device`, `-d`   | `auto` (default), `cpu`, or `cuda` |
| `--cpu-threads`    | CPU thread count for PyTorch (default: OS default) |
| `--skip-normalize` | Skip audio normalization for faster draft renders |
| `--quality`        | MP3 export quality preset: `draft` (96k), `final` (192k) |
| `--max-segment-chars` | Max characters per TTS segment before chunking (default: 500) |
| `--language-policy` | Language drift guardrail: `warn`, `fail`, or `sanitize` (default: disabled) |

## Playback modes

Podvoice supports two optional playback modes in addition to file export:

* `--play`
	* Renders the full podcast and plays it through your local default speakers.
	* If `--out` is omitted, playback-only mode is used and no file is written.

* `--play-stream` (experimental)
	* Starts playback while later segments are still being synthesized.
	* Useful for long scripts when you want faster time-to-first-audio.
	* `--stream-prebuffer-ms` controls startup behavior (duration-based):
		* Lower values start earlier but may be less smooth on slower machines.
		* Higher values start later but can reduce underruns.
		* A low-watermark guard inserts brief padding silence when the buffer runs low.
	* `--stream-gap-ms` controls spacing between streamed chunks.
		* Set to `0` for no extra fixed silence between chunks.
		* Increase it if transitions sound abrupt.
	* Timing and device behavior can vary by platform and backend.

Validation notes:

* Podvoice rejects negative values for `--stream-gap-ms` and `--stream-prebuffer-ms`.
* Podvoice rejects using `--play` and `--play-stream` together in the same command.

Recommended stream tuning flow:

```bash
podvoice render examples/podcastprep.md --play-stream --stream-prebuffer-ms 5000 --stream-gap-ms 80
```

If playback starts too late, lower prebuffer:

```bash
podvoice render examples/podcastprep.md --play-stream --stream-prebuffer-ms 2000 --stream-gap-ms 80
```

If transitions feel abrupt, increase the stream gap:

```bash
podvoice render examples/podcastprep.md --play-stream --stream-prebuffer-ms 5000 --stream-gap-ms 120
```

Reproducibility note:

* File export is the deterministic baseline for reproducible artifacts.
* Live playback is local-device dependent and may vary in timing.

Windows and VS Code note:

* Running from the VS Code integrated terminal on Windows still uses the OS audio output device, so playback goes to your local speakers/headphones.

---

## Benchmarking

You can benchmark performance with phase-level timing breakdowns:

```bash
podvoice benchmark examples/demo.md --iterations 3 --no-cache
```

This reports per-run and average timings for:

* Parse
* Model load
* Synthesis
* Stitch
* Export

---

## GPU usage (optional)

Podvoice auto-detects CUDA when `--device auto` (the default).
To force GPU usage:

```bash
podvoice examples/demo.md --device cuda
```

If CUDA is unavailable, Podvoice safely falls back to CPU.

To control CPU thread count for inference:

```bash
podvoice examples/demo.md --device cpu --cpu-threads 4
```

---

## Segment chunking

Long text segments can cause slow or stalled synthesis. Podvoice automatically
splits segments that exceed `--max-segment-chars` (default: 500) at sentence
boundaries, preserving speaker and emotion metadata:

```bash
podvoice render examples/podcastprep.md --max-segment-chars 300
```

Cache keys are computed per chunk, so caching remains deterministic.

---

## Language drift guardrails

English renders can occasionally produce unintended non-English artifacts.
Use `--language-policy` to detect and handle cross-language drift:

```bash
# Warn on drift (log only, no text changes)
podvoice render examples/demo.md --language-policy warn

# Fail if drift detected
podvoice render examples/demo.md --language-policy fail

# Auto-sanitize non-target characters
podvoice render examples/demo.md --language-policy sanitize
```

Detection is local-only (Unicode range checks, no external APIs). Disabled by
default for backward compatibility.

---

## Draft renders

For fast iteration, skip normalization and use draft MP3 quality:

```bash
podvoice render examples/demo.md --out draft.mp3 --skip-normalize --quality draft
```

| Preset  | MP3 bitrate |
| ------- | ----------- |
| draft   | 96 kbps     |
| (none)  | 128 kbps    |
| final   | 192 kbps    |

---

## Daemon mode

Avoid reloading the model on every run by starting a persistent daemon:

```bash
# Start (keeps XTTS loaded in memory)
podvoice daemon start --language en --device auto

# Check status
podvoice daemon status

# Stop
podvoice daemon stop
```

The daemon serves a local HTTP API on `127.0.0.1:8473` by default.
Use `--host` and `--port` to change binding.

---

## Performance notes

You may see warnings like:

```
Could not initialize NNPACK! Reason: Unsupported hardware.
```

✔️ These are **harmless**
✔️ Audio generation will still complete
❌ No action required

---

## How voices are assigned

Podvoice does **not** train voices.

Instead:

* Uses built-in XTTS v2 speakers
* Hashes speaker names deterministically
* Maps each logical speaker to a stable voice

Implications:

* Same speaker name → same voice
* Rename speaker → possibly different voice
* XTTS update → mapping may change

Fallback: default XTTS voice.

---

## Project structure

```text
podvoice/
├── podvoice/
│   ├── cli.py        # CLI entrypoint
│   ├── parser.py     # Markdown parser
│   ├── tts.py        # XTTS inference
│   ├── audio.py      # Audio stitching
│   ├── chunking.py   # Segment chunking
│   ├── guardrails.py # Language drift detection
│   ├── daemon.py     # Persistent model server
│   └── utils.py
│
├── examples/
│   └── demo.md
│
├── bootstrap.sh
├── bootstrap.ps1
├── requirements.lock
├── pyproject.toml
└── README.md
```

---

## Responsible use

Podvoice generates natural-sounding speech.

Do **not**:

* Impersonate real people without consent
* Use generated audio for fraud or deception

Always disclose synthesized content where appropriate.

You are responsible for compliance with all applicable laws and licenses,
including those of Coqui XTTS v2.

---

## Contributing

Podvoice is intentionally simple.

Good contributions:

* Bug reports with minimal reproduction scripts
* CLI UX improvements
* Documentation clarity
* Cross-platform fixes

Non-goals:

* Cloud dependencies
* Training pipelines
* Over-engineering

**Goal:** local, boring, reliable software.

