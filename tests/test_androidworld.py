"""The AndroidWorld suite: what it runs inside the Sandbox and how it turns the answer into pass or fail."""

import json
from types import SimpleNamespace

import pytest

from computers import Android
from evals import androidworld


class CannedPhone(Android):
    """An Android that records what it is asked to run and what is written to it, and replies with a fixed score."""

    def __init__(self, score: float = 1.0):
        self.score, self.commands, self.written = score, [], {}
        self.sandbox = SimpleNamespace(filesystem=SimpleNamespace(write_text=self.write_text))

    def write_text(self, text: str, path: str) -> None:
        self.written[path] = text

    def run(self, *argv, timeout=60, binary=False, env=None):
        self.commands.append(argv[-1])
        if "goal.json" in argv[-1]:
            return '{"goal": "Add a contact named Ada."}'
        return json.dumps({"score": self.score}) if "score.json" in argv[-1] else ""


def test_the_suite_is_the_116_tasks_with_androidworlds_own_step_budgets():
    by_name = {task.name: task for task in androidworld.TASKS}
    assert len(by_name) == 116
    assert by_name["ContactsAddContact"].max_steps == 12 and by_name["OsmAndTrack"].max_steps == 120
    assert all(task.computer is androidworld.AndroidWorldPhone and task.wants_answer for task in by_name.values())


def test_a_task_is_prepared_and_scored_by_androidworlds_code_inside_the_sandbox():
    task, phone = androidworld.androidworld_task("ContactsAddContact"), CannedPhone()
    task.setup(phone)
    assert "from android_world import registry" in phone.written["/tmp/androidworld.py"]
    assert f"python /tmp/androidworld.py task ContactsAddContact {androidworld.SEED} " in phone.commands[0]
    assert task.instruction(phone) == "Add a contact named Ada."
    assert task.check(phone, "It is 42.")
    assert phone.written["/tmp/androidworld/answer.txt"] == "It is 42."  # question tasks are scored on the answer


def test_a_failure_inside_the_sandbox_is_raised_with_androidworlds_traceback():
    phone = CannedPhone()
    phone.run = lambda *argv, **options: '{"error": "KeyError: no such task"}'
    with pytest.raises(RuntimeError, match="no such task"):
        androidworld.reply(phone, "goal.json")


def test_a_task_passes_only_if_the_phone_is_right_and_the_agent_said_it_was_done():
    task = androidworld.androidworld_task("ContactsAddContact")
    assert task.check(CannedPhone(score=1.0), "")
    assert not task.check(CannedPhone(score=1.0), None)  # ran out of steps without calling done
    assert not task.check(CannedPhone(score=0.0), "done")
    assert not task.check(CannedPhone(score=0.5), "done")  # half of a two-part task
