"""An Android phone: Google's emulator in a VM Sandbox, controlled with adb.

The emulator is itself a virtual machine, so this needs the VM runtime with nested
virtualization, which Modal offers to Enterprise workspaces.
"""

import re
import shlex
import time
import xml.etree.ElementTree as ET

import modal

from .base import Computer, action
from .desktop import ASSETS

SDK = "/opt/android"
TOOLS = "https://dl.google.com/android/repository/commandlinetools-linux-15859902_latest.zip"
SYSTEM_IMAGE = "system-images;android-33;google_apis;x86_64"
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
LAUNCHABLE = ("-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER")  # apps with an icon

PACKAGES = [
    "openjdk-17-jre-headless", "wget", "unzip", "procps",
    # shared libraries the emulator loads
    "libnss3", "libxcursor1", "libpulse0", "libxkbcommon0", "libxkbcommon-x11-0", "libgbm1", "libdrm2",
    "libasound2t64", "libdbus-1-3", "libx11-6", "libx11-xcb1", "libxcb1", "libxcb-cursor0", "libxcomposite1",
    "libxdamage1", "libxi6", "libxtst6", "libxrender1", "libxrandr2", "libxfixes3", "libsm6", "libice6",
    "libfontconfig1", "libgl1", "libegl1", "libxkbfile1", "libxcb-xinerama0", "libxcb-icccm4", "libxcb-image0",
    "libxcb-keysyms1", "libxcb-randr0", "libxcb-render-util0", "libxcb-shape0", "libxcb-xkb1",
    # the virtual screen, the live viewer, and xdotool to dismiss the emulator's startup dialog
    "xvfb", "x11vnc", "novnc", "websockify", "xdotool",
]  # fmt: skip

android_image = (
    modal.Image.from_registry("ubuntu:24.04", add_python="3.12")
    .env(
        {
            "DEBIAN_FRONTEND": "noninteractive",
            "ANDROID_HOME": SDK,
            "ANDROID_SDK_ROOT": SDK,
            "ANDROID_AVD_HOME": "/root/.android/avd",
            "PATH": f"{SDK}/cmdline-tools/latest/bin:{SDK}/emulator:{SDK}/platform-tools:"
            "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        }
    )
    .apt_install(*PACKAGES)
    .run_commands(
        f"mkdir -p {SDK}/cmdline-tools && cd /tmp && wget -q {TOOLS} -O tools.zip && unzip -q tools.zip "
        f"&& mv cmdline-tools {SDK}/cmdline-tools/latest",
        "yes | sdkmanager --licenses >/dev/null",
        f'sdkmanager platform-tools emulator "{SYSTEM_IMAGE}" >/dev/null',
        f'echo no | avdmanager create avd --name phone --device pixel_6 --package "{SYSTEM_IMAGE}"',
        # Let a person watching through the live view type with their own keyboard.
        "sed -i '/^hw.keyboard/d' $ANDROID_AVD_HOME/phone.avd/config.ini "
        "&& echo 'hw.keyboard = yes' >> $ANDROID_AVD_HOME/phone.avd/config.ini",
    )
    .add_local_file(ASSETS / "boot-android.sh", "/opt/boot-android.sh", copy=True)
)


class Android(Computer):
    kind = "Android phone"
    image = android_image
    command = ("bash", "/opt/boot-android.sh")
    options = {"runtime": "vm", "experimental_options": {"enable_nested_virt": True}, "cpu": 4, "memory": 8192}
    size = (1080, 2400)
    settle = 0.7  # a tapped switch can take half a second to show its new state
    _seen: tuple = ()  # the centre point of each element in the latest description

    def wait_ready(self) -> None:
        """Wait for Android to boot, which takes about a minute."""
        deadline = time.monotonic() + 360
        while True:
            if self.sandbox.poll() is not None:
                raise RuntimeError(f"Android failed to boot: {self.sandbox.stdout.read()[-2000:]}")
            if self.run("bash", "-c", "test -f /run/android-ready && echo ready || true").strip() == "ready":
                return
            if time.monotonic() > deadline:
                raise TimeoutError("Android did not boot within 6 minutes")
            time.sleep(2)

    def adb(self, *argv, binary: bool = False):
        """Run an adb command against the phone."""
        return self.run("adb", *argv, binary=binary)

    def screenshot(self) -> bytes:
        return self.adb("exec-out", "screencap", "-p", binary=True)

    # `adb shell` passes its arguments to a shell on the phone, so everything a model supplies
    # is converted to an int, checked against a pattern, or quoted before it is sent.

    @action(view="pixels")
    def click(self, x: int, y: int, hold: bool = False):
        """Tap a point on the screen. hold=True is a long press, which selects an item or opens its menu."""
        if hold:
            self.adb("shell", "input", "swipe", int(x), int(y), int(x), int(y), 1000)  # a swipe that stays put
        else:
            self.adb("shell", "input", "tap", int(x), int(y))

    @action(view="pixels")
    def drag(self, x1: int, y1: int, x2: int, y2: int):
        """Swipe a finger from one point to another."""
        self.adb("shell", "input", "swipe", int(x1), int(y1), int(x2), int(y2), 300)

    @action
    def swipe(self, direction: str):
        """Swipe across the middle of the screen: up, down, left or right. Swiping up moves down a list."""
        width, height = self.size
        paths = {
            "up": (width // 2, height * 7 // 10, width // 2, height * 3 // 10),
            "down": (width // 2, height * 3 // 10, width // 2, height * 7 // 10),
            "left": (width * 8 // 10, height // 2, width * 2 // 10, height // 2),
            "right": (width * 2 // 10, height // 2, width * 8 // 10, height // 2),
        }
        if direction not in paths:
            raise ValueError(f"direction must be up, down, left or right, not {direction!r}")
        self.drag(*paths[direction])

    @action
    def type(self, text: str, clear: bool = False):
        """Type text into the focused field. clear=True empties the field first. ASCII only; %s is typed as a space."""
        if clear:
            self.adb("shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A")  # select all
            self.key("DEL")
        if text:
            self.adb("shell", "input", "text", shlex.quote(text.replace(" ", "%s")))

    @action
    def key(self, name: str):
        """Press a key by its Android name: BACK, HOME, ENTER, DEL, APP_SWITCH."""
        if not re.fullmatch(r"\w+", name):
            raise ValueError(f"{name!r} is not a key name")
        self.adb("shell", "input", "keyevent", f"KEYCODE_{name.upper()}")

    @action
    def open_app(self, name: str):
        """Open an app by its name or package: Settings, Clock, com.android.chrome."""
        apps = self.adb("shell", "cmd", "package", "query-activities", "--brief", "--components", *LAUNCHABLE).split()
        words = re.findall(r"\w+", name.lower())
        matches = [app for app in apps if words and all(word in app.lower() for word in words)]
        if len({app.split("/")[0] for app in matches}) != 1:
            choices = sorted({app.split("/")[0] for app in matches or apps})
            raise ValueError(f"{name!r} does not name one app. Choose from: {', '.join(choices)}")
        self.adb("shell", "am", "start", "-n", shlex.quote(matches[0]))

    def _hierarchy(self) -> ET.Element | None:
        """The UI tree, or None while the screen keeps moving.

        uiautomator waits ten seconds for the screen to hold still and returns nothing if it never does,
        as with a running stopwatch. One retry covers a screen that was only part-way through a change.
        """
        for _ in range(2):
            dump = self.adb("exec-out", "uiautomator", "dump", "/dev/tty")
            start, end = dump.find("<hierarchy"), dump.rfind("</hierarchy>")
            if start >= 0 and end >= 0:
                return ET.fromstring(dump[start : end + len("</hierarchy>")])
        return None

    def describe(self) -> str:
        """The screen as text: a numbered list of everything with a label."""
        tree = self._hierarchy()
        if tree is None:
            self._seen = ()
            return "(Something on the screen keeps moving, so it cannot be read as text.)"
        lines, points = [], []
        for node in tree.iter("node"):
            label = node.get("text") or node.get("content-desc")
            has_labelled_child = any(child.get("text") or child.get("content-desc") for child in node.iter("node"))
            if not label and node.get("clickable") == "true" and not has_labelled_child:
                label = node.get("resource-id", "").rsplit("/", 1)[-1]  # an unlabelled icon button
            bounds = BOUNDS.fullmatch(node.get("bounds", ""))
            if not (label and bounds):
                continue
            left, top, right, bottom = map(int, bounds.groups())
            points.append(((left + right) // 2, (top + bottom) // 2))
            state = ""
            if node.get("checkable") == "true":
                state = " (on)" if node.get("checked") == "true" else " (off)"
            lines.append(f'[{len(points)}] {node.get("class", "").rsplit(".", 1)[-1]} "{label}"{state}')
        self._seen = tuple(points)
        return "\n".join(lines)

    @action(view="text")
    def click_ref(self, ref: int, hold: bool = False):
        """Tap the element with this number. hold=True is a long press, which selects it or opens its menu."""
        if not 1 <= ref <= len(self._seen):
            raise ValueError(f"No element [{ref}]. Numbers come from the latest description.")
        self.click(*self._seen[ref - 1], hold)
