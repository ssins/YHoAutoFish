import ctypes
import time


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class UserActivityMonitor:
    """Detects physical user input while the bot is controlling the game."""

    VK_BY_KEY = {
        "a": 0x41,
        "d": 0x44,
        "f": 0x46,
        "esc": 0x1B,
        "escape": 0x1B,
        "mouse_left": 0x01,
        "left_mouse": 0x01,
    }

    KEY_NAMES = {
        0x01: "left mouse",
        0x02: "right mouse",
        0x04: "middle mouse",
        0x05: "mouse x1",
        0x06: "mouse x2",
        0x08: "backspace",
        0x09: "tab",
        0x0D: "enter",
        0x10: "shift",
        0x11: "ctrl",
        0x12: "alt",
        0x1B: "esc",
        0x20: "space",
        0x21: "page up",
        0x22: "page down",
        0x23: "end",
        0x24: "home",
        0x25: "left",
        0x26: "up",
        0x27: "right",
        0x28: "down",
        0x2D: "insert",
        0x2E: "delete",
        0x5B: "left win",
        0x5C: "right win",
        0x60: "num 0",
        0x61: "num 1",
        0x62: "num 2",
        0x63: "num 3",
        0x64: "num 4",
        0x65: "num 5",
        0x66: "num 6",
        0x67: "num 7",
        0x68: "num 8",
        0x69: "num 9",
    }

    def __init__(
        self,
        enabled=True,
        poll_interval=0.05,
        start_grace=1.20,
        program_input_grace=0.45,
        mouse_move_threshold=12,
    ):
        self.enabled = bool(enabled)
        self.poll_interval = max(0.02, float(poll_interval))
        self.start_grace = max(0.0, float(start_grace))
        self.program_input_grace = max(0.05, float(program_input_grace))
        self.mouse_move_threshold = max(4, int(mouse_move_threshold))
        try:
            self._user32 = ctypes.windll.user32
            # Do not bind GetCursorPos to this module's POINT type. pydirectinput
            # calls the same global user32 function with its own POINT class.
            self._user32.GetCursorPos.argtypes = None
        except Exception:
            self._user32 = None
            self.enabled = False
        self._last_check_time = 0.0
        self._armed_after = 0.0
        self._ignored_until = 0.0
        self._baseline_down = set()
        self._keyboard_vks = self._build_keyboard_vks()
        self._mouse_vks = (0x01, 0x02, 0x04, 0x05, 0x06)
        self.reset()

    def update_config(self, enabled=None, mouse_move_threshold=None, start_grace=None, excluded_rects=None):
        if enabled is not None:
            self.enabled = bool(enabled)
        if mouse_move_threshold is not None:
            self.mouse_move_threshold = max(4, int(mouse_move_threshold))
        if start_grace is not None:
            self.start_grace = max(0.0, float(start_grace))

    def reset(self):
        now = time.time()
        self._last_check_time = 0.0
        self._armed_after = now + self.start_grace
        self._ignored_until = now + self.start_grace
        self._baseline_down = self._pressed_vks()

    def note_program_input(self, keys=(), duration=None):
        duration = self.program_input_grace if duration is None else max(0.05, float(duration))
        self._ignored_until = max(self._ignored_until, time.time() + duration)
        for key in keys or ():
            vk = self._vk_for_key(key)
            if vk is not None:
                self._baseline_down.add(vk)

    def check(self, owned_keys=(), game_rect=None, excluded_rects=()):
        if not self.enabled:
            return None

        now = time.time()
        if now - self._last_check_time < self.poll_interval:
            return None
        self._last_check_time = now

        pressed_keyboard = self._pressed_keyboard_vks()
        pressed_mouse = self._pressed_mouse_vks()
        pressed = pressed_keyboard | pressed_mouse
        owned_vks = self._owned_vks(owned_keys)
        self._baseline_down.intersection_update(pressed)

        if now < self._armed_after or now < self._ignored_until:
            self._baseline_down.update(pressed - owned_vks)
            return None

        user_keyboard = pressed_keyboard - self._baseline_down - owned_vks
        if user_keyboard:
            return self._format_key_reason(user_keyboard)

        cursor_pos = self._cursor_pos()
        if self._point_in_any_rect(cursor_pos, excluded_rects):
            if pressed_mouse:
                self._baseline_down.update(pressed_mouse)
            return None

        if self._point_in_rect(cursor_pos, game_rect):
            user_mouse = pressed_mouse - self._baseline_down
            if user_mouse:
                return self._format_mouse_reason(user_mouse)
        elif pressed_mouse:
            self._baseline_down.update(pressed_mouse)

        return None

    def _build_keyboard_vks(self):
        vks = set()
        vks.update(range(0x30, 0x3A))  # 0-9
        vks.update(range(0x41, 0x5B))  # A-Z
        vks.update(range(0x70, 0x7C))  # F1-F12
        vks.update(
            {
                0x08,
                0x09,
                0x0D,
                0x10,
                0x11,
                0x12,
                0x1B,
                0x20,
                0x21,
                0x22,
                0x23,
                0x24,
                0x25,
                0x26,
                0x27,
                0x28,
                0x2D,
                0x2E,
                0x5B,
                0x5C,
            }
        )
        vks.update(range(0x60, 0x6C))  # numpad and operators
        return tuple(sorted(vks))

    def _pressed_vks(self):
        return self._pressed_keyboard_vks() | self._pressed_mouse_vks()

    def _pressed_keyboard_vks(self):
        pressed = set()
        for vk in self._keyboard_vks:
            if self._is_down(vk):
                pressed.add(vk)
        return pressed

    def _pressed_mouse_vks(self):
        pressed = set()
        for vk in self._mouse_vks:
            if self._is_down(vk):
                pressed.add(vk)
        return pressed

    def _is_down(self, vk):
        try:
            if self._user32 is None:
                return False
            return bool(self._user32.GetAsyncKeyState(int(vk)) & 0x8000)
        except Exception:
            return False

    def _cursor_pos(self):
        point = POINT()
        try:
            if self._user32 is None:
                return None
            if self._user32.GetCursorPos(ctypes.byref(point)):
                return int(point.x), int(point.y)
        except Exception:
            return None
        return None

    def _vk_for_key(self, key):
        if key is None:
            return None
        key_text = str(key).lower()
        if key_text in self.VK_BY_KEY:
            return self.VK_BY_KEY[key_text]
        if len(key_text) == 1:
            return ord(key_text.upper())
        return None

    def _owned_vks(self, owned_keys):
        owned = set()
        for key in owned_keys or ():
            vk = self._vk_for_key(key)
            if vk is not None:
                owned.add(vk)
        return owned

    def _point_in_rect(self, point, rect):
        if point is None or rect is None:
            return False
        try:
            x, y = int(point[0]), int(point[1])
            left, top, width, height = rect
            return int(left) <= x < int(left + width) and int(top) <= y < int(top + height)
        except Exception:
            return False

    def _point_in_any_rect(self, point, rects):
        for rect in rects or ():
            if self._point_in_rect(point, rect):
                return True
        return False

    def _format_key_reason(self, vks):
        vk = min(vks)
        if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
            name = chr(vk)
        elif 0x70 <= vk <= 0x7B:
            name = f"F{vk - 0x6F}"
        else:
            name = self.KEY_NAMES.get(vk, f"VK 0x{vk:02X}")
        return f"检测到游戏内键盘输入: {name}"

    def _format_mouse_reason(self, vks):
        vk = min(vks)
        name = self.KEY_NAMES.get(vk, f"VK 0x{vk:02X}")
        return f"检测到游戏窗口内鼠标点击: {name}"
