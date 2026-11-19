"""The calls OSWorldDesktop sends to the guest, checked against a fake OSWorld environment. No VMs."""

import pytest

from evals.osworld.desktop import OSWorldDesktop
from evals.osworld.run import PROMPT, summary


class FakeEnv:
    """Stands in for an OSWorld DesktopEnv: records the Python sent to the guest."""

    def __init__(self, reply=None):
        self.sent = []
        self.controller = self
        self.reply = reply or {"returncode": 0}

    def execute_python_command(self, code):
        self.sent.append(code)
        return self.reply

    def get_screenshot(self):
        return b"png"


def test_actions_become_pyautogui_calls():
    env = FakeEnv()
    desktop = OSWorldDesktop(env)
    desktop.click(10, 20, count=2)
    desktop.drag(1, 2, 3, 4)
    desktop.scroll(5, 6, 600)
    desktop.key("ctrl+S")
    desktop.key("enter")
    desktop.key("ctrl+-")
    assert env.sent == [
        "pyautogui.click(10, 20, clicks=2, interval=0.1, button='left')",
        "pyautogui.moveTo(1, 2); pyautogui.dragTo(3, 4, duration=0.5)",
        "pyautogui.moveTo(5, 6); pyautogui.scroll(-5)",  # pyautogui scrolls down with a negative count
        "pyautogui.hotkey('ctrl', 's')",
        "pyautogui.hotkey('enter')",
        "pyautogui.hotkey('ctrl', '-')",
    ]
    assert desktop.screenshot() == b"png"


def test_text_from_the_model_cannot_become_code_in_the_guest():
    env = FakeEnv()
    desktop = OSWorldDesktop(env)
    desktop.type("it's \"quoted\"\n'); import os #")
    assert env.sent == ['pyautogui.write("it\'s \\"quoted\\"\\n\'); import os #", interval=0.02)']
    for name in ("a'); import os #", "ctrl+", "f1 f2"):
        with pytest.raises(ValueError, match="not a key name"):
            desktop.key(name)
    with pytest.raises(ValueError, match="button must be"):
        desktop.click(1, 1, button="left'); import os #")
    assert len(env.sent) == 1


def test_a_call_the_guest_rejects_is_an_error_the_loop_can_show():
    for reply in (None, {"returncode": 1, "error": "NameError"}):
        with pytest.raises(RuntimeError, match="the guest rejected"):
            OSWorldDesktop(FakeEnv(reply) if reply else FakeEnvNoReply()).move(1, 1)


class FakeEnvNoReply(FakeEnv):
    def execute_python_command(self, code):
        return None


def test_summary_totals_scores_per_domain_and_leaves_out_tasks_that_could_not_be_set_up():
    rows = [
        {"domain": "os", "score": 1.0},
        {"domain": "os", "score": 0.5},
        {"domain": "chrome", "score": 0.0},
        {"domain": "multi_apps", "score": 0.0, "skipped": "could not be set up: no Google Drive credentials"},
    ]
    table = summary(rows)
    assert "| os | 2 | 1.5 |" in table and "| chrome | 1 | 0.0 |" in table and "multi_apps" not in table
    assert "| **all** | 3 | **1.5 (50%)** |" in table
    assert table.endswith("1 more could not be set up.")


def test_the_prompt_gives_the_task_then_the_password_the_step_limit_and_how_to_give_up():
    prompt = PROMPT.format(instruction="Rename {old}.txt to new.txt.", password="secret", max_steps=30)
    assert prompt.startswith("Rename {old}.txt to new.txt.\n")
    assert 'password is "secret"' in prompt and "at most 30 steps" in prompt
    assert "finish with the answer INFEASIBLE" in prompt  # the runner reports FAIL to OSWorld on this answer
