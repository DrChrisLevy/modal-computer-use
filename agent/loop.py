"""One agent loop for every Computer: look at the screen, ask a model for one action, run it, repeat."""

import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from computers import Computer

from .model import Model

SYSTEM = """You operate a {kind} to complete a task. {screen}

Reply with exactly one JSON object and nothing else:
{{"thought": "<what you see, what to remember, what you do next>", "action": "<name>", "arguments": {{...}}}}

Actions:
{actions}
- done(answer: str) - Finish. Use only once the task is complete; put any requested result in answer.

Take one action per turn. After each action you get the new screen, so check that it worked.
You only ever see the current screen and your own earlier thoughts, so note anything you will need later."""

ASK_USER = (
    "- ask_user(question: str) - Pause and ask the person you work for. "
    "Only for something you cannot find out or do yourself, such as a password or a choice that is theirs."
)
SEEN = {"pixels": "a screenshot", "text": "the screen as text", "both": "a screenshot and the same screen as text"}
PIXELS = "The screenshot is {width}x{height} pixels. Positions are pixels measured from its top-left corner."
GRID = (
    "Give positions in the screenshot on a 0-{grid} grid: x=0 is the left edge and x={grid} the right edge; "
    "y=0 is the top edge and y={grid} the bottom edge."
)
NUMBERS = "In the text, controls are numbered like [3]; refer to them by number."

MAX_FAILURES = 3  # consecutive failed steps before the loop gives up


@dataclass
class Step:
    thought: str = ""
    action: str = ""
    arguments: dict = field(default_factory=dict)
    result: str = "ok"
    screenshot: bytes | None = None  # what the model saw, in the pixels and both views
    screen_text: str | None = None  # what the model saw, in the text and both views
    seconds: float = 0.0

    @property
    def failed(self) -> bool:
        return self.result.startswith("error")

    def summary(self) -> str:
        arguments = ", ".join(f"{name}={value!r}" for name, value in self.arguments.items())
        return f"{self.action}({arguments}) -> {self.result}"


@dataclass
class Run:
    task: str
    steps: list[Step] = field(default_factory=list)
    answer: str | None = None  # set when the model calls done
    question: str | None = None  # set while the run is paused, waiting for the user to answer

    @property
    def finished(self) -> bool:
        return self.answer is not None

    def to_json(self) -> str:
        """Everything needed to continue the run later, in another process. Screens are left out."""
        steps = [asdict(step) | {"screenshot": None, "screen_text": None} for step in self.steps]
        return json.dumps({"task": self.task, "answer": self.answer, "question": self.question, "steps": steps})

    @classmethod
    def from_json(cls, text: str) -> "Run":
        data = json.loads(text)
        return cls(data["task"], [Step(**step) for step in data["steps"]], data["answer"], data["question"])


def parse(reply: str) -> dict:
    """Pull the JSON object out of a model reply, tolerating code fences and surrounding prose."""
    start, end = reply.find("{"), reply.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in the reply")
    decision = json.loads(reply[start : end + 1])
    if not isinstance(decision.get("action"), str):
        raise ValueError('the reply needs an "action" name')
    if not isinstance(decision.setdefault("arguments", {}), dict):
        raise ValueError('"arguments" must be a JSON object')
    return decision


def to_pixels(arguments: dict, grid: int, size: tuple[int, int]) -> dict:
    """Convert positions from a model's 0-grid scale to screen pixels. Positions are the x... and y... arguments."""
    scale = {"x": size[0] / grid, "y": size[1] / grid}
    return {
        name: round(value * scale[name[0]]) if name[0] in scale and isinstance(value, int | float) else value
        for name, value in arguments.items()
    }


def run(computer: Computer, task: str, model: Model, **options) -> Run:
    """Drive `computer` with `model` until it calls done or runs out of steps. Options are those of `resume`."""
    return resume(computer, Run(task), model, **options)


def resume(
    computer: Computer,
    record: Run,
    model: Model,
    *,
    reply: str | None = None,
    view: str | None = None,
    max_steps: int = 30,
    settle: float | None = None,
    can_ask: bool = False,
    stop: Callable[[], bool] | None = None,
    on_step: Callable[[Step], None] | None = None,
) -> Run:
    """Continue a run: one that was interrupted, loaded with `Run.from_json`, or paused on a question.

    `reply` answers the question a paused run asked.
    `view` is how the model sees the screen: "pixels" (a screenshot), "text" (`computer.describe()`), or "both".
    It defaults to "both", or to "pixels" on a computer that has no text view.
    `max_steps` counts the steps already taken.
    `settle` is the pause in seconds after each action, so the screen can catch up before the next look.
    It defaults to the computer's own `settle`.
    `can_ask` offers the model an `ask_user` action, which pauses the run with `record.question` set.
    `stop` is checked before each step; returning true ends the run there.

    A step that fails (an unreadable reply, a rejected action, a network error) is recorded and shown
    to the model on its next turn. The run ends early after three failed steps in a row.
    """
    width, height = computer.size
    settle = computer.settle if settle is None else settle
    if view is None:
        view = "pixels" if type(computer).describe is Computer.describe else "both"
    grid = model.grid if view != "text" else None
    hints = [f"Each turn you get {SEEN[view]}."]
    if view != "text":
        hints.append((GRID if grid else PIXELS).format(width=width, height=height, grid=grid))
    if view != "pixels":
        hints.append(NUMBERS)
    actions = [f"- {line}" for line in computer.actions(view).values()] + ([ASK_USER] if can_ask else [])
    system = SYSTEM.format(kind=computer.kind, screen=" ".join(hints), actions="\n".join(actions))

    if record.question is not None and reply is not None:
        record.steps[-1].result = f"the user replied: {reply}"
        record.question = None
    failures = 0
    while len(record.steps) < max_steps and not record.finished and record.question is None:
        if failures == MAX_FAILURES or (stop and stop()):
            break
        started = time.monotonic()
        step = Step()
        # The model's memory is its own earlier thoughts, not earlier screens.
        history = "\n".join(f"{i}. {s.thought}\n   {s.summary()}" for i, s in enumerate(record.steps, 1))
        try:
            if view != "text":
                step.screenshot = computer.screenshot()
            if view != "pixels":
                step.screen_text = computer.describe()
            screen = step.screen_text or "(attached)"
            prompt = (
                f"Task: {record.task}\n\nYour steps so far:\n{history or '(none yet)'}\n\nCurrent screen:\n{screen}"
            )
            decision = parse(model.complete(system, prompt, step.screenshot))
            step.thought = str(decision.get("thought", ""))
            step.action = decision["action"]
            step.arguments = decision["arguments"]
            if step.action == "done":
                record.answer = str(step.arguments.get("answer", ""))
            elif step.action == "ask_user" and can_ask:
                record.question = str(step.arguments.get("question", ""))
                step.result = "waiting for the user"
            else:
                arguments = to_pixels(step.arguments, grid, computer.size) if grid else step.arguments
                computer.act(step.action, view, **arguments)
                time.sleep(settle)
        except NotImplementedError:
            raise  # this computer has no such view; retrying cannot help
        except Exception as error:
            step.result = f"error: {error}"
        failures = failures + 1 if step.failed else 0
        step.seconds = time.monotonic() - started
        record.steps.append(step)
        if on_step:
            on_step(step)
    return record
