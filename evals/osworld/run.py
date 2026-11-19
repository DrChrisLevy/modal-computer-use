"""Run OSWorld tasks on Modal with our loop: a fresh virtual machine per task, several at once.

OSWorld is a benchmark of real desktop tasks (LibreOffice, Chrome, GIMP, VS Code, the file manager)
scored by inspecting the machine afterwards. It brings its own virtual machine and its own Python
environment, so it is not a dependency of this repo and not a suite of `evals.run`. Set it up once:

    git clone https://github.com/xlang-ai/OSWorld ~/OSWorld && cd ~/OSWorld
    uv sync && uv pip install "modal>=1.6"
    .venv/bin/python -m desktop_env.providers.modal.setup --os Ubuntu   # copies the machine's disk to a Modal Volume

Then run this from that checkout, with its Python:

    cd ~/OSWorld
    PYTHONPATH=/path/to/this/repo .venv/bin/python -m evals.osworld.run

Results are written to runs/<time>/ in the OSWorld checkout as they arrive, with a replay of every run.
"""

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import agent
from agent import replay

from .desktop import OSWorldDesktop

EXAMPLES = Path("evaluation_examples")  # relative to the OSWorld checkout this runs from
# OSWorld scores a task from the files and settings left on the machine, so work that looks right on
# screen but was not saved, or was saved under another name, scores nothing. Its own agents are told
# as much, and these rules say the same. It also includes tasks that cannot be done, and scores those
# by whether the agent says so.
PROMPT = """{instruction}

Rules:
- The computer's password is "{password}". You have at most {max_steps} steps.
- Keep every path, file name, extension and application exactly as the task gives them.
- Save your work, then check the result itself: reopen the file or read the setting back. \
Seeing your actions run is not enough.
- Before you finish, make sure every part of the task is done and no dialog or error is left open.
- In LibreOffice and GIMP, work in the app's own interface: no macros, scripts or other programs \
unless the task asks for them. In GIMP, do not save or export unless the task asks.
- If the task cannot be done on this computer, finish with the answer INFEASIBLE."""


def trial(domain: str, task_id: str, model_name: str, folder: Path, max_steps: int) -> dict:
    """Boot a machine for one task, let the loop work on it, and score it the way OSWorld does."""
    from desktop_env.desktop_env import DesktopEnv

    task = json.loads((EXAMPLES / "examples" / domain / f"{task_id}.json").read_text())
    row = {"domain": domain, "task": task_id, "score": 0.0, "steps": 0, "seconds": 0.0}
    env = None
    try:
        env = DesktopEnv(provider_name="modal", action_space="pyautogui", headless=True, require_a11y_tree=False)
        try:
            env.reset(task_config=task)
        except Exception as error:  # a few tasks need Google Drive credentials to prepare the machine
            row["skipped"] = f"could not be set up: {error}"[:200]
            return row
        time.sleep(60)  # OSWorld's own runner waits this long for the task's apps to finish opening
        started = time.monotonic()
        prompt = PROMPT.format(instruction=task["instruction"], password=env.client_password, max_steps=max_steps)
        # The endpoint settings ask for little reasoning, which is quick and enough for short tasks. On
        # these the model then reports checks it has not really made, so leave the amount to the server.
        model = agent.modal_endpoint(model_name)
        options = {name: value for name, value in model.options.items() if name != "reasoning_effort"}
        model = replace(model, options=options)
        record = agent.run(OSWorldDesktop(env), prompt, model, max_steps=max_steps)
        row["seconds"] = round(time.monotonic() - started, 1)
        row["steps"] = len(record.steps)
        replay.save(record, folder / f"{domain}-{task_id}")
        gave_up = (record.answer or "").strip().upper().startswith("INFEASIBLE")
        env.step("FAIL" if gave_up else "DONE")
        time.sleep(20)  # as OSWorld's runner does, so files being saved have landed
        row["score"] = float(env.evaluate())
    except Exception as error:
        row["error"] = f"{type(error).__name__}: {error}"[:300]
    finally:
        if env:
            env.close()
        note = row.get("skipped") or row.get("error", "")
        print(
            f"{row['score']:4.2f}  {domain:20} {task_id}  {row['steps']:3} steps {row['seconds']:6.1f}s  {note}",
            flush=True,
        )
    return row


def summary(rows: list[dict]) -> str:
    """A Markdown table of the total score per kind of task, over the tasks that could be set up.

    OSWorld scores each task between 0 and 1.
    """
    skipped = sum("skipped" in row for row in rows)
    rows = [row for row in rows if "skipped" not in row]
    lines = ["| Domain | Tasks | Score |", "| --- | ---: | ---: |"]
    for domain in sorted({row["domain"] for row in rows}):
        scores = [row["score"] for row in rows if row["domain"] == domain]
        lines.append(f"| {domain} | {len(scores)} | {sum(scores):.1f} |")
    total = sum(row["score"] for row in rows)
    lines.append(f"| **all** | {len(rows)} | **{total:.1f} ({100 * total / len(rows):.0f}%)** |")
    return "\n".join(lines) + (f"\n\n{skipped} more could not be set up." if skipped else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--tasks", default="test_small", help="a task list in evaluation_examples: test_small, test_all"
    )
    parser.add_argument("--domains", help="comma-separated domains to keep, such as chrome,os; default is all")
    parser.add_argument("--limit", type=int, help="run only the first N tasks")
    parser.add_argument("--model", default="kimi-k3-1-pro", help="name of a Modal Endpoint")
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--parallel", type=int, default=8, help="virtual machines to run at once")
    args = parser.parse_args()

    listed = json.loads((EXAMPLES / f"{args.tasks}.json").read_text())
    domains = args.domains.split(",") if args.domains else sorted(listed)
    jobs = [(domain, task_id) for domain in domains for task_id in listed[domain]][: args.limit]
    folder = Path("runs") / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True)
    print(f"Running {len(jobs)} tasks with {args.model}, {args.parallel} at a time. Results in {folder}/")
    rows = []
    with ProcessPoolExecutor(args.parallel) as pool:
        futures = [pool.submit(trial, *job, args.model, folder, args.max_steps) for job in jobs]
        for future in futures:
            rows.append(future.result())
            (folder / "results.json").write_text(json.dumps(rows, indent=2))
    (folder / "results.md").write_text(summary(rows) + "\n")
    print(summary(rows))


if __name__ == "__main__":
    main()
