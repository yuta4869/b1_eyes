# b1_eyes

A small local-VLM camera assistant. Capture frames from a webcam, send them to an [Ollama](https://ollama.com)-hosted vision model, and display objects + transcribed text in real time.

Runs on **macOS** (Apple Silicon, Metal) and **WSL2 / Linux** (NVIDIA CUDA). 100% local — no cloud APIs.

[日本語版 README](README.ja.md)

---

## Features

- Live camera preview with Tkinter GUI **and** OpenCV CLI
- Manual or automatic capture at a configurable interval
- Per-request model and language switching (no restart)
- Output language: **English** or **Japanese**
- Automatic fallback for English-only vision models (e.g. moondream): VLM call in English, then translation to Japanese via a small text model
- Image is downscaled to 768 px before upload; KV cache is kept warm via `keep_alive=30m`
- macOS app bundle (`VLM Camera.app`) with a custom Dock icon — double-click to launch
- Flexible camera source: device index, `/dev/video0`, or RTSP/HTTP URL (for WSL or IP cameras)

## Architecture

```
        ┌─────────────┐    JPEG (base64)    ┌────────────────────┐
        │   GUI/CLI   │  ────────────────▶  │  Ollama (Metal/    │
        │  (Python)   │  ◀────── text ───── │   CUDA)            │
        └─────────────┘                     │  - moondream       │
              ▲                             │  - llava           │
              │                             │  - llama3.2:3b (T) │
        Webcam frame                        └────────────────────┘
        (OpenCV / V4L2 /
         RTSP / HTTP)
```

`T` = translator. When the selected vision model can't produce Japanese, the worker pipelines through a text-only model to translate.

## Requirements

| Component | Version |
|---|---|
| Python | 3.10+ (3.14 tested) |
| Ollama | latest |
| OS | macOS 13+ (Apple Silicon) **or** WSL2 Ubuntu 22.04+ |
| GPU | Apple Silicon (Metal) **or** NVIDIA + CUDA (auto-detected by Ollama) |

## Setup

### macOS

```bash
brew install python-tk@3.14         # Tk for the system Python you'll use
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Pull at least one vision model
ollama pull moondream               # fast (~1.7 GB)
ollama pull llava                   # better Japanese, ~4.7 GB
ollama pull llama3.2:3b             # used as JA translator for moondream
```

Build the `.app` bundle (optional, lets you double-click to launch with a custom icon):

```bash
./build_app.sh
open "VLM Camera.app"
```

The first launch will trigger a macOS camera-permission dialog.

### WSL2 + CUDA

Requires: Windows 11 + WSL2 (Ubuntu 22.04+) + a recent NVIDIA Windows driver.

```bash
bash setup_wsl.sh
```

The script installs apt packages (`python3-tk`, `libgl1`, `fonts-noto-cjk`, `v4l-utils`, ...), creates the venv, installs Ollama, and pulls the default models.

**Camera in WSL2** — WSL doesn't see Windows USB devices directly. Use [usbipd-win](https://github.com/dorssel/usbipd-win):

```powershell
# Windows PowerShell (Admin)
winget install usbipd
usbipd list                         # find your camera's BUSID
usbipd bind --busid <X-Y>
usbipd attach --wsl --busid <X-Y>
```

Then in WSL:

```bash
ls -l /dev/video*                   # /dev/video0 should appear
.venv/bin/python gui.py --camera /dev/video0
```

If you don't have a USB camera, you can stream from a phone (e.g. RTSP app) and use:

```bash
.venv/bin/python gui.py --camera rtsp://<phone-ip>:8554/stream
```

Verify CUDA: after `ollama serve` is up, `ollama ps` should show `100% GPU`.

## Usage

### GUI

```bash
.venv/bin/python gui.py                  # default: moondream
.venv/bin/python gui.py --model llava    # better Japanese, slower
.venv/bin/python gui.py --camera /dev/video0
```

Controls:
- **▶ 開始 / ■ 停止** — start / stop camera
- **📷 今すぐ認識** — capture the current frame manually
- **モード** — manual / auto (auto-captures every N seconds)
- **間隔** — auto-capture interval slider (1–30 s)
- **言語** — 日本語 / English (applies to the next request, even mid-run)
- **モデル** — vision model dropdown (applies to the next request)

### CLI (OpenCV window)

```bash
.venv/bin/python main.py --auto --interval 4 --lang ja --model moondream
```

Keys inside the window: `Space` capture, `m` toggle mode, `+/-` interval, `s` save frame, `q` quit.

## Configuration notes

- **Model recommendations**
  - English, fast: `moondream` (~0.4 s / call on M-series, similar on a mid-range NVIDIA GPU)
  - Japanese, direct: `llava` (~2–3 s / call)
  - Highest quality: `ollama pull llama3.2-vision` (11 B; use `--model llama3.2-vision`)
- **English-only vision models** (`moondream`, `bakllava`) are listed in `VISION_EN_ONLY_MODELS` in `main.py`. When you choose Japanese with one of these, the worker calls the VLM in English and translates with `llama3.2:3b`.
- **Image size** is capped at 768 px on the long edge by `encode_jpeg_b64`. CLIP-based vision models internally resize to ~336 px anyway, so this lossless trim cuts upload latency without hurting quality.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| "[空の応答]" in result panel | Vision model returned 0 tokens. Switch to `llava` or rephrase by editing `PROMPTS` in `main.py`. |
| Garbled (Thai-like) Japanese | Selected an English-only vision model with `lang=ja` and no `llama3.2:3b` translator. Pull it: `ollama pull llama3.2:3b`. |
| `Camera (...) failed to open` | macOS: grant Terminal camera permission in System Settings. WSL: attach via `usbipd` or use RTSP URL. |
| `_tkinter` not found on Linux | `sudo apt install python3-tk` |
| Result text shows boxes for Japanese | Install Noto CJK: `sudo apt install fonts-noto-cjk` |
| Ollama returns 404 | `ollama serve &` to start the daemon, then verify with `ollama ps`. |

## Files

| File | Purpose |
|---|---|
| `main.py` | OpenCV CLI + shared worker / prompt / model logic |
| `gui.py` | Tkinter GUI |
| `make_icon.py` | Generate the app icon PNG |
| `build_app.sh` | Build `VLM Camera.app` (macOS only) |
| `setup_wsl.sh` | Install dependencies on WSL2 / Ubuntu |
| `requirements.txt` | Python dependencies (opencv-python, requests, Pillow) |

## License

MIT (no LICENSE file checked in yet — add one if you intend to redistribute).
