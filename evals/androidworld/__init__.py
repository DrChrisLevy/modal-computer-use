"""AndroidWorld: 116 tasks across 20 real Android apps, each prepared and scored by the benchmark's own code.

AndroidWorld (github.com/google-research/android_world) ships an agent framework. This uses only two
pieces of it, through on_phone.py: "prepare task N on the phone" and "is task N solved". Our loop drives
the phone exactly as it drives any other Android.

Every trial starts from a phone that already has AndroidWorld's apps installed. Make it once with
`uv run python -m evals.androidworld.setup`.
"""

import json
from pathlib import Path

import modal

from computers import Android

from ..tasks import Task

COMMIT = "55ddaf5edc6f6c25673aed343907d5b9dca66f84"  # google-research/android_world, as of November 2026
PREPARED = "androidworld-phone"  # the name setup.py publishes its filesystem snapshot under
SEED = 30  # AndroidWorld fills each task's blanks (names, amounts, dates) at random; 30 is its default seed

# name -> the step budget AndroidWorld gives the task, which is ten times its difficulty rating
BUDGETS = {
    name: int(steps) for name, steps in map(str.split, Path(__file__).with_name("tasks.txt").read_text().splitlines())
}

SCRIPT = Path(__file__).with_name("on_phone.py")

# AndroidWorld is installed next to the emulator, because it prepares and scores tasks over adb.
# Its code expects the emulator's gRPC port to be 8554. Pillow is a dependency its package forgets to declare.
unprepared_image = (
    Android.image.apt_install("git", "ffmpeg")
    .pip_install(f"android_world @ git+https://github.com/google-research/android_world@{COMMIT}", "pillow")
    .env({"EMULATOR_FLAGS": "-grpc 8554"})
)


class AndroidWorldPhone(Android):
    """An Android that starts from the snapshot with AndroidWorld's apps installed."""

    image = modal.Image.from_name(PREPARED)


def reply(phone: Android, name: str) -> dict:
    """Wait for a file that on_phone.py writes when it has finished a stage, and return its contents."""
    path = f"/tmp/androidworld/{name}"
    contents = json.loads(phone.run("bash", "-c", f"until [ -e {path} ]; do sleep 1; done; cat {path}", timeout=900))
    if "error" in contents:
        raise RuntimeError(f"AndroidWorld failed inside the Sandbox: {contents['error']}")
    return contents


def androidworld_task(name: str) -> Task:
    def setup(phone: Android) -> None:
        phone.sandbox.filesystem.write_text(SCRIPT.read_text(), "/tmp/androidworld.py")
        start = f"nohup python /tmp/androidworld.py task {name} {SEED} >/tmp/androidworld.log 2>&1 &"
        phone.run("bash", "-c", start)

    def check(phone: Android, answer: str | None) -> bool:
        """AndroidWorld's rule: the phone must be in the right state and the agent must have said it was done."""
        phone.sandbox.filesystem.write_text(answer or "", "/tmp/androidworld/answer.txt")
        solved = reply(phone, "score.json")["score"] == 1
        if solved and answer is None:
            print(f"      {name}: solved, but the agent never called done, so AndroidWorld counts it as failed")
        return solved and answer is not None

    return Task(
        name,
        AndroidWorldPhone,
        prompt="",
        setup=setup,
        check=check,
        instruction=lambda phone: reply(phone, "goal.json")["goal"],  # the task's wording with its blanks filled in
        max_steps=BUDGETS[name],
        wants_answer=True,
    )


TASKS = [androidworld_task(name) for name in BUDGETS]
