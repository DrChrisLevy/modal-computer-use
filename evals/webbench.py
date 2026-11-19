"""WebBench: long tasks across simulated office applications, graded by code against their database.

The tasks are Blobfish AI's `blobfishai/webbench` dataset in Harbor's registry. Download it once:

    uv run --with "harbor[modal]==0.26.0" harbor datasets download blobfishai/webbench -o runs/webbench

Each task ships its applications (one standard-library Python web server over a SQLite database) and a
verifier. Harbor runs them as two Docker containers. Here the server runs inside the Browser's own
Sandbox as root, where Chromium (which runs as the user `agent`) cannot read its files, and the verifier
with its expected answers is only uploaded once the agent has finished.
"""

import io
import json
import os
import tarfile
from pathlib import Path

from computers import Browser

from .browser_use import BrowserWithBrowserUse
from .tasks import Task

ROOT = Path(os.environ.get("WEBBENCH", "runs/webbench/webbench"))  # where the download command above puts the tasks
SITE = "http://world:8765"  # the address the instructions use; `world` is pointed at the Sandbox itself
WORLD, TESTS = "/opt/webbench", "/opt/webbench-tests"  # both readable by root only
SERVE = (
    "grep -q world /etc/hosts || echo '127.0.0.1 world' >> /etc/hosts; cd {world} && "
    "(HUBBENCH_VERIFIER_TOKEN_SHA256={digest} nohup python -m webbench.engine.world_service --family {family} "
    "--task task.json --db /var/lib/webbench/world.db --fresh --port 8765 --private-port 8766 >/tmp/world.log 2>&1 &)"
    " && until (echo >/dev/tcp/127.0.0.1/8765) 2>/dev/null; do sleep 0.1; done"
)
# The verifier fetches the finished database from the server's private port and writes its verdict as JSON.
VERIFY = f"python {TESTS}/verify.py >/dev/null; cat /tmp/verdict/verdict.json"
VERIFY_ENV = {"WEBBENCH_VERIFIER_URL": "http://127.0.0.1:8766", "WEBBENCH_LOGS_DIR": "/tmp/verdict"}


def upload(browser: Browser, folder: Path, names: list[str], target: str) -> None:
    """Copy the named entries of a local folder into a directory in the Sandbox that only root can read."""
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name in names:
            tar.add(folder / name, arcname=name)
    browser.sandbox.filesystem.write_bytes(archive.getvalue(), "/tmp/upload.tgz")
    unpack = f"tar -xzf /tmp/upload.tgz --no-overwrite-dir -C {target}"  # the directory keeps its own permissions
    browser.run("bash", "-c", f"install -d -m 700 {target} && {unpack} && rm /tmp/upload.tgz")


def instruction(folder: Path) -> str:
    """The task as the benchmark words it, without the manual for the benchmark's own browser tool."""
    text = (folder / "instruction.md").read_text().split("```")[0].strip()
    return text.replace(" with the `browser` command", " in the browser")


def webbench_task(folder: Path) -> Task:
    family = folder.name.split("-")[1]  # wb-<family>-..., one of deskops, itsmdesk, workplace

    def setup(browser: Browser) -> None:
        upload(browser, folder / "environment", ["hubbench", "webbench", "task.json"], WORLD)
        digest = (folder / "environment" / "verifier-token.sha256").read_text().strip()
        browser.run("bash", "-c", SERVE.format(world=WORLD, digest=digest, family=family))
        browser.goto(f"{SITE}/")

    def check(browser: Browser) -> dict:
        upload(browser, folder / "tests", ["."], TESTS)
        verdict = json.loads(browser.run("bash", "-c", VERIFY, env=VERIFY_ENV))
        if not verdict.get("graded", True):
            raise RuntimeError(f"the verifier could not grade the run: {verdict.get('verifierError')}")
        missed = [gate["id"] for gate in verdict["gates"] if not gate["ok"]]
        missed += [leaf["id"] for leaf in verdict["leaves"] if leaf["value"] < 1]
        return {
            "passed": bool(verdict["pass"]),
            "score": verdict["reward"],  # WebScore: partial credit, from 0 to 1
            "failure": verdict.get("failure_mode"),  # the verifier's own label for what went wrong, if it has one
            "missed": missed,  # the checks that did not get full marks, such as "answer:event_id"
        }

    return Task(folder.name, BrowserWithBrowserUse, instruction(folder), setup, check, max_steps=100)


# The first three variants of each task template: 42 of the dataset's 159 tasks. Empty until it is downloaded.
TASKS = [webbench_task(folder) for folder in sorted(ROOT.glob("wb-*-s[012]"))]
