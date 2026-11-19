"""A Linux desktop: a virtual screen (Xvfb) running XFCE, controlled with xdotool and scrot."""

from pathlib import Path

import modal

from .base import VIEWER_PORT, Computer, action

ASSETS = Path(__file__).parent / "assets"
BUTTONS = {"left": 1, "middle": 2, "right": 3}
WHEEL_NOTCH = 120  # pixels that one turn of the mouse wheel scrolls in Chromium

PACKAGES = [
    # the screen, the desktop, and the live viewer
    "xvfb", "xfce4", "dbus-x11", "x11vnc", "novnc", "websockify",
    # the agent's hands and eyes
    "xdotool", "scrot",
    # something to use
    "chromium", "mousepad", "xfce4-terminal", "fonts-dejavu-core", "fonts-liberation",
]  # fmt: skip

desktop_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install(*PACKAGES)
    .run_commands("useradd --create-home --shell /bin/bash agent")
    .add_local_file(ASSETS / "start-desktop.sh", "/opt/start-desktop.sh", copy=True)
)


class Desktop(Computer):
    kind = "Linux desktop"
    image = desktop_image
    command = ("bash", "/opt/start-desktop.sh")
    options = {"cpu": 2, "memory": 4096, "readiness_probe": modal.Probe.with_tcp(VIEWER_PORT)}
    exec_env = {"DISPLAY": ":0"}
    size = (1280, 800)  # start-desktop.sh creates the screen at this size

    def screenshot(self) -> bytes:
        return self.run("scrot", "--pointer", "-", binary=True)

    # xdotool's `mousemove --sync` stalls for 15 seconds when the pointer is already at the target,
    # so these commands move without it. Events in one xdotool call are still delivered in order.

    @action(view="pixels")
    def click(self, x: int, y: int, button: str = "left", count: int = 1):
        """Click at a point. button is left, middle or right; count=2 double-clicks."""
        if button not in BUTTONS:
            raise ValueError(f"button must be one of {', '.join(BUTTONS)}, not {button!r}")
        self.run("xdotool", "mousemove", x, y, "click", "--repeat", count, BUTTONS[button])

    @action(view="pixels")
    def move(self, x: int, y: int):
        """Move the mouse to a point without clicking."""
        self.run("xdotool", "mousemove", x, y)

    @action(view="pixels")
    def drag(self, x1: int, y1: int, x2: int, y2: int):
        """Press the left button at one point, move to another, and release."""
        self.run("xdotool", "mousemove", x1, y1, "mousedown", 1, "mousemove", x2, y2, "mouseup", 1)

    @action(view="pixels")
    def scroll(self, x: int, y: int, dy: int):
        """Scroll the content under a point by about dy pixels. Positive scrolls down, negative up."""
        notches = min(max(round(abs(dy) / WHEEL_NOTCH), 1), 50)
        self.run("xdotool", "mousemove", x, y, "click", "--repeat", notches, "--delay", 10, 5 if dy > 0 else 4)

    @action
    def type(self, text: str):
        """Type text into whatever has keyboard focus."""
        self.run("xdotool", "type", "--clearmodifiers", "--delay", 12, "--", text)

    @action
    def key(self, name: str):
        """Press a key or shortcut by its xdotool name: Return, Tab, Escape, BackSpace, ctrl+s, alt+F4."""
        self.run("xdotool", "key", "--clearmodifiers", "--", name)

    def launch(self, command: str) -> None:
        """Start a program on the desktop without waiting for it.

        `command` is a shell command line, run as the unprivileged `agent` user.
        """
        self.run("runuser", "-u", "agent", "--", "bash", "-c", f"nohup {command} >/tmp/launch.log 2>&1 &")
