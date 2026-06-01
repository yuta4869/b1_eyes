#!/usr/bin/env python3
"""Mac camera + Ollama (LLaVA) で物体認識と文字起こしを行うCLI。"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import textwrap
import threading
import time
from queue import Queue, Empty

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass

import cv2
import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont

OLLAMA_URL = "http://localhost:11434/api/generate"

PROMPTS = {
    "ja": (
        "この画像に写っている主な物体を日本語で説明し、"
        "画像中に見える文字があればそのまま書き起こしてください。"
    ),
    "en": (
        "Describe the main objects in this image, "
        "and transcribe any visible text exactly as shown."
    ),
}

VISION_EN_ONLY_MODELS = {"moondream", "bakllava"}

TRANSLATION_MODEL = "llama3.2:3b"


def is_vision_en_only(model: str) -> bool:
    base = model.split(":")[0].lower()
    return base in VISION_EN_ONLY_MODELS


def get_prompt(lang: str) -> str:
    return PROMPTS.get(lang, PROMPTS["en"])

JP_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴ ProN W3.otf",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    # Linux / WSL (fonts-noto-cjk package)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # Windows (if invoked from Windows-side Python)
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]


def parse_camera_source(value: str):
    """Accept '0', '/dev/video0', 'rtsp://host', 'http://host/stream' etc.
    Returns an int when the string is a plain integer; otherwise the string."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def load_jp_font(size: int) -> ImageFont.ImageFont:
    for path in JP_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def encode_jpeg_b64(frame: np.ndarray, quality: int = 80, max_side: int = 768) -> str | None:
    h, w = frame.shape[:2]
    longest = max(h, w)
    if longest > max_side:
        scale = max_side / longest
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


def call_ollama(
    image_b64: str | None,
    model: str,
    prompt: str,
    timeout: float = 180.0,
) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "30m",
        "options": {
            "temperature": 0.2,
            "num_ctx": 2048,
            "num_predict": 220,
        },
    }
    if image_b64 is not None:
        payload["images"] = [image_b64]
    r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json().get("response", "").strip()


def translate_to_ja(english_text: str) -> str:
    """Translate English VLM output to Japanese using a small text model.
    Falls back to the original text if the translator model is not available."""
    if not english_text:
        return english_text
    prompt = (
        "次の英文を自然な日本語に翻訳してください。"
        "原文の意味と固有名詞・数字・引用符内の文字は厳密に保ち、"
        "翻訳結果のみを出力してください。前置きや注釈は付けないこと。\n\n"
        f"英文:\n{english_text}\n\n日本語訳:"
    )
    try:
        return call_ollama(None, TRANSLATION_MODEL, prompt, timeout=60.0)
    except Exception as e:
        return f"{english_text}\n\n[翻訳失敗: {e}]"


class VLMWorker(threading.Thread):
    """Worker thread that runs VLM calls. Model and prompt are passed per-submit."""

    def __init__(self):
        super().__init__(daemon=True)
        self.in_q: Queue = Queue(maxsize=1)
        self.lock = threading.Lock()
        self._latest_text: str = ""
        self._latest_ts: float = 0.0
        self._latest_meta: dict = {}
        self._busy: bool = False
        self._stop = threading.Event()

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def latest(self) -> tuple[str, float, dict]:
        with self.lock:
            return self._latest_text, self._latest_ts, dict(self._latest_meta)

    def submit(self, frame: np.ndarray, model: str, prompt: str, lang: str = "") -> bool:
        if self._busy:
            return False
        try:
            self.in_q.put_nowait({"frame": frame, "model": model, "prompt": prompt, "lang": lang})
            return True
        except Exception:
            return False

    def stop(self) -> None:
        self._stop.set()
        try:
            self.in_q.put_nowait(None)
        except Exception:
            pass

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self.in_q.get(timeout=0.5)
            except Empty:
                continue
            if item is None:
                break
            self._busy = True
            t0 = time.time()
            model = item["model"]
            lang = item.get("lang", "en")
            note = ""
            try:
                b64 = encode_jpeg_b64(item["frame"])
                if b64 is None:
                    raise RuntimeError("JPEGエンコード失敗")

                if lang == "ja" and is_vision_en_only(model):
                    en_out = call_ollama(b64, model, PROMPTS["en"])
                    if not en_out:
                        text = "[空の応答] モデルが何も返しませんでした。別のモデルを試してください。"
                    else:
                        ja_out = translate_to_ja(en_out)
                        text = ja_out
                        note = f"(VLM={model} EN → 翻訳={TRANSLATION_MODEL})"
                else:
                    prompt = item["prompt"]
                    raw = call_ollama(b64, model, prompt)
                    if not raw:
                        text = (
                            "[空の応答] モデルがプロンプトに応答しませんでした。"
                            "別のモデル（llava 等）を試してください。"
                        )
                    else:
                        text = raw
            except requests.HTTPError as e:
                text = f"[HTTPエラー] {e.response.status_code}: {e.response.text[:200]}"
            except requests.ConnectionError:
                text = "[接続エラー] Ollamaが起動していますか? `ollama serve`"
            except Exception as e:
                text = f"[エラー] {type(e).__name__}: {e}"
            dt = time.time() - t0
            with self.lock:
                self._latest_text = text
                self._latest_ts = time.time()
                self._latest_meta = {
                    "model": model,
                    "lang": lang,
                    "elapsed": dt,
                    "note": note,
                }
            print(f"\n===== {time.strftime('%H:%M:%S')} model={model} lang={lang} ({dt:.1f}s) =====")
            if note:
                print(note)
            print(text)
            print("=" * 40)
            self._busy = False


def wrap_text_lines(text: str, width_chars: int = 42, max_lines: int = 10) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            lines.append("")
            continue
        chunks = []
        cur = ""
        cur_w = 0
        for ch in raw:
            w = 2 if ord(ch) > 0x7F else 1
            if cur_w + w > width_chars:
                chunks.append(cur)
                cur, cur_w = ch, w
            else:
                cur += ch
                cur_w += w
        if cur:
            chunks.append(cur)
        lines.extend(chunks)
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["…"]
    return lines


def render_overlay(
    frame: np.ndarray,
    mode: str,
    interval: float,
    busy: bool,
    last_text: str,
    last_age: float | None,
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
) -> np.ndarray:
    h, w = frame.shape[:2]
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img, "RGBA")

    status = "処理中…" if busy else "待機"
    header = f"モード:{mode}  間隔:{interval:.1f}s  状態:{status}"
    help_line = "[Space]撮影  [m]モード切替  [+/-]間隔  [s]保存  [q]終了"

    draw.rectangle([0, 0, w, 70], fill=(0, 0, 0, 160))
    draw.text((10, 6), header, font=font_small, fill=(0, 255, 120, 255))
    draw.text((10, 36), help_line, font=font_small, fill=(220, 220, 220, 255))

    if last_text:
        lines = wrap_text_lines(last_text, width_chars=46, max_lines=10)
        line_h = font.size + 4
        box_h = line_h * len(lines) + 18
        y0 = h - box_h
        draw.rectangle([0, y0, w, h], fill=(0, 0, 0, 180))
        if last_age is not None:
            age_str = f"({last_age:.0f}s前)"
            draw.text((w - 110, y0 + 4), age_str, font=font_small, fill=(180, 180, 180, 255))
        for i, line in enumerate(lines):
            draw.text((10, y0 + 8 + i * line_h), line, font=font, fill=(255, 255, 255, 255))

    if busy:
        draw.ellipse([w - 30, 80, w - 14, 96], fill=(255, 60, 60, 255))

    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mac camera + Ollama VLM")
    parser.add_argument("--model", default="moondream", help="Ollamaビジョンモデル名 (例: moondream, llava, llava:13b, llama3.2-vision)")
    parser.add_argument("--camera", default="0", help="カメラ指定: 整数インデックス / /dev/video0 / rtsp:// / http://")
    parser.add_argument("--auto", action="store_true", help="自動キャプチャモードで起動")
    parser.add_argument("--interval", type=float, default=4.0, help="自動キャプチャ間隔 (秒)")
    parser.add_argument("--width", type=int, default=1280, help="撮影解像度 (幅)")
    parser.add_argument("--height", type=int, default=720, help="撮影解像度 (高さ)")
    parser.add_argument("--save-dir", default=None, help="[s]キーで保存するフォルダ (省略時はカレント)")
    parser.add_argument("--lang", default="ja", choices=["ja", "en"], help="出力言語 (ja: 日本語 / en: English)")
    args = parser.parse_args()

    cam_src = parse_camera_source(args.camera)
    cap = cv2.VideoCapture(cam_src)
    if not cap.isOpened():
        print(f"カメラ({cam_src!r})を開けませんでした。", file=sys.stderr)
        print("- macOS: システム設定 > プライバシーとセキュリティ > カメラ で許可", file=sys.stderr)
        print("- WSL2: usbipd-win でカメラをアタッチ (例: usbipd attach --wsl --busid X-Y)", file=sys.stderr)
        print("        または --camera rtsp://... / http://.../stream を指定", file=sys.stderr)
        return 2
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    font = load_jp_font(20)
    font_small = load_jp_font(16)

    worker = VLMWorker()
    worker.start()

    mode = "auto" if args.auto else "manual"
    interval = max(0.5, args.interval)
    last_capture_t = 0.0
    save_dir = args.save_dir or os.getcwd()
    lang = args.lang

    print(f"モデル: {args.model}  モード: {mode}  間隔: {interval}s  言語: {lang}")
    print("ウィンドウを選択した状態で [q] 終了 / [Space] 撮影 / [m] モード切替 / [+/-] 間隔 / [s] 保存")

    win = "VLM Camera"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("フレーム取得失敗", file=sys.stderr)
                break

            now = time.time()
            text, ts, _ = worker.latest
            age = (now - ts) if ts > 0 else None
            display = render_overlay(frame, mode, interval, worker.busy, text, age, font, font_small)
            cv2.imshow(win, display)

            should_capture = (
                mode == "auto"
                and not worker.busy
                and (now - last_capture_t) >= interval
            )

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q") or key == 27:
                break
            elif key == ord("m"):
                mode = "auto" if mode == "manual" else "manual"
                print(f"[mode] -> {mode}")
            elif key == ord(" "):
                if worker.busy:
                    print("[busy] 前のリクエスト処理中")
                else:
                    should_capture = True
            elif key in (ord("+"), ord("=")):
                interval = min(60.0, interval + 1.0)
                print(f"[interval] {interval}s")
            elif key in (ord("-"), ord("_")):
                interval = max(0.5, interval - 1.0)
                print(f"[interval] {interval}s")
            elif key == ord("s"):
                fname = os.path.join(save_dir, f"capture_{time.strftime('%Y%m%d_%H%M%S')}.jpg")
                cv2.imwrite(fname, frame)
                print(f"[saved] {fname}")

            if should_capture:
                if worker.submit(frame.copy(), args.model, get_prompt(lang), lang):
                    last_capture_t = now
                    print(f"[capture] {time.strftime('%H:%M:%S')} 送信")
    except KeyboardInterrupt:
        pass
    finally:
        worker.stop()
        cap.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    sys.exit(main())
