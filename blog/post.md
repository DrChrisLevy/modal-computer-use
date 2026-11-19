# Using Modal Sandboxes for Computer Use

The idea with this tutorial is to keep the code relatively simple and light on dependencies.
Use it as inspiration for your own projects or as a reference with your coding agents.
The only dependency is `modal`!

Okay, let's get right into it.

## Setup

```sh
uv sync
uv run modal setup
export MODAL_ENVIRONMENT=your-environment
```

## The Idea

The code snippets here are slightly simplified versions of [the code](TODO-link-to-the-code) we will
import and use later on, but the overall idea is the same.

```python
import modal


class Computer:
    def __init__(self, sandbox: modal.Sandbox):
        self.sandbox = sandbox

    @classmethod
    def create(cls, **options):
        """Start a Sandbox running this computer and wait until its screen is usable."""
        app = modal.App.lookup("computers", create_if_missing=True)
        settings = {"image": cls.image, "timeout": 3600, **cls.options, **options}
        computer = cls(modal.Sandbox.create(*cls.command, app=app, **settings))
        computer.sandbox.wait_until_ready(timeout=180)
        return computer

    def run(self, *argv, binary=False):
        """Run one command inside the computer and return its output."""
        process = self.sandbox.exec(*map(str, argv), text=not binary, env=self.exec_env)
        output = process.stdout.read()
        if process.wait() != 0:
            raise RuntimeError(f"{argv[0]} failed: {process.stderr.read()}")
        return output
```

To create a Linux desktop from the above base class, we can do the following:

```python
desktop_image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("xvfb", "xfce4", "dbus-x11")  # a virtual screen and a desktop to put on it
    .apt_install("x11vnc", "novnc", "websockify")  # the live viewer
    .apt_install("xdotool", "scrot")  # the hands and the eyes
    .apt_install("mousepad", "xfce4-terminal", "chromium")  # something to use
    .run_commands("useradd --create-home agent")  # the desktop runs as an ordinary user, not root
    .add_local_file("start-desktop.sh", "/opt/start-desktop.sh", copy=True)
)


class Desktop(Computer):
    image = desktop_image
    command = ("bash", "/opt/start-desktop.sh")
    options = {"cpu": 2, "memory": 4096, "readiness_probe": modal.Probe.with_tcp(6080)}  # ready when the viewer is up
    exec_env = {"DISPLAY": ":0"}

    def screenshot(self) -> bytes:
        return self.run("scrot", "--pointer", "-", binary=True)

    def click(self, x: int, y: int):
        self.run("xdotool", "mousemove", x, y, "click", 1)

    def type(self, text: str):
        self.run("xdotool", "type", "--clearmodifiers", "--delay", 12, "--", text)

    def key(self, name: str):
        self.run("xdotool", "key", "--clearmodifiers", "--", name)
```

The code for interacting with the browser or Android is similar; see [the code](TODO-link-to-the-code).

## A Quick Look at Each Use Case (Desktop, Browser, Android)

```python
from computers import Android, Browser, Desktop
```

### A Linux desktop

```python
import time

with Desktop.create() as desktop:
    print("Watch it live:", desktop.live_view())  # a private link to the screen
    input("Open the link, then press Enter to start. ")

    desktop.launch("mousepad")  # open a text editor
    time.sleep(3)  # give the window a moment to appear
    desktop.type("Hello from a Modal Sandbox.")
    desktop.key("ctrl+a")  # select what we typed

    png = desktop.screenshot()  # the screen as PNG bytes
    input("Press Enter to shut the desktop down. ")
```

<video src="desktop1.mp4" controls title="A text editor on the Linux desktop, in the Sandbox"></video>

### A browser

A `Browser` is that same desktop with Chromium running full screen on top:

```python
with Browser.create() as browser:
    print("Watch it live:", browser.live_view())
    browser.goto("https://modal.com")
    input("Press Enter to shut the browser down. ")
```

<video src="browser1.mp4" controls title="modal.com, in the Sandbox's browser"></video>

### An Android phone

An `Android` is Google's Android emulator running in a Sandbox, controlled with `adb`:

```python
import time

with Android.create() as phone:
    print("Watch it live:", phone.live_view())
    input("Open the link, then press Enter to start. ")

    phone.open_app("Settings")
    time.sleep(3)
    phone.click(376, 660)  # tap the search bar
    time.sleep(2)
    phone.type("battery")
    time.sleep(3)
    phone.adb("shell", "cmd", "uimode", "night", "yes")  # any adb command works: this one turns on the dark theme
    time.sleep(3)
    phone.open_app("Clock")
    time.sleep(3)
    phone.key("HOME")
    time.sleep(2)
    phone.swipe("up")  # open the list of apps

    input("Press Enter to shut the phone down. ")
```

<video src="android1.mp4" controls title="The Android phone in the Sandbox"></video>

### Skipping the phone's boot with a snapshot

The Sandbox itself starts in about a second, but the Android phone inside it takes about a minute to
boot. To speed that up, we can boot one phone, take a
[memory snapshot](https://modal.com/docs/guide/sandbox-snapshots#memory-snapshots) of it, and start
every later phone from that snapshot. Memory snapshots are in alpha at the time of writing.

```python
import modal

phone = Android.create(_experimental_enable_snapshot=True)
snapshot = phone.sandbox._experimental_snapshot()

copy = Android(modal.Sandbox._experimental_from_snapshot(snapshot))
print("Watch it live:", copy.live_view())
input("Open the link, then press Enter to start. ")

copy.open_app("Clock")
time.sleep(3)
copy.open_app("Settings")
time.sleep(3)
copy.swipe("up")  # scroll down the list

input("Press Enter to shut the copy down. ")
copy.terminate()
```

<video src="android2.mp4" controls title="A copy of the phone, started from the snapshot"></video>

The first boot took about a minute, and each copy was ready in about 3 seconds.

## Let an Agent Use the Tools

Now we hand those methods to an agent. The models here are served on
[Modal Endpoints](https://modal.com/docs/guide/endpoints). I used Kimi K3.1 Pro and also tried Qwen 3.8
Max VL, but the choice doesn't really matter: any model that can look at an image and speak the
OpenAI-style chat API will do.

### How the tools reach the model

There is no framework here, just an LLM and a basic agent loop.
In the code, each method with the `@action` decorator is available as a tool:

```python
class Desktop(Computer):
    @action
    def type(self, text: str):
        """Type text into whatever has keyboard focus."""
        self.run("xdotool", "type", "--clearmodifiers", "--delay", 12, "--", text)
```

`computer.actions("pixels")` collects those into one line each: the signature plus the docstring. For
the browser, it gives:

```text
- click(x: int, y: int, button: str = 'left', count: int = 1) - Click at a point. button is left, middle or right; count=2 double-clicks.
- drag(x1: int, y1: int, x2: int, y2: int) - Press the left button at one point, move to another, and release.
- goto(url: str) - Load a URL in the browser.
- key(name: str) - Press a key or shortcut by its xdotool name: Return, Tab, Escape, BackSpace, ctrl+s, alt+F4.
- move(x: int, y: int) - Move the mouse to a point without clicking.
- scroll(x: int, y: int, dy: int) - Scroll the content under a point by about dy pixels. Positive scrolls down, negative up.
- type(text: str) - Type text into whatever has keyboard focus.
```

That text goes into the prompt. The model answers with one JSON object naming an action:

```json
{"thought": "The page is blank. I'll open modal.com.", "action": "goto", "arguments": {"url": "https://modal.com"}}
```

Then `computer.act("goto", "pixels", url="https://modal.com")` looks the method up by name and calls it.
So the tools are just the class's own methods, described by their own signatures.

### The agent loop

Look at the screen, ask the model for one action, do it, repeat:

```python
import json
import time

SYSTEM = """You operate a computer to complete a task. Each turn you get a screenshot of its screen,
which is {width}x{height} pixels. Reply with one JSON object and nothing else:
{{"thought": "<what you see and what you will do>", "action": "<name>", "arguments": {{...}}}}

Actions:
{actions}
- done(answer: str) - Finish, once the task is complete."""


def run(computer, task, model, max_steps=30):
    width, height = computer.size
    actions = "\n".join(f"- {line}" for line in computer.actions("pixels").values())
    system = SYSTEM.format(width=width, height=height, actions=actions)
    notes = []  # the model's memory: what it thought and did on earlier steps

    for _ in range(max_steps):
        screenshot = computer.screenshot()  # 1. look at the screen
        prompt = f"Task: {task}\n\nYour steps so far:\n" + "\n".join(notes)
        decision = json.loads(model.complete(system, prompt, screenshot))  # 2. ask the model for one action
        if decision["action"] == "done":
            return decision["arguments"].get("answer")
        computer.act(decision["action"], "pixels", **decision["arguments"])  # 3. do it
        notes.append(f"{decision['thought']} -> {decision['action']}({decision['arguments']})")
        time.sleep(computer.settle)  # 4. give the screen a moment to change
```

Like the classes earlier, this is a simplified version of [the real loop](TODO-link-to-the-code),
which is about 190 lines. The real one can also cope with replies it can't read, show the model the
page as text instead of a screenshot, and pause a task and pick it up later.

```python
import agent
from computers import Browser

model = agent.modal_endpoint("kimi-k3-1-pro")

with Browser.create() as browser:
    result = agent.run(browser, "Go to modal.com, open the Pricing page, and tell me its main headline.", model)
    print(result.answer)
```

To try the real loop from your terminal, giving it one task after another:

```sh
uv run python -m examples.chat
```

## How Well Does It Work?