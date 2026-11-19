"""The Ubuntu machine of an OSWorld task as a Computer, so the same loop can drive it.

OSWorld runs each task in a full virtual machine and controls it through a small server inside the
guest that executes pyautogui calls. This class turns our actions into those calls.
"""

import json
import re

from computers import Computer, action

WHEEL_NOTCH = 120  # pixels that one turn of the mouse wheel scrolls, roughly


class OSWorldDesktop(Computer):
    kind = "Ubuntu desktop"
    size = (1920, 1080)
    settle = 2.0  # office apps and browsers in the guest take a moment to redraw

    def __init__(self, env):
        self.env = env  # an OSWorld DesktopEnv that has been reset to a task

    def python(self, code: str) -> None:
        """Run Python in the guest, where `pyautogui` is already imported."""
        result = self.env.controller.execute_python_command(code)
        if not result or result.get("returncode"):
            raise RuntimeError(f"the guest rejected {code!r}: {(result or {}).get('error', 'no reply')}"[:300])

    def screenshot(self) -> bytes:
        return self.env.controller.get_screenshot()

    @action(view="pixels")
    def click(self, x: int, y: int, button: str = "left", count: int = 1):
        """Click at a point. button is left, middle or right; count=2 double-clicks."""
        if button not in ("left", "middle", "right"):
            raise ValueError(f"button must be left, middle or right, not {button!r}")
        self.python(f"pyautogui.click({int(x)}, {int(y)}, clicks={int(count)}, interval=0.1, button='{button}')")

    @action(view="pixels")
    def move(self, x: int, y: int):
        """Move the mouse to a point without clicking."""
        self.python(f"pyautogui.moveTo({int(x)}, {int(y)})")

    @action(view="pixels")
    def drag(self, x1: int, y1: int, x2: int, y2: int):
        """Press the left button at one point, move to another, and release."""
        self.python(f"pyautogui.moveTo({int(x1)}, {int(y1)}); pyautogui.dragTo({int(x2)}, {int(y2)}, duration=0.5)")

    @action(view="pixels")
    def scroll(self, x: int, y: int, dy: int):
        """Scroll the content under a point by about dy pixels. Positive scrolls down, negative up."""
        notches = min(max(round(abs(dy) / WHEEL_NOTCH), 1), 50)
        self.python(f"pyautogui.moveTo({int(x)}, {int(y)}); pyautogui.scroll({-notches if dy > 0 else notches})")

    @action
    def type(self, text: str):
        """Type text into whatever has keyboard focus."""
        self.python(f"pyautogui.write({json.dumps(text)}, interval=0.02)")  # a JSON string is a Python string

    @action
    def key(self, name: str):
        """Press a key or shortcut by its pyautogui name: enter, tab, esc, backspace, ctrl+s, alt+f4."""
        keys = name.lower().split("+")
        if not all(re.fullmatch(r"\w+|[-=\[\];,./`]", key) for key in keys):
            raise ValueError(f"{name!r} is not a key name")
        self.python(f"pyautogui.hotkey({', '.join(repr(key) for key in keys)})")
