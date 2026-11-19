"""A Computer is a Modal Sandbox with a screen, plus the few methods an agent needs to use it."""

import inspect
import os
from typing import ClassVar, Self

import modal

APP_NAME = os.environ.get("COMPUTERS_APP", "computers")
VIEWER_PORT = 6080  # noVNC, inside every Computer


def action(method=None, *, view: str | None = None):
    """Mark a method as something a model may call.

    `view` restricts it to agents that see the screen as "pixels" (a screenshot) or as
    "text" (the output of `describe`). Unrestricted actions are offered to both.
    """

    def mark(fn):
        fn.action_view = view
        return fn

    return mark(method) if method else mark


class Computer:
    """Base class. Subclasses set the image and startup command, and add their controls."""

    image: ClassVar[modal.Image]
    command: ClassVar[tuple[str, ...]]
    options: ClassVar[dict] = {}  # default Sandbox.create arguments
    exec_env: ClassVar[dict[str, str]] = {}
    kind: ClassVar[str]  # what an agent is told it is operating, such as "web browser"
    size: tuple[int, int]  # screen size in pixels; screenshot coordinates use this space
    settle: ClassVar[float] = 0.3  # seconds the screen needs to catch up after an action

    def __init__(self, sandbox: modal.Sandbox):
        self.sandbox = sandbox

    @classmethod
    def create(cls, **options) -> Self:
        """Start a Sandbox running this computer and wait until its screen is usable.

        Keyword arguments are passed to `modal.Sandbox.create` and override the class defaults,
        so `image=` can be a filesystem snapshot of an earlier computer.
        """
        app = modal.App.lookup(APP_NAME, create_if_missing=True)
        settings = {"image": cls.image, "timeout": 3600, **cls.options, **options}
        computer = cls(modal.Sandbox.create(*cls.command, app=app, **settings))
        try:
            computer.wait_ready()
        except BaseException:
            computer.terminate()
            raise
        return computer

    @classmethod
    def from_id(cls, sandbox_id: str) -> Self:
        """Attach to a computer that is already running."""
        return cls(modal.Sandbox.from_id(sandbox_id))

    def wait_ready(self) -> None:
        self.sandbox.wait_until_ready(timeout=180)

    def run(self, *argv, timeout: int = 60, binary: bool = False, env: dict[str, str] | None = None):
        """Run one command inside the computer and return its stdout. Raises if it fails.

        Every control is built on this method, so it is the one to replace to host a computer elsewhere.
        """
        environment = {**self.exec_env, **(env or {})}
        process = self.sandbox.exec(*map(str, argv), timeout=timeout, text=not binary, env=environment)
        output = process.stdout.read()
        if process.wait() != 0:
            error = process.stderr.read()
            error = error.decode(errors="replace") if isinstance(error, bytes) else error
            raise RuntimeError(f"{argv[0]} exited {process.returncode}: {error[-2000:]}")
        return output

    def screenshot(self) -> bytes:
        """The current screen as PNG bytes."""
        raise NotImplementedError

    def describe(self) -> str:
        """The current screen as text, with numbered elements. Not every computer can do this."""
        raise NotImplementedError(f"{type(self).__name__} has no text view")

    def live_view(self) -> str:
        """A private URL for watching and controlling the screen from a web browser."""
        credentials = self.sandbox.create_connect_token(port=VIEWER_PORT)
        return f"{credentials.url}/vnc.html?autoconnect=1&resize=scale&_modal_connect_token={credentials.token}"

    def terminate(self) -> None:
        self.sandbox.terminate()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc) -> None:
        self.terminate()

    def actions(self, view: str) -> dict[str, str]:
        """The actions offered to an agent with the given view, as `{name: "signature - docstring"}`.

        The view is "pixels", "text", or "both", which offers the actions of either.
        """
        offered = {}
        for name, method in inspect.getmembers(self, inspect.ismethod):
            offered_in = getattr(method, "action_view", "not an action")
            if offered_in in (None, view) or (view == "both" and offered_in in ("pixels", "text")):
                offered[name] = f"{name}{inspect.signature(method)} - {inspect.getdoc(method)}"
        return offered

    def act(self, name: str, view: str, /, **arguments):
        """Run one action by name. Only actions offered for `view` are allowed.

        `name` and `view` are positional-only so an action may have arguments with those names.
        """
        if name not in self.actions(view):
            raise ValueError(f"Unknown action {name!r}. Choose from: {', '.join(self.actions(view))}")
        return getattr(self, name)(**arguments)
