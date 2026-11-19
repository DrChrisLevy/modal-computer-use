"""Save a run so it can be watched afterwards: a screenshot per step and a page to flip through them."""

import json
from pathlib import Path

from .loop import Run

PAGE = Path(__file__).with_name("replay.html")


def save(record: Run, directory: Path) -> Path:
    """Write the run to `directory` and return the path of its replay page."""
    directory.mkdir(parents=True, exist_ok=True)
    steps = []
    for number, step in enumerate(record.steps, 1):
        image = None
        if step.screenshot:
            image = f"{number:02}.png"
            (directory / image).write_bytes(step.screenshot)
        steps.append(
            {
                "image": image,
                "screen": step.screen_text,
                "thought": step.thought,
                "action": step.summary(),
                "seconds": round(step.seconds, 1),
            }
        )
    data = {"task": record.task, "answer": record.answer, "steps": steps}
    (directory / "steps.json").write_text(json.dumps(data, indent=2))
    replay = directory / "replay.html"
    # The data sits inside a <script> element, so a "</script>" in recorded text must not end it.
    replay.write_text(PAGE.read_text().replace("__RUN__", json.dumps(data).replace("</", "<\\/")))
    return replay
