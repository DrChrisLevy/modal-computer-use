"""The eval's bookkeeping: which agent runs which task, and the summary table."""

import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from computers import Android, Browser, Computer, Desktop, action
from evals import miniwob, webbench
from evals.run import chosen, summary, supports, trial
from evals.tasks import Task


def task_on(computer) -> Task:
    return Task("t", computer, "do it", setup=lambda c: None, check=lambda c: True)


def test_agents_only_run_on_computers_they_can_use():
    assert [supports("pixels", task_on(c)) for c in (Browser, Desktop, Android)] == [True, True, True]
    assert [supports("text", task_on(c)) for c in (Browser, Desktop, Android)] == [True, False, True]
    assert [supports("both", task_on(c)) for c in (Browser, Desktop, Android)] == [True, False, True]
    assert [supports("browser-use", task_on(c)) for c in (Browser, Desktop, Android)] == [True, False, False]


def test_summary_groups_by_computer_and_averages_only_passing_trials():
    rows = [
        {"computer": "web browser", "agent": "text", "passed": True, "steps": 4, "seconds": 10.0},
        {"computer": "web browser", "agent": "text", "passed": True, "steps": 6, "seconds": 20.0},
        {"computer": "web browser", "agent": "text", "passed": False, "steps": 25, "seconds": 90.0},
        {"computer": "Linux desktop", "agent": "pixels", "passed": False, "steps": 0, "seconds": 0.0},
    ]
    table = summary(rows)
    assert "**web browser**" in table and "**Linux desktop**" in table
    assert "| text | 2/3 | 5.0 | 15.0 |" in table
    assert "| pixels | 0/1 | - | - |" in table


def test_a_mistyped_task_or_agent_name_stops_the_run():
    assert chosen("signup,shop", ["signup", "shop", "orders"], "tasks") == ["signup", "shop"]
    with pytest.raises(SystemExit, match="Unknown tasks: sign-up"):
        chosen("sign-up", ["signup"], "tasks")


def test_miniwob_lists_125_tasks_and_does_not_let_the_agent_reload_the_page():
    assert len(miniwob.TASKS) == 125 and miniwob.NEED_POSITIONS < set(miniwob.NAMES)
    browser = miniwob.MiniwobBrowser(sandbox=None)
    assert "goto" in Browser(sandbox=None).actions("text")
    assert "goto" not in browser.actions("text") and "click_ref" in browser.actions("text")


def test_a_trial_gives_the_agent_the_written_prompt_unless_the_task_reads_one_off_the_computer(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    class FakeComputer(Computer):
        kind, size = "test computer", (10, 10)
        create = classmethod(lambda cls: cls(sandbox=None))
        terminate = lambda self: None  # noqa: E731
        screenshot = lambda self: b"png"  # noqa: E731

    class FinishesAtOnce:
        grid = None

        def complete(self, system, text, image=None):
            self.prompt = text
            return '{"action": "done", "arguments": {}}'

    written = Task("t", FakeComputer, "the written prompt", setup=lambda c: "what a setup command printed", check=bool)
    model = FinishesAtOnce()
    assert trial(written, "pixels", model, tmp_path, max_steps=3, settle=0)["passed"]
    assert "Task: the written prompt\n" in model.prompt

    read = Task("t", FakeComputer, "", setup=lambda c: None, check=bool, instruction=lambda c: "read off the page")
    trial(read, "pixels", model, tmp_path, max_steps=3, settle=0)
    assert "Task: read off the page\n" in model.prompt


def test_a_check_may_return_a_score_which_the_trial_records_and_the_summary_averages(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    class FakeComputer(Computer):
        kind, size = "test computer", (10, 10)
        create = classmethod(lambda cls: cls(sandbox=None))
        terminate = lambda self: None  # noqa: E731
        screenshot = lambda self: b"png"  # noqa: E731

    model = SimpleNamespace(grid=None, complete=lambda *args: '{"action": "done", "arguments": {}}')
    half = Task("t", FakeComputer, "p", setup=lambda c: None, check=lambda c: {"passed": False, "score": 0.5})
    row = trial(half, "pixels", model, tmp_path, max_steps=3, settle=0)
    assert (row["passed"], row["score"]) == (False, 0.5)
    table = summary([row, row | {"passed": True, "score": 1.0}])
    assert "| Mean seconds | Mean score |" in table and "| pixels | 1/2 | 1.0 | 0.0 | 0.75 |" in table


def test_webbench_keeps_the_answers_out_of_the_sandbox_until_the_agent_is_done(tmp_path):
    folder = tmp_path / "wb-deskops-demo-s0"
    for name in ("environment/hubbench", "environment/webbench", "tests"):
        (folder / name).mkdir(parents=True)
    (folder / "environment" / "task.json").write_text("{}")
    (folder / "environment" / "verifier-token.sha256").write_text("abc123\n")
    (folder / "tests" / "contract.json").write_text("the expected answer")
    manual = '```\nbrowser \'{"action":"read"}\'\n```\nThe reply is the page observation.'
    brief = "Find the event.\n\nOpen http://world:8765/ with the `browser` command."
    (folder / "instruction.md").write_text(f"{brief}\n\n{manual}")

    class FakeBrowser:
        """Records what is uploaded and run, and answers every command with the verifier's verdict."""

        verdict = {"graded": True, "pass": False, "reward": 0.4, "failure_mode": "wrong_record"}
        verdict |= {"gates": [{"id": "containment", "ok": True}]}
        verdict |= {"leaves": [{"id": "answer:event_id", "value": 0.0}, {"id": "answer:decision", "value": 1.0}]}

        def __init__(self):
            self.uploads, self.commands = [], []
            self.sandbox = SimpleNamespace(filesystem=SimpleNamespace(write_bytes=self.upload))

        def upload(self, data, path):
            self.uploads.append(tarfile.open(fileobj=io.BytesIO(data)).getnames())

        def run(self, *argv, env=None):
            self.commands.append(argv[-1])
            return json.dumps(self.verdict)

        goto = lambda self, url: self.commands.append(url)  # noqa: E731

    task = webbench.webbench_task(folder)
    assert task.prompt == "Find the event.\n\nOpen http://world:8765/ in the browser."

    browser = FakeBrowser()
    task.setup(browser)
    assert browser.uploads == [["hubbench", "webbench", "task.json"]]  # the applications, not the answers
    assert "install -d -m 700 /opt/webbench " in browser.commands[0]
    assert "HUBBENCH_VERIFIER_TOKEN_SHA256=abc123" in browser.commands[1] and "--family deskops" in browser.commands[1]
    assert browser.commands[-1] == "http://world:8765/"

    graded = {"passed": False, "score": 0.4, "failure": "wrong_record", "missed": ["answer:event_id"]}
    assert task.check(browser) == graded
    assert "./contract.json" in browser.uploads[-1]
    browser.verdict = {"graded": False, "verifierError": "no database"}
    with pytest.raises(RuntimeError, match="no database"):
        task.check(browser)


def test_a_trial_keeps_to_the_tasks_own_step_budget_and_can_hand_the_check_the_agents_answer(tmp_path, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    class FakeComputer(Computer):
        kind, size = "test computer", (10, 10)
        create = classmethod(lambda cls: cls(sandbox=None))
        terminate = lambda self: None  # noqa: E731
        screenshot = lambda self: b"png"  # noqa: E731
        wait = action(lambda self: None)

    def replies(reply):
        return SimpleNamespace(grid=None, complete=lambda system, text, image=None: reply)

    heard = []
    check = lambda computer, answer: heard.append(answer)  # noqa: E731
    task = Task("t", FakeComputer, "p", setup=lambda c: None, check=check, max_steps=2, wants_answer=True)

    never_done = replies('{"action": "wait", "arguments": {}}')
    assert trial(task, "pixels", never_done, tmp_path, max_steps=None, settle=0)["steps"] == 2
    assert trial(task, "pixels", never_done, tmp_path, max_steps=4, settle=0)["steps"] == 4  # --max-steps wins
    says_42 = replies('{"action": "done", "arguments": {"answer": "42"}}')
    trial(task, "pixels", says_42, tmp_path, max_steps=None, settle=0)
    assert heard == [None, None, "42"]
