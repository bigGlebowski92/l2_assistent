"""Try every common F1 injection method. Focus the game during the countdown."""

from __future__ import annotations

import time
import traceback
from pathlib import Path

OUT = Path(__file__).resolve().parent / "key_methods_result.txt"


def log(msg: str, lines: list[str]) -> None:
    print(msg, flush=True)
    lines.append(msg)


def wait(sec: float, lines: list[str], label: str) -> None:
    log(f"  ... пауза {sec:.1f}s ({label})", lines)
    time.sleep(sec)


def try_method(name: str, fn, lines: list[str]) -> None:
    log(f"\n=== {name} ===", lines)
    try:
        fn()
        log(f"OK  {name}: виклик без винятку", lines)
    except Exception:
        log(f"FAIL {name}:\n{traceback.format_exc()}", lines)


def main() -> None:
    lines: list[str] = []
    log("Тест F1 усіма методами. Переключіться в ГРУ зараз.", lines)
    for i in range(5, 0, -1):
        log(f"  старт через {i}...", lines)
        time.sleep(1)

    # 1) keyboard
    def m_keyboard():
        import keyboard

        keyboard.send("f1")
        time.sleep(0.15)
        keyboard.press("f1")
        time.sleep(0.08)
        keyboard.release("f1")

    try_method("keyboard.send/press", m_keyboard, lines)
    wait(1.2, lines, "дивіться, чи спрацювало F1 в грі")

    # 2) pydirectinput
    def m_pydi():
        import pydirectinput

        pydirectinput.FAILSAFE = False
        pydirectinput.PAUSE = 0.05
        pydirectinput.press("f1")
        time.sleep(0.1)
        pydirectinput.keyDown("f1")
        time.sleep(0.08)
        pydirectinput.keyUp("f1")

    try_method("pydirectinput.press/keyDown", m_pydi, lines)
    wait(1.2, lines, "дивіться гру")

    # 3) pyautogui
    def m_pag():
        import pyautogui

        pyautogui.FAILSAFE = False
        pyautogui.press("f1")

    try_method("pyautogui.press", m_pag, lines)
    wait(1.2, lines, "дивіться гру")

    # 4) pynput
    def m_pynput():
        from pynput.keyboard import Controller, Key

        kb = Controller()
        kb.press(Key.f1)
        time.sleep(0.08)
        kb.release(Key.f1)

    try_method("pynput Key.f1", m_pynput, lines)
    wait(1.2, lines, "дивіться гру")

    # 5) keybd_event (ctypes = same as win32api.keybd_event)
    def m_keybd():
        import ctypes

        VK_F1 = 0x70
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_F1, 0x3B, 0, 0)
        time.sleep(0.08)
        user32.keybd_event(VK_F1, 0x3B, 2, 0)

    try_method("keybd_event (ctypes)", m_keybd, lines)
    wait(1.2, lines, "дивіться гру")

    # 6) SendInput scancode
    def m_sendinput():
        import ctypes
        from ctypes import wintypes

        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            )

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = (
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            )

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = (
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            )

        class INPUT_UNION(ctypes.Union):
            _fields_ = (("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT))

        class INPUT(ctypes.Structure):
            _fields_ = (("type", wintypes.DWORD), ("u", INPUT_UNION))

        user32 = ctypes.windll.user32
        user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        user32.SendInput.restype = wintypes.UINT
        KEYEVENTF_SCANCODE = 0x0008
        KEYEVENTF_KEYUP = 0x0002
        scan = 0x3B  # F1

        def one(up: bool = False):
            inp = INPUT(type=1)
            flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0)
            inp.u.ki = KEYBDINPUT(0, scan, flags, 0, 0)
            n = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
            if n != 1:
                raise RuntimeError(f"SendInput returned {n}, sizeof={ctypes.sizeof(INPUT)}")

        one(False)
        time.sleep(0.08)
        one(True)

    try_method("SendInput scancode", m_sendinput, lines)
    wait(1.2, lines, "дивіться гру")

    # 7) PostMessage / SendMessage to game HWND
    def m_messages():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        found = []

        def _enum(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            cls = buf.value.lower()
            if "viewport" in cls or ("unreal" in cls and "window" in cls):
                found.append(hwnd)
            return True

        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        user32.EnumWindows(enum_proc(_enum), 0)
        if not found:
            raise RuntimeError("вікно гри (viewport/unreal) не знайдено")
        hwnd = found[0]
        VK_F1 = 0x70
        scan = user32.MapVirtualKeyW(VK_F1, 0) & 0xFF
        lp_down = 1 | (scan << 16)
        lp_up = 1 | (scan << 16) | (1 << 30) | (1 << 31)
        WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
        r1 = user32.PostMessageW(hwnd, WM_KEYDOWN, VK_F1, lp_down)
        time.sleep(0.08)
        r2 = user32.PostMessageW(hwnd, WM_KEYUP, VK_F1, lp_up)
        log(f"  PostMessage -> hwnd={hwnd} down={r1} up={r2}", lines)
        time.sleep(0.4)
        r3 = user32.SendMessageW(hwnd, WM_KEYDOWN, VK_F1, lp_down)
        time.sleep(0.08)
        r4 = user32.SendMessageW(hwnd, WM_KEYUP, VK_F1, lp_up)
        log(f"  SendMessage -> down={r3} up={r4}", lines)

    try_method("PostMessage/SendMessage WM_KEYDOWN", m_messages, lines)
    wait(1.2, lines, "дивіться гру")

    # 8) win32api if available
    def m_win32():
        import win32api
        import win32con

        win32api.keybd_event(win32con.VK_F1, 0x3B, 0, 0)
        time.sleep(0.08)
        win32api.keybd_event(win32con.VK_F1, 0x3B, win32con.KEYEVENTF_KEYUP, 0)

    try_method("win32api.keybd_event", m_win32, lines)
    wait(1.0, lines, "кінець")

    log("\nГотово. Напишіть, який номер/метод спрацював у грі (якщо хоч один).", lines)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    log(f"Лог збережено: {OUT}", lines)


if __name__ == "__main__":
    main()
