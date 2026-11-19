"""Run the eval: each task with each agent, every trial in its own fresh Sandbox.

    uv run python -m evals.run
    uv run python -m evals.run --tasks signup,shop --agents pixels,text --trials 3
    uv run python -m evals.run --suite miniwob      # or webbench, or androidworld

Agents:
    pixels       our loop, looking at screenshots
    text         our loop, reading the screen as text (browser and Android only)
    both         our loop, given the screenshot and the text together (browser and Android only)
    browser-use  the Browser Use library (browser only)

Results are written to runs/<time>/ as they arrive, with a replay of every run by our loop.
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path

import agent
from agent import Model, replay
from computers import Browser, Desktop

from . import androidworld, browser_use, miniwob, tasks, webbench
from .tasks import Task

SUITES = {
    "basic": tasks.TASKS,
    "miniwob": miniwob.TASKS,
    "webbench": webbench.TASKS,
    "androidworld": androidworld.TASKS,
}
AGENTS = ("pixels", "text", "both", "browser-use")


def supports(agent_name: str, task: Task) -> bool:
    if agent_name == "browser-use":
        return issubclass(task.computer, Browser)
    if agent_name in ("text", "both"):
        return task.computer is not Desktop  # a bare desktop has no text view
    return True


def trial(
    task: Task, agent_name: str, model: Model, folder: Path, *, max_steps: int | None, settle: float | None
) -> dict:
    """Run one task once and report what happened.

    The check reads the computer's real state. A task that asks a question is also given the agent's answer.
    """
    row = {"task": task.name, "computer": task.computer.kind, "agent": agent_name}
    row |= {"passed": False, "steps": 0, "seconds": 0.0}
    max_steps = max_steps or task.max_steps  # --max-steps, or else the task's own budget
    computer_class = task.computer
    if agent_name == "browser-use" and not issubclass(computer_class, browser_use.BrowserWithBrowserUse):
        computer_class = browser_use.BrowserWithBrowserUse
    try:
        with computer_class.create() as computer:
            task.setup(computer)
            prompt = task.instruction(computer) if task.instruction else task.prompt
            time.sleep(3)  # let the app or page finish opening
            started = time.monotonic()
            answer = None  # what the agent passed to done, for the tasks whose check asks for it
            if agent_name == "browser-use":
                row["steps"] = browser_use.drive(computer, prompt, model, max_steps)
            else:
                stop = (lambda: task.finished(computer)) if task.finished else None
                options = {"view": agent_name, "max_steps": max_steps, "settle": settle, "stop": stop}
                record = agent.run(computer, prompt, model, **options)
                replay.save(record, folder)
                row["steps"], answer = len(record.steps), record.answer
            row["seconds"] = round(time.monotonic() - started, 1)
            # true or false, or a dict with "passed" and more to record
            verdict = task.check(computer, answer) if task.wants_answer else task.check(computer)
            row |= verdict if isinstance(verdict, dict) else {"passed": bool(verdict)}
    except Exception as error:
        row["error"] = f"{type(error).__name__}: {error}"[:300]
    outcome = "PASS" if row["passed"] else "FAIL"
    timing = f"{row['steps']:2} steps {row['seconds']:6.1f}s"
    print(f"{outcome}  {task.name:15} {agent_name:12} {timing}  {row.get('error', '')}", flush=True)
    return row


def summary(rows: list[dict]) -> str:
    """A Markdown table per kind of computer, so agents are only compared on the tasks they share.

    Mean steps and seconds are over the trials that passed; the mean score is over all of them.
    """
    lines = []
    for computer in sorted({row["computer"] for row in rows}):
        on_computer = [row for row in rows if row["computer"] == computer]
        scored = any("score" in row for row in on_computer)  # a suite that gives partial credit, such as WebBench
        header = "| Agent | Passed | Mean steps | Mean seconds |" + " Mean score |" * scored
        lines += [f"\n**{computer}**\n", header]
        lines += ["| --- | ---: | ---: | ---: |" + " ---: |" * scored]
        for agent_name in sorted({row["agent"] for row in on_computer}):
            group = [row for row in on_computer if row["agent"] == agent_name]
            passed = [row for row in group if row["passed"]]
            steps = f"{sum(row['steps'] for row in passed) / len(passed):.1f}" if passed else "-"
            seconds = f"{sum(row['seconds'] for row in passed) / len(passed):.1f}" if passed else "-"
            score = f" {sum(row.get('score', 0) for row in group) / len(group):.2f} |" * scored
            lines.append(f"| {agent_name} | {len(passed)}/{len(group)} | {steps} | {seconds} |{score}")
    return "\n".join(lines)


def chosen(value: str, known: list[str], what: str) -> list[str]:
    """Split a comma-separated option and reject names that do not exist."""
    names = value.split(",")
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise SystemExit(f"Unknown {what}: {', '.join(unknown)}. Choose from: {', '.join(known)}")
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite", default="basic", choices=SUITES, help="basic: our ten tasks; the rest: benchmarks")
    parser.add_argument("--tasks", help="comma-separated task names; default is the whole suite")
    parser.add_argument("--agents", default=",".join(AGENTS))
    parser.add_argument("--max-steps", type=int, help="default: each task's own budget")
    parser.add_argument(
        "--settle", type=float, help="seconds our loop waits after each action; default: the computer's"
    )
    parser.add_argument("--model", default="kimi-k3-1-pro", help="name of a Modal Endpoint")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=8, help="Sandboxes to run at once")
    args = parser.parse_args()

    suite = SUITES[args.suite]
    if not suite:
        raise SystemExit(f"The {args.suite} suite has no tasks yet. Download them first: see evals/{args.suite}.py.")
    task_names = chosen(args.tasks, [task.name for task in suite], "tasks") if args.tasks else None
    tasks = [task for task in suite if task_names is None or task.name in task_names]
    agents = chosen(args.agents, list(AGENTS), "agents")
    # Resolved once, up front, so a missing token or endpoint fails before any Sandbox starts.
    model = agent.modal_endpoint(args.model)

    folder = Path("runs") / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True)
    jobs = [
        (task, agent_name, model, folder / f"{task.name}-{agent_name}-{number}")
        for task, agent_name, number in product(tasks, agents, range(1, args.trials + 1))
        if supports(agent_name, task)
    ]
    print(f"Running {len(jobs)} trials with {args.model}, {args.parallel} at a time. Results in {folder}/")
    rows = []
    with ThreadPoolExecutor(args.parallel) as pool:
        options = {"max_steps": args.max_steps, "settle": args.settle}
        for row in pool.map(lambda job: trial(*job, **options), jobs):
            rows.append(row)
            (folder / "results.json").write_text(json.dumps(rows, indent=2))
    (folder / "results.md").write_text(summary(rows) + "\n")
    print(summary(rows))


if __name__ == "__main__":
    main()
