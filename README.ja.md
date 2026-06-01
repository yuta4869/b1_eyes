# b1_eyes

ローカルVLMによるカメラアシスタント。Webカメラのフレームを[Ollama](https://ollama.com)上のビジョンモデルに送り、写っている物体と画像中の文字をリアルタイムで表示します。

**macOS** (Apple Silicon, Metal) と **WSL2 / Linux** (NVIDIA CUDA) で動作。完全ローカル動作・クラウドAPI不使用。

[English README](README.md)

---

## 機能

- Tkinter GUI **と** OpenCV CLI の両対応・カメラ映像をライブ表示
- 手動キャプチャ / 一定間隔の自動キャプチャ
- モデルと言語を実行中でも切替可能（次回リクエストから即反映）
- 出力言語: **日本語** または **英語**
- 英語のみのビジョンモデル (例: moondream) を選んでも日本語出力可能 — 英語でVLM呼び出し→小型テキストモデルで翻訳
- 画像は送信前に長辺768pxへリサイズ、`keep_alive=30m` でモデルをVRAMに常駐
- macOSは独自アイコン付きの`.app`バンドル (`VLM Camera.app`) で**ダブルクリック起動**可能
- カメラソースは柔軟指定: デバイスインデックス / `/dev/video0` / RTSP・HTTP URL (WSL や IP カメラ用)

## アーキテクチャ

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

`T` は翻訳役。選んだビジョンモデルが日本語を生成できない場合、ワーカーはテキスト専用モデルを経由して翻訳します。

## 動作環境

| 要素 | バージョン |
|---|---|
| Python | 3.10 以上 (3.14 で検証) |
| Ollama | 最新版 |
| OS | macOS 13+ (Apple Silicon) **または** WSL2 Ubuntu 22.04+ |
| GPU | Apple Silicon (Metal) **または** NVIDIA + CUDA (Ollamaが自動検出) |

## セットアップ

### macOS

```bash
brew install python-tk@3.14         # 使うPythonに対応するTk
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# ビジョンモデルを最低1つ取得
ollama pull moondream               # 高速 (~1.7 GB)
ollama pull llava                   # 日本語OK・~4.7 GB
ollama pull llama3.2:3b             # moondream用の日本語翻訳役
```

`.app`バンドルをビルド（任意。ダブルクリック起動 + Dockカスタムアイコン）:

```bash
./build_app.sh
open "VLM Camera.app"
```

初回起動時にmacOSのカメラ権限ダイアログが表示されます。

### WSL2 + CUDA

前提: Windows 11 + WSL2 (Ubuntu 22.04+) + 最新のNVIDIA Windowsドライバ。

```bash
bash setup_wsl.sh
```

スクリプトがaptパッケージ (`python3-tk`, `libgl1`, `fonts-noto-cjk`, `v4l-utils`, ...) のインストール、venv作成、Ollamaのインストール、デフォルトモデルの取得まで実行します。

**WSL2でカメラを使うには** — WSL2はWindowsのUSBデバイスを直接認識できません。[usbipd-win](https://github.com/dorssel/usbipd-win) を使います:

```powershell
# Windows PowerShell (管理者で実行)
winget install usbipd
usbipd list                         # カメラの BUSID を確認
usbipd bind --busid <X-Y>
usbipd attach --wsl --busid <X-Y>
```

WSL側で:

```bash
ls -l /dev/video*                   # /dev/video0 などが見えればOK
.venv/bin/python gui.py --camera /dev/video0
```

USBカメラが手元になければ、スマホをRTSPカメラ化するアプリ等で配信し:

```bash
.venv/bin/python gui.py --camera rtsp://<phone-ip>:8554/stream
```

CUDA動作確認: `ollama serve` 起動後、`ollama ps` の PROCESSOR 列が `100% GPU` になればCUDA利用中です。

## 使い方

### GUI

```bash
.venv/bin/python gui.py                  # デフォルト: moondream
.venv/bin/python gui.py --model llava    # 日本語精度↑・速度↓
.venv/bin/python gui.py --camera /dev/video0
```

操作:
- **▶ 開始 / ■ 停止** — カメラ開始 / 停止
- **📷 今すぐ認識** — 現在のフレームを手動で送信
- **モード** — 手動 / 自動 (指定秒数ごとに自動キャプチャ)
- **間隔** — 自動キャプチャ間隔のスライダー (1〜30秒)
- **言語** — 日本語 / English (次回リクエストから反映・実行中切替可)
- **モデル** — ビジョンモデルのドロップダウン (次回リクエストから反映)

### CLI (OpenCVウィンドウ)

```bash
.venv/bin/python main.py --auto --interval 4 --lang ja --model moondream
```

ウィンドウ上でのキー操作: `Space` 撮影 / `m` モード切替 / `+/-` 間隔 / `s` フレーム保存 / `q` 終了

## 設定メモ

- **モデルの選び方**
  - 英語・高速: `moondream` (~0.4秒/回・M系/ミドルクラスNVIDIA GPU)
  - 日本語・直接: `llava` (~2〜3秒/回)
  - 高精度: `ollama pull llama3.2-vision` (11B・`--model llama3.2-vision`)
- **英語のみのビジョンモデル** (`moondream`, `bakllava`) は `main.py` の `VISION_EN_ONLY_MODELS` に列挙されています。これらを選んで言語を日本語にすると、英語でVLM呼び出し→`llama3.2:3b` で翻訳のパイプラインに自動切替されます。
- **画像サイズ**は `encode_jpeg_b64` で長辺768pxに自動リサイズ。CLIP系のビジョンモデルは内部で~336pxにさらに縮小するため、品質を落とさずアップロード遅延だけを削減します。

## トラブルシューティング

| 症状 | 原因 / 対処 |
|---|---|
| 結果欄に「[空の応答]」 | ビジョンモデルが0トークンで停止。`llava` に切替、または `main.py` の `PROMPTS` を書き換える。 |
| 日本語が文字化け (タイ語風など) | 英語専用ビジョンモデル + 日本語選択時に翻訳モデルが未取得。`ollama pull llama3.2:3b` を実行。 |
| `カメラ (...) を開けません` | macOS: システム設定 > プライバシーとセキュリティ > カメラ で許可。 WSL: `usbipd` でアタッチ、または RTSP URL を指定。 |
| Linuxで `_tkinter` not found | `sudo apt install python3-tk` |
| 結果欄の日本語が□に化ける | Noto CJK を導入: `sudo apt install fonts-noto-cjk` |
| Ollama が 404 を返す | `ollama serve &` でデーモン起動、`ollama ps` で確認。 |

## ファイル

| ファイル | 役割 |
|---|---|
| `main.py` | OpenCV CLI + 共通ワーカー / プロンプト / モデルロジック |
| `gui.py` | Tkinter GUI |
| `make_icon.py` | アプリアイコンPNG生成 |
| `build_app.sh` | `VLM Camera.app` のビルド (macOS専用) |
| `setup_wsl.sh` | WSL2 / Ubuntu の依存セットアップ |
| `requirements.txt` | Python依存 (opencv-python, requests, Pillow) |

## ライセンス

MIT (LICENSEファイルは未配置。再配布する場合は追加してください)。
