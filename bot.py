"""Lineage 2 assist: HP bars -> click F1/F2; low own HP -> F3. Ctrl macro unsticks input."""

from __future__ import annotations

import json
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

DEFAULTS = {
    "pause_min_ms": 400,
    "pause_max_ms": 700,
    "stuck_seconds": 8,
    "max_stuck": 3,
    "own_hp_stop": 30,  # якщо моє HP < цього % — клік F3 (0 = вимкнено)
    "target_region": None,
    "own_hp_region": None,
    "attack_aim": None,  # {"x": int, "y": int} — F1 slot
    "next_aim": None,  # {"x": int, "y": int} — F2 slot
    "heal_aim": None,  # {"x": int, "y": int} — F3 heal/skill
    "click_settle_ms": 60,  # пауза після SetCursorPos перед кліком (час для Ctrl-макросу)
    "switch_settle_ms": 150,  # довша пауза при F1↔F2 (після руху кліки часто «мертві»)
    "switch_extra_clicks": 0,  # додаткові кліки без повторного SetCursorPos після зміни слота
    "unstick_key": True,  # перед кліком натиснути клавішу (замість макросу Ctrl на миші)
    "unstick_vk": 0x20,  # VK: Space=0x20, Control=0x11
    "red_min": 120,
    "red_ratio": 1.8,
}


def load_config() -> dict:
    data = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                if "attack_aim" not in saved and saved.get("attack_click"):
                    saved["attack_aim"] = saved["attack_click"]
                if "next_aim" not in saved and saved.get("next_click"):
                    saved["next_aim"] = saved["next_click"]
                for k in DEFAULTS:
                    if k in saved:
                        data[k] = saved[k]
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
) -> list:
    if width <= 0 or height <= 0 or not bgra:
        return []
    mask = [False] * width
    stride = width * 4
    for y in range(height):
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
) -> int:
    mask = red_column_mask(bgra, width, height, red_min, red_ratio)
    rightmost = -1
    for x, flag in enumerate(mask):
        if flag:
            rightmost = x
    if rightmost < 0:
        return 0
    return int(round((rightmost + 1) / len(mask) * 100))


def bgra_to_ppm(bgra: bytes, width: int, height: int) -> bytes:
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
    width = len(mask)
    if width <= 0 or strip_h <= 0:
        return b"P6\n1 1\n255\n\x00\x00\x00"
    row = bytearray()
    for flag in mask:
        row.extend((220, 30, 30) if flag else (160, 160, 160))
    return f"P6\n{width} {strip_h}\n255\n".encode("ascii") + (bytes(row) * strip_h)


def preview_ppms(bgra: bytes, width: int, height: int, red_min: float = 120, red_ratio: float = 1.8):
    mask = red_column_mask(bgra, width, height, red_min, red_ratio)
    return bgra_to_ppm(bgra, width, height), mask_strip_ppm(mask), hp_percent(bgra, width, height, red_min, red_ratio)


def _tap_vk(vk: int) -> None:
    """Short key tap (may unstick soft mouse after SetCursorPos — test vs mouse Ctrl macro)."""
    import ctypes

    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.015)
    user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    time.sleep(0.01)


def _left_click(unstick_vk: Optional[int] = None) -> None:
    import ctypes

    if unstick_vk:
        _tap_vk(int(unstick_vk))
    user32 = ctypes.windll.user32
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP


def click_at(
    point: Optional[dict],
    settle_ms: int = 60,
    move: bool = True,
    times: int = 1,
    unstick_vk: Optional[int] = None,
) -> bool:
    """Optional SetCursorPos + key tap + left-click(s)."""
    if not point or "x" not in point or "y" not in point:
        return False
    import ctypes

    if move:
        ctypes.windll.user32.SetCursorPos(int(point["x"]), int(point["y"]))
        time.sleep(max(0, settle_ms) / 1000.0)
    for i in range(max(1, times)):
        if i:
            time.sleep(0.05)
        _left_click(unstick_vk=unstick_vk)
    return True


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
        self._click_error = False
        self._last_log = 0.0
        self._last_slot: Optional[str] = None

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

    def _click(self, point: Optional[dict], label: str) -> None:
        """Click slot. On F1↔F2: move once, longer settle, extra clicks; same slot: click only."""
        try:
            if not point or "x" not in point or "y" not in point:
                if not self._click_error:
                    self._click_error = True
                    self.on_log(f"Немає точки кліку «{label}».")
                return
            unstick_vk = None
            if self.cfg.get("unstick_key", True):
                unstick_vk = int(self.cfg.get("unstick_vk", 0x20))
            switched = self._last_slot != label
            if switched:
                settle = int(self.cfg.get("switch_settle_ms", 150))
                times = 1 + max(0, int(self.cfg.get("switch_extra_clicks", 2)))
                ok = click_at(point, settle_ms=settle, move=True, times=times, unstick_vk=unstick_vk)
                if ok:
                    self._last_slot = label
                    self.on_log(f"клік: {label} (перемикання ×{times})")
            else:
                settle = int(self.cfg.get("click_settle_ms", 60))
                # Already on slot — do not SetCursorPos again (re-move re-sticks clicks).
                click_at(point, settle_ms=settle, move=False, times=1, unstick_vk=unstick_vk)
        except Exception as exc:
            if not self._click_error:
                self._click_error = True
                self.on_log(f"Помилка кліку ({label}): {exc}")

    def _grab_hp(self, region: Optional[dict], sct) -> Optional[int]:
        if not region:
            return None
        w, h = int(region["width"]), int(region["height"])
        if w <= 0 or h <= 0:
            return None
        box = {k: int(region[k]) for k in ("left", "top", "width", "height")}
        last_exc: Optional[Exception] = None
        for _ in range(3):
            try:
                shot = sct.grab(box)
                return hp_percent(
                    shot.bgra if hasattr(shot, "bgra") else bytes(shot.raw),
                    shot.width,
                    shot.height,
                    self.cfg.get("red_min", 120),
                    self.cfg.get("red_ratio", 1.8),
                )
            except Exception as exc:
                last_exc = exc
                time.sleep(0.05)
        raise last_exc or RuntimeError("grab failed")

    def _loop(self) -> None:
        try:
            import mss
        except ImportError:
            self.stop("Не встановлено mss. pip install -r requirements.txt")
            return

        target_reg = self.cfg.get("target_region")
        if not target_reg:
            self.stop("Відкалібруйте HP цілі.")
            return
        attack_aim = self.cfg.get("attack_aim") or self.cfg.get("attack_click")
        next_aim = self.cfg.get("next_aim") or self.cfg.get("next_click")
        heal_aim = self.cfg.get("heal_aim")
        if not attack_aim or not next_aim:
            self.stop("Відкалібруйте наведення F1 і F2.")
            return

        stuck_sec = float(self.cfg.get("stuck_seconds", 8))
        max_stuck = int(self.cfg.get("max_stuck", 3))
        own_heal = int(self.cfg.get("own_hp_stop", 30))
        pmin = int(self.cfg.get("pause_min_ms", 400))
        pmax = int(self.cfg.get("pause_max_ms", 700))
        if pmax < pmin:
            pmin, pmax = pmax, pmin
        if own_heal > 0 and not heal_aim:
            self.stop("Поріг HP > 0: відкалібруйте наведення F3.")
            return

        last_hp: Optional[int] = None
        last_change = time.monotonic()
        stuck_count = 0
        heal_used = False
        self._last_slot = None
        unstick = "перед кліком Space" if self.cfg.get("unstick_key", True) else "без Space"
        if own_heal > 0:
            self.on_log(
                f"Бот: F1/F2 / F3 якщо HP < {own_heal}%. {unstick}. "
                "Макрос Ctrl на миші можна вимкнути для тесту. F12 — стоп."
            )
        else:
            self.on_log(
                f"Бот: F1/F2 (F3 вимк — поріг 0). {unstick}. F12 — стоп."
            )
        if self._stop.wait(1.5):
            return

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

                # F3 один раз, коли HP падає нижче порогу; після хілу знову F1/F2.
                if own_heal > 0 and own_hp is not None:
                    if own_hp >= own_heal:
                        heal_used = False
                    elif not heal_used:
                        self._click(heal_aim, "F3")
                        heal_used = True
                        self.on_log(f"Моє HP {own_hp}% < {own_heal}% — F3")
                        if self._stop.wait(random.uniform(pmin, pmax) / 1000.0):
                            return
                        continue

                now = time.monotonic()
                if target_hp <= 0:
                    # F2 лише один раз за епізод «немає цілі», не кожен тік циклу.
                    if self._last_slot != "F2":
                        self._click(next_aim, "F2")
                    last_hp = None
                    last_change = now
                elif last_hp is not None and target_hp == last_hp and (now - last_change) >= stuck_sec:
                    # Примусово один F2 на застрягання (навіть якщо вже були на F2 раніше).
                    self._last_slot = None
                    self._click(next_aim, "F2")
                    stuck_count += 1
                    self.on_log(f"HP не змінюється {stuck_sec:.0f} с — F2 ({stuck_count}/{max_stuck})")
                    last_hp = None
                    last_change = now
                    if stuck_count >= max_stuck:
                        self.stop(f"Застрягання {stuck_count} разів. Стоп.")
                        return
                else:
                    if last_hp is not None and target_hp != last_hp:
                        stuck_count = 0
                    if last_hp != target_hp:
                        last_hp = target_hp
                        last_change = now
                    self._click(attack_aim, "F1")

                if self._stop.wait(random.uniform(pmin, pmax) / 1000.0):
                    return
