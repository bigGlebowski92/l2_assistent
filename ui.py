"""Tkinter UI. Entry: python ui.py — aim+click assistant, F12 stops."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk, scrolledtext
from typing import Optional

from bot import AssistBot, load_config, save_config, preview_ppms


def set_dpi_awareness() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


class Calibrator(tk.Toplevel):
    """Semi-transparent HP region picker."""

    def __init__(self, master: tk.Tk, title: str, initial: Optional[dict], on_save):
        super().__init__(master)
        self._on_save = on_save
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.45)
        self.configure(bg="#922b21")
        bar_h = 28
        if initial and all(k in initial for k in ("left", "top", "width", "height")):
            self.geometry(
                f"{max(40, int(initial['width']))}x{max(20, int(initial['height'])) + bar_h}"
                f"+{int(initial['left'])}+{int(initial['top'])}"
            )
        else:
            self.geometry("260x80+200+200")

        self.body = tk.Frame(self, bg="#e74c3c", cursor="fleur")
        self.body.pack(fill="both", expand=True)
        tk.Label(self.body, text=title, bg="#e74c3c", fg="white").pack(expand=True)

        bar = tk.Frame(self, bg="#922b21", height=bar_h)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        tk.Button(bar, text="Зберегти", command=self._save).pack(side="left", padx=4, pady=2)
        handle = tk.Frame(bar, bg="white", width=14, height=14, cursor="sizing")
        handle.pack(side="right", padx=3, pady=6)
        handle.pack_propagate(False)

        self.bind("<Return>", lambda e: self._save())
        self.body.bind("<ButtonPress-1>", self._press_move)
        self.body.bind("<B1-Motion>", self._move)
        handle.bind("<ButtonPress-1>", self._press_resize)
        handle.bind("<B1-Motion>", self._resize)
        self._dx = self._dy = 0
        self.focus_force()

    def _press_move(self, e):
        self._dx, self._dy = e.x, e.y

    def _move(self, e):
        self.geometry(f"+{self.winfo_x() + e.x - self._dx}+{self.winfo_y() + e.y - self._dy}")

    def _press_resize(self, e):
        self._dx, self._dy = self.winfo_width(), self.winfo_height()
        self._ox, self._oy = e.x_root, e.y_root

    def _resize(self, e):
        w = max(40, self._dx + (e.x_root - self._ox))
        h = max(48, self._dy + (e.y_root - self._oy))
        self.geometry(f"{w}x{h}")

    def _save(self) -> None:
        self.update_idletasks()
        self._on_save(
            {
                "left": int(self.body.winfo_rootx()),
                "top": int(self.body.winfo_rooty()),
                "width": int(self.body.winfo_width()),
                "height": int(self.body.winfo_height()),
            }
        )
        self.destroy()


class PointPicker(tk.Toplevel):
    """One click saves aim coordinates for a skill slot."""

    def __init__(self, master: tk.Tk, title: str, on_save):
        super().__init__(master)
        self._on_save = on_save
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.25)
        self.configure(bg="#1a5276")
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        tk.Label(
            self,
            text=f"{title}\nКлікніть по слоту — збережеться лише позиція курсора",
            bg="#1a5276",
            fg="white",
            font=("Segoe UI", 16, "bold"),
        ).pack(expand=True)
        self.bind("<ButtonPress-1>", self._pick)
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_force()

    def _pick(self, e) -> None:
        self._on_save({"x": int(e.x_root), "y": int(e.y_root)})
        self.destroy()


class CalibPreview(tk.Toplevel):
    def __init__(self, master: tk.Tk, cfg: dict):
        super().__init__(master)
        self.cfg = cfg
        self.title("Перевірка калібрування")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._sct = None
        self._after = None
        self._imgs: list = []

        ttk.Button(self, text="Закрити", command=self._close).pack(anchor="e", padx=6, pady=4)
        self.sections = {}
        for key, title in (("target_region", "HP цілі"), ("own_hp_region", "Моє HP")):
            frm = tk.LabelFrame(self, text=title, padx=6, pady=4)
            frm.pack(fill="x", padx=8, pady=4)
            status = tk.Label(frm, text="")
            status.pack(anchor="w")
            img = tk.Label(frm)
            img.pack()
            strip = tk.Label(frm)
            strip.pack()
            self.sections[key] = (status, img, strip)
        try:
            import mss

            self._sct = mss.mss()
        except Exception as exc:
            tk.Label(self, text=f"mss недоступний: {exc}", fg="red").pack(padx=8, pady=4)
        self._tick()

    def _photo(self, ppm: bytes, zoom: int) -> tk.PhotoImage:
        img = tk.PhotoImage(data=ppm, format="PPM")
        return img.zoom(zoom, zoom) if zoom > 1 else img

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        self._imgs.clear()
        red_min = self.cfg.get("red_min", 120)
        red_ratio = self.cfg.get("red_ratio", 1.8)
        for key, (status, img, strip_lbl) in self.sections.items():
            region = self.cfg.get(key)
            if not region:
                status.config(text="не відкалібровано")
                img.config(image="")
                strip_lbl.config(image="")
                continue
            if self._sct is None:
                status.config(text="немає mss")
                continue
            try:
                box = {k: int(region[k]) for k in ("left", "top", "width", "height")}
                shot = self._sct.grab(box)
                bgra = shot.bgra if hasattr(shot, "bgra") else bytes(shot.raw)
                ppm, strip, hp = preview_ppms(bgra, shot.width, shot.height, red_min, red_ratio)
            except Exception as exc:
                status.config(text=f"помилка: {exc}")
                continue
            zoom = max(1, min(16, 300 // max(1, shot.width)))
            photo, mask = self._photo(ppm, zoom), self._photo(strip, zoom)
            self._imgs.extend((photo, mask))
            status.config(text=f"HP: {hp}%")
            img.config(image=photo)
            strip_lbl.config(image=mask)
        self._after = self.after(500, self._tick)

    def _close(self) -> None:
        if self._after is not None:
            self.after_cancel(self._after)
            self._after = None
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
        self.destroy()


class App(tk.Tk):
    FIELDS = (
        ("pause_min_ms", "Пауза мін (мс)", 8),
        ("pause_max_ms", "Пауза макс (мс)", 8),
        ("stuck_seconds", "Застрягання (с)", 8),
        ("max_stuck", "Макс. застрягань", 8),
        ("own_hp_stop", "Поріг HP → F3 (%)", 8),
    )

    def __init__(self):
        super().__init__()
        self.title("L2 асистент")
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.cfg = load_config()
        self.q: queue.Queue = queue.Queue()
        self.bot: Optional[AssistBot] = None
        self._kb = None
        self.vars = {key: tk.StringVar(value=str(self.cfg.get(key, ""))) for key, *_ in self.FIELDS}

        pad = {"padx": 6, "pady": 2}
        self.lbl_target = tk.Label(self, text="HP цілі: —%", font=("Segoe UI", 11, "bold"))
        self.lbl_own = tk.Label(self, text="Моє HP: —%", font=("Segoe UI", 11, "bold"))
        self.lbl_target.grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        self.lbl_own.grid(row=1, column=0, columnspan=2, sticky="w", **pad)

        for i, (key, label, width) in enumerate(self.FIELDS, start=2):
            tk.Label(self, text=label).grid(row=i, column=0, sticky="w", **pad)
            tk.Entry(self, textvariable=self.vars[key], width=width).grid(row=i, column=1, sticky="ew", **pad)

        btns = tk.Frame(self)
        btns.grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        self.btn_start = ttk.Button(btns, text="Старт", command=self._start)
        self.btn_stop = ttk.Button(
            btns, text="Стоп", command=lambda: self._request_stop("Зупинено користувачем."), state="disabled"
        )
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop.pack(side="left", padx=4)

        cal = tk.Frame(self)
        cal.grid(row=8, column=0, columnspan=2, sticky="ew")
        ttk.Button(cal, text="Калібрувати ціль", command=lambda: self._calibrate("target_region", "HP цілі")).pack(
            side="left", padx=4, pady=2
        )
        ttk.Button(cal, text="Калібрувати моє HP", command=lambda: self._calibrate("own_hp_region", "Моє HP")).pack(
            side="left", padx=4, pady=2
        )

        aims = tk.Frame(self)
        aims.grid(row=9, column=0, columnspan=2, sticky="ew")
        ttk.Button(aims, text="Наведення F1", command=lambda: self._pick_point("attack_aim", "F1 атака")).pack(
            side="left", padx=4, pady=2
        )
        ttk.Button(aims, text="Наведення F2", command=lambda: self._pick_point("next_aim", "F2 наступна")).pack(
            side="left", padx=4, pady=2
        )
        ttk.Button(aims, text="Наведення F3", command=lambda: self._pick_point("heal_aim", "F3 хіл")).pack(
            side="left", padx=4, pady=2
        )

        ttk.Button(self, text="Перевірити калібрування", command=self._open_preview).grid(
            row=10, column=0, columnspan=2, padx=6, pady=2, sticky="ew"
        )

        self.logbox = scrolledtext.ScrolledText(self, height=8, width=42, state="disabled", wrap="word")
        self.logbox.grid(row=11, column=0, columnspan=2, padx=6, pady=6, sticky="nsew")

        self._bind_f12()
        self.after(50, self._pump)
        self._log(
            "F1/F2/F3. Перед кліком асистент тисне Space (замість макросу Ctrl — перевір). F12 — стоп."
        )

    def _read_fields(self) -> None:
        for key, *_ in self.FIELDS:
            try:
                self.cfg[key] = int(self.vars[key].get().strip())
            except ValueError:
                pass

    def _calibrate(self, field: str, title: str) -> None:
        def saved(region):
            self.cfg[field] = region
            save_config(self.cfg)
            self._log(f"{title}: {region['width']}×{region['height']} @ ({region['left']}, {region['top']})")

        Calibrator(self, title, self.cfg.get(field), saved)

    def _pick_point(self, field: str, title: str) -> None:
        def saved(point):
            self.cfg[field] = point
            save_config(self.cfg)
            self._log(f"{title}: наведення @ ({point['x']}, {point['y']})")

        PointPicker(self, title, saved)

    def _open_preview(self) -> None:
        win = getattr(self, "_preview", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        self._preview = CalibPreview(self, self.cfg)

    def _start(self) -> None:
        if self.bot and self.bot.running:
            return
        self._read_fields()
        save_config(self.cfg)
        self.bot = AssistBot(self.cfg, self._log, self._hp, lambda r: self.q.put(("stop", r)))
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.bot.start()

    def _request_stop(self, reason: str) -> None:
        if self.bot:
            self.bot.stop(reason)
        else:
            self.q.put(("stop", reason))

    def _apply_stopped(self) -> None:
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _hp(self, target: Optional[int], own: Optional[int]) -> None:
        self.q.put(("hp", (target, own)))

    def _log(self, msg: str) -> None:
        self.q.put(("log", msg))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.logbox.config(state="normal")
                    self.logbox.insert("end", payload + "\n")
                    lines = int(self.logbox.index("end-1c").split(".")[0])
                    if lines > 200:
                        self.logbox.delete("1.0", f"{lines - 200}.0")
                    self.logbox.see("end")
                    self.logbox.config(state="disabled")
                elif kind == "hp":
                    t, o = payload
                    self.lbl_target.config(text=f"HP цілі: {t}%" if t is not None else "HP цілі: —%")
                    self.lbl_own.config(text=f"Моє HP: {o}%" if o is not None else "Моє HP: —%")
                elif kind == "stop":
                    self._apply_stopped()
        except queue.Empty:
            pass
        self.after(50, self._pump)

    def _bind_f12(self) -> None:
        try:
            import keyboard

            keyboard.add_hotkey("f12", lambda: self._request_stop("Зупинено F12."))
            self._kb = keyboard
        except Exception as exc:
            self.after(100, lambda: self._log(f"F12 не підключено ({exc})."))

    def _close(self) -> None:
        self._request_stop("Вікно закрито.")
        prev = getattr(self, "_preview", None)
        if prev is not None and prev.winfo_exists():
            prev._close()
        if self._kb is not None:
            try:
                self._kb.unhook_all()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    set_dpi_awareness()
    App().mainloop()


if __name__ == "__main__":
    main()
