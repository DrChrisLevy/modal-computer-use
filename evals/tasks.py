"""Small tasks with a pass/fail check that reads the computer's real state, never the agent's own claim."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from computers import Android, Browser, Computer, Desktop

PAGES = Path(__file__).parent / "pages"


@dataclass(frozen=True)
class Task:
    name: str
    computer: type[Computer]
    prompt: str
    setup: Callable[[Computer], object]
    check: Callable[[Computer], bool | dict]  # a dict holds "passed" and anything else worth recording
    instruction: Callable[[Computer], str] | None = None  # reads the prompt off the computer, when only it knows
    finished: Callable[[Computer], bool] | None = None  # true once nothing the agent does can change the result
    max_steps: int = 25  # the most steps an agent may take
    wants_answer: bool = False  # check is called as check(computer, answer), with what the agent passed to done


def web_task(name: str, prompt: str) -> Task:
    """A task on one of the pages in evals/pages, served from inside the Sandbox.

    Each page sets `window.passed` when it has been solved.
    """

    def setup(browser: Browser) -> None:
        browser.sandbox.filesystem.write_text((PAGES / f"{name}.html").read_text(), f"/tmp/{name}.html")
        serve = "cd /tmp && (nohup python -m http.server 8000 >/dev/null 2>&1 &)"
        wait = "until (echo >/dev/tcp/127.0.0.1/8000) 2>/dev/null; do sleep 0.1; done"
        browser.run("bash", "-c", f"{serve} && {wait}")
        browser.goto(f"http://localhost:8000/{name}.html")

    return Task(name, Browser, prompt, setup, lambda browser: browser.eval("window.passed === true"))


def saved(desktop: Desktop, path: str) -> str:
    """The contents of a file on the desktop, or an empty string if it does not exist."""
    return desktop.run("bash", "-c", f"cat {path} 2>/dev/null || true").strip()


def has_contact(name: str, digits: str) -> Callable[[Android], bool]:
    """True when the phone's contacts database holds this name and this phone number."""

    def check(phone: Android) -> bool:
        rows = phone.adb("shell", "content", "query", "--uri", "content://com.android.contacts/data")
        return name in rows and digits in "".join(character for character in rows if character.isdigit())

    return check


TASKS = [
    web_task("click-order", "Press the buttons in this order: Charlie, Alpha, Delta, Bravo."),
    web_task(
        "signup",
        "Create an account for Ada Lovelace, email ada@example.com, on the Team plan. Accept the terms and submit.",
    ),
    web_task("orders", "Refund order #1042: enter that order's total in the refund box and issue the refund."),
    web_task(
        "hidden-code",
        "Reveal the verification code at the bottom of the page, type it into the box at the top, and press Verify.",
    ),
    web_task("shop", "Buy two Notebooks and one Pen, and nothing else, then check out."),
    Task(
        "save-note",
        Desktop,
        'In the Mousepad text editor, write the text "Hello from Modal" (without the quotes) '
        "and save the file as /home/agent/note.txt.",
        setup=lambda desktop: desktop.launch("mousepad"),
        check=lambda desktop: saved(desktop, "/home/agent/note.txt") == "Hello from Modal",
    ),
    Task(
        "kernel-version",
        Desktop,
        "Using the terminal window, save this machine's kernel release (the output of `uname -r`) "
        "to the file /home/agent/kernel.txt.",
        setup=lambda desktop: desktop.launch("xfce4-terminal"),
        check=lambda desktop: saved(desktop, "/home/agent/kernel.txt") == desktop.run("uname", "-r").strip(),
    ),
    Task(
        "airplane-mode",
        Android,
        "Turn on airplane mode.",
        setup=lambda phone: phone.adb("shell", "am", "start", "-a", "android.settings.SETTINGS"),
        check=lambda phone: phone.adb("shell", "settings", "get", "global", "airplane_mode_on").strip() == "1",
    ),
    Task(
        "dark-theme",
        Android,
        "Turn on the dark theme.",
        setup=lambda phone: phone.adb("shell", "am", "start", "-a", "android.settings.SETTINGS"),
        check=lambda phone: "yes" in phone.adb("shell", "cmd", "uimode", "night"),
    ),
    Task(
        "add-contact",
        Android,
        "Using the Contacts app, create a new contact named Ada Lovelace with the phone number 5550100 and save it.",
        setup=lambda phone: phone.key("HOME"),
        check=has_contact("Ada Lovelace", "5550100"),
    ),
]
