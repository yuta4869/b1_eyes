#!/usr/bin/env python3
"""Tkinter GUI for the Mac camera + Ollama VLM app."""
from __future__ import annotations

import argparse
import os
import sys
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

import cv2
import requests
from PIL import Image, ImageTk

from main import OLLAMA_URL, VLMWorker, get_prompt

VIDEO_W, VIDEO_H = 640, 480
TICK_MS = 33


def list_ollama_models() -> list[str]:
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=2)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []


class App:
    def __init__(self, root: tk.Tk, default_model: str, camera_index: int):
        self.root = root
        self.root.title("VLM Camera — 物体認識 & 文字起こし")
        self.root.geometry("1180x680")
        self.camera_index = camera_index

        self.cap: cv2.VideoCapture | None = None
        self.worker: VLMWorker | None = None
        self.running = False
        self.latest_frame = None
        self.last_capture_t = 0.0
        self._last_shown_ts = 0.0
        self._photo: ImageTk.PhotoImage | None = None

        models = list_ollama_models()
        if default_model not in models and models:
            initial_model = default_model if default_model else models[0]
        else:
            initial_model = default_model
        self.model_var = tk.StringVar(value=initial_model)
        self.mode_var = tk.StringVar(value="manual")
        self.interval_var = tk.DoubleVar(value=4.0)
        self.lang_var = tk.StringVar(value="ja")
        self.status_var = tk.StringVar(value="停止中")
        self.fps_var = tk.StringVar(value="")

        self._build_ui(models)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._last_tick = time.time()
        self._frames_since = 0
        self.root.after(TICK_MS, self._tick)

    def _build_ui(self, models: list[str]) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        ctrl = ttk.Frame(outer)
        ctrl.pack(fill="x", pady=(0, 8))

        self.btn_start = ttk.Button(ctrl, text="▶ 開始", command=self.start, width=10)
        self.btn_stop = ttk.Button(ctrl, text="■ 停止", command=self.stop, width=10, state="disabled")
        self.btn_capture = ttk.Button(ctrl, text="📷 今すぐ認識", command=self.capture_now, state="disabled")
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop.pack(side="left", padx=2)
        self.btn_capture.pack(side="left", padx=8)

        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(ctrl, text="モード:").pack(side="left")
        ttk.Radiobutton(ctrl, text="手動", value="manual", variable=self.mode_var).pack(side="left")
        ttk.Radiobutton(ctrl, text="自動", value="auto", variable=self.mode_var).pack(side="left")

        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(ctrl, text="間隔:").pack(side="left")
        self.interval_scale = ttk.Scale(
            ctrl, from_=1.0, to=30.0, orient="horizontal",
            variable=self.interval_var, length=140, command=self._on_interval,
        )
        self.interval_scale.pack(side="left", padx=4)
        self.interval_label = ttk.Label(ctrl, text="4.0s", width=6)
        self.interval_label.pack(side="left")

        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(ctrl, text="言語:").pack(side="left")
        ttk.Radiobutton(ctrl, text="日本語", value="ja", variable=self.lang_var).pack(side="left")
        ttk.Radiobutton(ctrl, text="English", value="en", variable=self.lang_var).pack(side="left")

        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Label(ctrl, text="モデル:").pack(side="left")
        self.model_combo = ttk.Combobox(
            ctrl,
            textvariable=self.model_var,
            values=models or ["moondream", "llava"],
            width=22,
            state="readonly",
        )
        self.model_combo.pack(side="left", padx=2)
        ttk.Button(ctrl, text="↻", width=3, command=self._refresh_models).pack(side="left")

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)

        left = ttk.LabelFrame(body, text="カメラ映像", padding=4)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.video_label = tk.Label(left, bg="#101010", width=VIDEO_W, height=VIDEO_H)
        self.video_label.pack(fill="both", expand=True)

        right = ttk.LabelFrame(body, text="認識結果", padding=4)
        right.pack(side="right", fill="both", expand=True, padx=(4, 0))
        self.result_text = scrolledtext.ScrolledText(
            right, wrap="word", font=("Hiragino Sans", 13), height=20, width=42,
        )
        self.result_text.pack(fill="both", expand=True)
        self.result_text.insert("1.0", "「開始」を押してカメラを起動してください。\n自動モードでは指定間隔で繰り返し認識します。\n手動モードでは「今すぐ認識」を押した瞬間のフレームを送信します。")
        self.result_text.configure(state="disabled")

        status = ttk.Frame(outer)
        status.pack(fill="x", pady=(8, 0))
        ttk.Label(status, textvariable=self.status_var, foreground="#0a0").pack(side="left")
        ttk.Label(status, textvariable=self.fps_var, foreground="#666").pack(side="right")

    def _on_interval(self, _evt=None) -> None:
        self.interval_label.config(text=f"{self.interval_var.get():.1f}s")

    def _refresh_models(self) -> None:
        models = list_ollama_models()
        if models:
            self.model_combo["values"] = models
            if self.model_var.get() not in models:
                self.model_var.set(models[0])
        else:
            messagebox.showwarning("Ollama", "Ollamaに接続できません。`ollama serve` を実行してください。")

    def start(self) -> None:
        if self.running:
            return
        model = self.model_var.get().strip()
        if not model:
            messagebox.showerror("モデル未指定", "モデルを選択してください。")
            return
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            messagebox.showerror(
                "カメラエラー",
                "カメラを開けません。\nシステム設定 > プライバシーとセキュリティ > カメラ で、"
                "実行端末（ターミナル等）の権限を許可してください。",
            )
            self.cap = None
            return
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

        self.worker = VLMWorker()
        self.worker.start()
        self.running = True
        self.last_capture_t = 0.0
        self._last_shown_ts = 0.0
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_capture.config(state="normal")
        self.status_var.set("起動中…")
        self._set_result("カメラ起動。フレーム取得中…\nモデル・言語は実行中も切り替え可能（次回リクエストから反映）。")

    def stop(self) -> None:
        self.running = False
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.latest_frame = None
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_capture.config(state="disabled")
        self.status_var.set("停止中")
        self.fps_var.set("")
        self.video_label.configure(image="", bg="#101010")
        self._photo = None

    def _submit_frame(self, frame) -> bool:
        if self.worker is None:
            return False
        model = self.model_var.get().strip()
        lang = self.lang_var.get()
        return self.worker.submit(frame, model, get_prompt(lang), lang)

    def capture_now(self) -> None:
        if not self.running or self.worker is None or self.latest_frame is None:
            return
        if self.worker.busy:
            self.status_var.set("処理中… 完了まで待機")
            return
        if self._submit_frame(self.latest_frame.copy()):
            self.last_capture_t = time.time()

    def _set_result(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    def _tick(self) -> None:
        try:
            if self.running and self.cap is not None:
                ok, frame = self.cap.read()
                if ok:
                    self.latest_frame = frame
                    self._frames_since += 1
                    self._render_frame(frame)

                    now = time.time()
                    if (
                        self.mode_var.get() == "auto"
                        and self.worker is not None
                        and not self.worker.busy
                        and (now - self.last_capture_t) >= self.interval_var.get()
                    ):
                        if self._submit_frame(frame.copy()):
                            self.last_capture_t = now

                if self.worker is not None:
                    text, ts, meta = self.worker.latest
                    if ts > self._last_shown_ts and text:
                        self._last_shown_ts = ts
                        stamp = time.strftime("%H:%M:%S", time.localtime(ts))
                        meta_line = f"{meta.get('model','?')} / {meta.get('lang','?')} / {meta.get('elapsed',0):.1f}s"
                        note = meta.get("note", "")
                        header = f"[{stamp}] {meta_line}"
                        if note:
                            header += f"\n{note}"
                        self._set_result(f"{header}\n\n{text}")

                    if self.worker.busy:
                        self.status_var.set("VLM処理中…")
                    elif self._last_shown_ts:
                        self.status_var.set("待機（最終結果あり）")
                    else:
                        self.status_var.set("待機")

                now = time.time()
                if now - self._last_tick >= 1.0:
                    fps = self._frames_since / (now - self._last_tick)
                    self.fps_var.set(f"プレビュー {fps:.0f} fps")
                    self._last_tick = now
                    self._frames_since = 0
        except Exception as e:
            self.status_var.set(f"エラー: {e}")
        finally:
            self.root.after(TICK_MS, self._tick)

    def _render_frame(self, frame) -> None:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        img.thumbnail((VIDEO_W, VIDEO_H))
        self._photo = ImageTk.PhotoImage(img)
        self.video_label.configure(image=self._photo, width=img.width, height=img.height)

    def on_close(self) -> None:
        if self.running:
            self.stop()
        self.root.after(50, self.root.destroy)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="moondream")
    parser.add_argument("--camera", type=int, default=0)
    args = parser.parse_args()

    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.4)
    except tk.TclError:
        pass

    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "icon_src.png")
    if os.path.exists(icon_path):
        try:
            icon_img = tk.PhotoImage(file=icon_path)
            root.iconphoto(True, icon_img)
            root._icon_ref = icon_img
        except tk.TclError:
            pass

    App(root, default_model=args.model, camera_index=args.camera)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
