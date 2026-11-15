"""Lineage 2 assist: screen HP bars -> attack / next-target keys."""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULTS = {
    "attack_key": "F1",
    "next_target_key": "F2",
    "pause_min_ms": 300,
    "pause_max_ms": 700,
    "stuck_seconds": 8,
    "max_stuck": 3,
    "own_hp_stop": 30,
    "target_region": None,
    "own_hp_region": None,
    "red_min": 120,
    "red_ratio": 1.8,
}

# Lazy so the module imports on non-Windows.
pydirectinput = None


def load_config() -> dict:
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                data.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
    return data


def save_config(cfg: dict) -> None:
    out = {k: cfg.get(k, v) for k, v in DEFAULTS.items()}
    CONFIG_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_red(b: int, g: int, r: int, red_min: float, red_ratio: float) -> bool:
    return r > red_min and r > g * red_ratio and r > b * red_ratio


def red_column_mask(
    bgra: bytes,
    width: int,
    height: int,
    red_min: float = 120,
    red_ratio: float = 1.8,
    rows: int = 3,
) -> list:
    """True for columns with a red pixel in the mid scan rows (same rule as HP%)."""
    if width <= 0 or height <= 0 or not bgra:
        return []
    mid = height // 2
    half = max(0, rows // 2)
    y0 = max(0, mid - half)
    y1 = min(height, mid + half + 1)
    mask = [False] * width
    stride = width * 4
    for y in range(y0, y1):
        row = y * stride
        for x in range(width):
            if mask[x]:
                continue
            i = row + x * 4
            if i + 2 >= len(bgra):
                return mask
            if is_red(bgra[i], bgra[i + 1], bgra[i + 2], red_min, red_ratio):
                mask[x] = True
    return mask


def hp_percent(
    bgra: bytes,
    width: int,
    height: int,
    red_min: float = 120,
    red_ratio: float = 1.8,
    rows: int = 3,
) -> int:
    """HP% from mss BGRA bytes: rightmost red column / width, scanning mid rows."""
    mask = red_column_mask(bgra, width, height, red_min, red_ratio, rows)
    rightmost = -1
    for x, flag in enumerate(mask):
        if flag:
            rightmost = x
    if rightmost < 0:
        return 0
    return int(round((rightmost + 1) / len(mask) * 100))


def bgra_to_ppm(bgra: bytes, width: int, height: int) -> bytes:
    """Binary PPM (P6) from mss BGRA, for tk.PhotoImage without PIL."""
    if width <= 0 or height <= 0:
        return b"P6\n1 1\n255\n\x00\x00\x00"
    rgb = bytearray(width * height * 3)
    for i in range(width * height):
        s = i * 4
        if s + 2 >= len(bgra):
            break
        d = i * 3
        rgb[d] = bgra[s + 2]
        rgb[d + 1] = bgra[s + 1]
        rgb[d + 2] = bgra[s]
    return f"P6\n{width} {height}\n255\n".encode("ascii") + bytes(rgb)


def mask_strip_ppm(mask: list, strip_h: int = 8) -> bytes:
    """Thin PPM strip: red-detected columns in red, others in gray."""
    width = len(mask)
    if width <= 0 or strip_h <= 0:
        return b"P6\n1 1\n255\n\x00\x00\x00"
    row = bytearray()
    for flag in mask:
        row.extend((220, 30, 30) if flag else (160, 160, 160))
    return f"P6\n{width} {strip_h}\n255\n".encode("ascii") + (bytes(row) * strip_h)


def preview_ppms(
    bgra: bytes,
    width: int,
    height: int,
    red_min: float = 120,
    red_ratio: float = 1.8,
    strip_h: int = 8,
):
    """(capture PPM, column-mask PPM, HP%) for the calibration preview."""
    mask = red_column_mask(bgra, width, height, red_min, red_ratio)
    return bgra_to_ppm(bgra, width, height), mask_strip_ppm(mask, strip_h), hp_percent(
        bgra, width, height, red_min, red_ratio
    )


def _ensure_pydirectinput():
    global pydirectinput
    if pydirectinput is None:
        import pydirectinput as _p

        pydirectinput = _p
        pydirectinput.PAUSE = 0.05
    return pydirectinput


class AssistBot:
    def __init__(
        self,
        cfg: dict,
        on_log: Callable[[str], None],
        on_hp: Callable[[Optional[int], Optional[int]], None],
        on_stop: Callable[[str], None],
    ):
        self.cfg = cfg
        self.on_log = on_log
        self.on_hp = on_hp
        self.on_stop = on_stop
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self, reason: str = "Зупинено") -> None:
        if self._stop.is_set() and not self.running:
            return
        already = self._stop.is_set()
        self._stop.set()
        if not already:
            self.on_log(reason)
            self.on_stop(reason)

    def _press(self, key: str) -> None:
        pdi = _ensure_pydirectinput()
        pdi.press(key.lower())

    def _grab_hp(self, region: Optional[dict], sct) -> Optional[int]:
        if not region:
            return None
        left, top = int(region["left"]), int(region["top"])
        w, h = int(region["width"]), int(region["height"])
        if w <= 0 or h <= 0:
            return None
        shot = sct.grab({"left": left, "top": top, "width": w, "height": h})
        return hp_percent(
            shot.bgra if hasattr(shot, "bgra") else bytes(shot.raw),
            shot.width,
            shot.height,
            self.cfg.get("red_min", 120),
            self.cfg.get("red_ratio", 1.8),
        )

    def _loop(self) -> None:
        try:
            import mss
        except ImportError:
            self.stop("Не встановлено mss. pip install -r requirements.txt")
            return
        try:
            _ensure_pydirectinput()
        except ImportError:
            self.stop("Не встановлено pydirectinput. pip install -r requirements.txt")
            return

        target_reg = self.cfg.get("target_region")
        if not target_reg:
            self.stop("Спочатку відкалібруйте смугу HP цілі.")
            return

        stuck_sec = float(self.cfg.get("stuck_seconds", 8))
        max_stuck = int(self.cfg.get("max_stuck", 3))
        own_stop = int(self.cfg.get("own_hp_stop", 30))
        attack = str(self.cfg.get("attack_key", "F1"))
        nxt = str(self.cfg.get("next_target_key", "F2"))
        pmin = int(self.cfg.get("pause_min_ms", 300))
        pmax = int(self.cfg.get("pause_max_ms", 700))
        if pmax < pmin:
            pmin, pmax = pmax, pmin

        last_hp: Optional[int] = None
        last_change = time.monotonic()
        stuck_count = 0
        self.on_log("Бот запущено.")

        with mss.mss() as sct:
            while not self._stop.is_set():
                try:
                    target_hp = self._grab_hp(target_reg, sct)
                    own_hp = self._grab_hp(self.cfg.get("own_hp_region"), sct)
                except Exception as exc:
                    self.stop(f"Помилка захоплення екрана: {exc}")
                    return
                if target_hp is None:
                    self.stop("Немає області HP цілі.")
                    return
                self.on_hp(target_hp, own_hp)

                if own_hp is not None and own_hp < own_stop:
                    self.stop(f"Моє HP {own_hp}% нижче порогу {own_stop}%.")
                    return

                now = time.monotonic()
                if target_hp <= 0:
                    self._press(nxt)
                    last_hp = None
                    last_change = now
                elif last_hp is not None and target_hp == last_hp and (now - last_change) >= stuck_sec:
                    self._press(nxt)
                    stuck_count += 1
                    self.on_log(
                        f"HP цілі не змінюється {stuck_sec:.0f} с — наступна ціль "
                        f"({stuck_count}/{max_stuck})."
                    )
                    last_hp = None
                    last_change = now
                    if stuck_count >= max_stuck:
                        self.stop(f"Застрягання {stuck_count} разів поспіль. Стоп.")
                        return
                else:
                    if last_hp is not None and target_hp != last_hp:
                        stuck_count = 0
                    if last_hp != target_hp:
                        last_hp = target_hp
                        last_change = now
                    self._press(attack)

                wait = random.uniform(pmin, pmax) / 1000.0
                if self._stop.wait(wait):
                    return
