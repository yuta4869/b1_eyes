#!/usr/bin/env bash
# WSL2 (Ubuntu) + CUDA 用のセットアップスクリプト。
# 想定: Windows 11 + WSL2 (Ubuntu 22.04 以降) + NVIDIA GPU + Windows ホスト側 GeForce ドライバ済み。
set -euo pipefail

cd "$(dirname "$0")"

echo "[1/5] apt パッケージのインストール (sudo)"
sudo apt update
sudo apt install -y \
    python3 python3-venv python3-pip python3-tk \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    fonts-noto-cjk \
    v4l-utils \
    curl

echo "[2/5] Python venv の作成"
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "[3/5] Ollama のインストール (未導入の場合)"
if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "[4/5] CUDA 認識確認"
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi -L || true
    echo "→ Ollama は CUDA を自動検出して使います ('ollama serve' でサーバ起動後 'ollama ps' で確認)"
else
    echo "⚠  nvidia-smi が見つかりません。WSL2 から GPU を使うには:"
    echo "   1) Windows ホストに最新の GeForce/Studio ドライバを入れる"
    echo "   2) PowerShell (管理者) で 'wsl --update'"
    echo "   3) WSL を再起動 'wsl --shutdown' → ターミナル再オープン"
fi

echo "[5/5] モデルの取得"
ollama pull moondream || true
ollama pull llava || true
ollama pull llama3.2:3b || true

cat <<'NEXT'

==================== セットアップ完了 ====================
■ カメラ (WSL2 で USB Web カメラを使う場合)
  WSL2 は USB を直接見えないので usbipd-win を Windows 側にインストール:
    winget install usbipd
  Windows の PowerShell (管理者) で:
    usbipd list                       # カメラの BUSID を確認
    usbipd bind --busid <X-Y>
    usbipd attach --wsl --busid <X-Y>
  その後 WSL 側で:
    ls -l /dev/video*                 # /dev/video0 などが出れば成功
    .venv/bin/python gui.py --camera /dev/video0
  USB カメラが無い場合: スマホの IP カメラアプリ等で RTSP/HTTP 配信し
    .venv/bin/python gui.py --camera rtsp://<host>:8554/...

■ 起動
  .venv/bin/python gui.py               # GUI (WSLg or X server 必要)
  .venv/bin/python main.py --auto       # CLI

■ Ollama サーバが落ちている場合
  ollama serve &                        # バックグラウンドで起動
NEXT
