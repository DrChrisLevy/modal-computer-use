"""The loop and the action registry, exercised with a fake computer and a scripted model. No Sandboxes."""

import io
import json
import urllib.error

import pytest

import agent
from agent.loop import parse, to_pixels
from computers import Computer, action


class FakeComputer(Computer):
    kind = "test computer"
    size = (1000, 500)

    def __init__(self):
        self.calls = []

    def screenshot(self) -> bytes:
        return b"png"

    def describe(self) -> str:
        return '[1] button "Go"'

    @action(view="pixels")
    def click(self, x: int, y: int):
        """Click at a point."""
        self.calls.append(("click", x, y))

    @action(view="text")
    def click_ref(self, ref: int):
        """Click a numbered control."""
        if ref != 1:
            raise ValueError(f"No control [{ref}]")
        self.calls.append(("click_ref", ref))

    @action
    def type(self, text: str):
        """Type text."""
        self.calls.append(("type", text))

    @action
    def key(self, name: str):
        """Press a key."""
        self.calls.append(("key", name))

    def not_an_action(self):
        self.calls.append("should never run")


class NoTextView(FakeComputer):
    describe = Computer.describe


class ScriptedModel:
    """Replies with each given decision in turn and records the prompts it was sent."""

    grid = None

    def __init__(self, *decisions):
        self.replies = [d if isinstance(d, str) else json.dumps(d) for d in decisions]
        self.prompts = []

    def complete(self, system, text, image=None):
        self.prompts.append((system, text, image))
        return self.replies.pop(0)


def test_actions_are_filtered_by_view():
    computer = FakeComputer()
    assert set(computer.actions("pixels")) == {"click", "type", "key"}
    assert set(computer.actions("text")) == {"click_ref", "type", "key"}
    assert computer.actions("pixels")["click"] == "click(x: int, y: int) - Click at a point."


def test_act_refuses_methods_that_are_not_offered():
    computer = FakeComputer()
    for name in ("not_an_action", "click_ref", "terminate"):
        with pytest.raises(ValueError, match="Unknown action"):
            computer.act(name, "pixels")
    assert computer.calls == []


def test_loop_runs_actions_until_done():
    computer = FakeComputer()
    model = ScriptedModel(
        {"thought": "press it", "action": "click", "arguments": {"x": 10, "y": 20}},
        {"thought": "finished", "action": "done", "arguments": {"answer": "42"}},
    )
    record = agent.run(computer, "press the button", model, view="pixels", settle=0)
    assert computer.calls == [("click", 10, 20)]
    assert record.answer == "42"
    assert [step.action for step in record.steps] == ["click", "done"]
    system, prompt, image = model.prompts[0]
    assert image == b"png" and '[1] button "Go"' not in prompt
    assert "click(x" in system and "click_ref" not in system


def test_text_view_sends_the_description_and_no_image():
    computer = FakeComputer()
    model = ScriptedModel(
        {"action": "click_ref", "arguments": {"ref": 1}},
        {"action": "done", "arguments": {"answer": ""}},
    )
    agent.run(computer, "press Go", model, view="text", settle=0)
    system, prompt, image = model.prompts[0]
    assert image is None
    assert '[1] button "Go"' in prompt
    assert "click_ref" in system and "click(x" not in system


def test_errors_are_shown_to_the_model_on_its_next_turn():
    computer = FakeComputer()
    model = ScriptedModel(
        "I think I should click.",  # not JSON
        {"action": "click_ref", "arguments": {"ref": 9}},  # the action itself fails
        {"action": "done", "arguments": {"answer": "gave up"}},
    )
    record = agent.run(computer, "press Go", model, view="text", settle=0)
    assert record.steps[0].result.startswith("error: no JSON object")
    assert record.steps[1].result == "error: No control [9]"
    assert "error: No control [9]" in model.prompts[2][1]
    assert record.answer == "gave up"


def test_earlier_thoughts_are_the_models_memory():
    computer = FakeComputer()
    model = ScriptedModel(
        {"thought": "the code is K7Q", "action": "type", "arguments": {"text": "x"}},
        {"action": "done", "arguments": {}},
    )
    agent.run(computer, "remember", model, settle=0)
    assert "the code is K7Q" in model.prompts[1][1]


def test_loop_stops_at_max_steps_without_an_answer():
    model = ScriptedModel(*[{"action": "type", "arguments": {"text": "a"}}] * 3)
    record = agent.run(FakeComputer(), "never ends", model, max_steps=3, settle=0)
    assert len(record.steps) == 3
    assert not record.finished


def test_positions_on_a_grid_are_converted_to_pixels():
    assert to_pixels({"x": 500, "y": 500, "text": "x marks"}, 1000, (1280, 800)) == {
        "x": 640,
        "y": 400,
        "text": "x marks",
    }
    assert to_pixels({"x1": 0, "y1": 1000, "x2": 250, "y2": 0}, 1000, (1000, 500)) == {
        "x1": 0,
        "y1": 500,
        "x2": 250,
        "y2": 0,
    }

    computer = FakeComputer()
    model = ScriptedModel({"action": "click", "arguments": {"x": 500, "y": 500}}, {"action": "done", "arguments": {}})
    model.grid = 1000
    agent.run(computer, "centre", model, settle=0)
    assert computer.calls == [("click", 500, 250)]
    assert "0-1000 grid" in model.prompts[0][0]


def test_parse_tolerates_fences_and_prose():
    assert parse('```json\n{"action": "done"}\n```')["action"] == "done"
    assert parse('Sure! {"action": "type", "arguments": {"text": "{}"}} Done.')["arguments"] == {"text": "{}"}
    with pytest.raises(ValueError):
        parse('{"thought": "no action here"}')


def test_a_reply_with_no_text_or_bad_arguments_is_a_failed_step_not_a_crash():
    model = ScriptedModel("", {"action": "done", "arguments": "42"}, {"action": "done", "arguments": {"answer": "ok"}})
    record = agent.run(FakeComputer(), "survive", model, settle=0)
    assert [step.failed for step in record.steps] == [True, True, False]
    assert record.answer == "ok"


def test_the_run_is_returned_when_the_model_or_the_screen_keeps_failing():
    class DeadModel(ScriptedModel):
        def complete(self, system, text, image=None):
            raise OSError("connection reset")

    record = agent.run(FakeComputer(), "unreachable", DeadModel(), settle=0)
    assert [step.result for step in record.steps] == ["error: connection reset"] * 3  # gives up after three in a row
    assert not record.finished

    class BlankScreen(FakeComputer):
        def screenshot(self) -> bytes:
            raise RuntimeError("scrot exited 1")

    record = agent.run(BlankScreen(), "unreadable", ScriptedModel(), settle=0)
    assert len(record.steps) == 3


def test_asking_for_a_view_the_computer_lacks_raises_immediately():
    with pytest.raises(NotImplementedError, match="has no text view"):
        agent.run(NoTextView(), "read", ScriptedModel(), view="text", settle=0)


def test_the_model_is_told_what_kind_of_computer_it_operates():
    model = ScriptedModel({"action": "done", "arguments": {}})
    agent.run(FakeComputer(), "anything", model, settle=0)
    assert model.prompts[0][0].startswith("You operate a test computer")


def test_replay_survives_script_tags_in_recorded_text(tmp_path):
    model = ScriptedModel({"thought": "the page says </script><b>hi", "action": "done", "arguments": {}})
    page = agent.replay.save(agent.run(FakeComputer(), "replay", model, settle=0), tmp_path)
    html = page.read_text()
    assert html.count("</script>") == 1  # only the page's own closing tag
    assert (tmp_path / "01.png").read_bytes() == b"png"
    assert json.loads((tmp_path / "steps.json").read_text())["steps"][0]["thought"].endswith("<b>hi")


def test_an_action_may_have_an_argument_called_name_or_view():
    computer = FakeComputer()
    computer.act("key", "pixels", name="Return")
    assert computer.calls == [("key", "Return")]


def test_the_both_view_sends_the_screenshot_and_the_text_and_offers_either_kind_of_action():
    computer = FakeComputer()
    model = ScriptedModel(
        {"action": "click_ref", "arguments": {"ref": 1}},
        {"action": "click", "arguments": {"x": 5, "y": 6}},
        {"action": "done", "arguments": {}},
    )
    agent.run(computer, "press Go", model, view="both", settle=0)
    system, prompt, image = model.prompts[0]
    assert image == b"png" and '[1] button "Go"' in prompt
    assert "click_ref" in system and "click(x" in system
    assert computer.calls == [("click_ref", 1), ("click", 5, 6)]


def test_a_saved_run_continues_where_it_stopped():
    computer = FakeComputer()
    first = ScriptedModel({"thought": "the code is K7Q", "action": "type", "arguments": {"text": "a"}})
    saved = agent.run(computer, "two steps", first, max_steps=1, settle=0).to_json()

    second = ScriptedModel({"action": "done", "arguments": {"answer": "K7Q"}})
    record = agent.resume(computer, agent.Run.from_json(saved), second, settle=0)
    assert [step.action for step in record.steps] == ["type", "done"]
    assert "the code is K7Q" in second.prompts[0][1]  # the new process knows what the old one noted
    assert record.answer == "K7Q"


def test_asking_the_user_pauses_the_run_until_it_is_resumed_with_a_reply():
    computer = FakeComputer()
    model = ScriptedModel(
        {"action": "ask_user", "arguments": {"question": "Which email?"}},
        {"action": "done", "arguments": {"answer": "sent"}},
    )
    record = agent.run(computer, "email them", model, can_ask=True, settle=0)
    assert record.question == "Which email?" and not record.finished
    assert len(model.prompts) == 1  # paused: the model is not asked again

    agent.resume(computer, record, model, reply="ada@example.com", can_ask=True, settle=0)
    assert "the user replied: ada@example.com" in model.prompts[1][1]
    assert record.question is None and record.answer == "sent"


def test_asking_the_user_is_only_possible_when_it_is_offered():
    model = ScriptedModel({"action": "ask_user", "arguments": {"question": "?"}}, {"action": "done", "arguments": {}})
    record = agent.run(FakeComputer(), "no questions", model, settle=0)
    assert "ask_user" not in model.prompts[0][0]
    assert record.steps[0].result.startswith("error: Unknown action") and record.question is None


def test_stop_ends_the_run_before_the_next_step():
    computer = FakeComputer()
    model = ScriptedModel(*[{"action": "type", "arguments": {"text": "a"}}] * 5)
    record = agent.run(computer, "until told", model, stop=lambda: len(computer.calls) == 2, settle=0)
    assert len(record.steps) == 2 and not record.finished


def test_the_model_client_asks_the_server_for_a_json_reply_unless_told_otherwise(monkeypatch):
    sent = []

    def urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    agent.Model("m", "https://example.invalid", "key").complete("system", "hi")
    agent.Model("m", "https://example.invalid", "key", options={"response_format": None}).complete("system", "hi")
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert sent[1]["response_format"] is None


def test_the_model_client_waits_and_retries_when_the_server_is_busy(monkeypatch):
    replies = [503, 429, {"choices": [{"message": {"content": "hello"}}]}, 500]
    waits = []

    def urlopen(request, timeout):
        reply = replies.pop(0)
        if isinstance(reply, int):
            raise urllib.error.HTTPError(request.full_url, reply, "busy", {}, None)
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("time.sleep", waits.append)
    model = agent.Model("m", "https://example.invalid", "key")
    assert model.complete("system", "hi") == "hello"
    assert waits == [2, 5]
    with pytest.raises(urllib.error.HTTPError):  # any other error is not retried
        model.complete("system", "hi")


def test_the_pause_after_an_action_is_the_computers_own_unless_one_is_given(monkeypatch):
    waits = []
    monkeypatch.setattr("time.sleep", waits.append)

    class SlowScreen(FakeComputer):
        settle = 0.7

    steps = [{"action": "type", "arguments": {"text": "a"}}, {"action": "done", "arguments": {}}]
    agent.run(SlowScreen(), "wait for it", ScriptedModel(*steps))
    agent.run(SlowScreen(), "hurry", ScriptedModel(*steps), settle=0.1)
    assert waits == [0.7, 0.1]


def test_the_default_view_is_both_where_the_computer_has_a_text_view():
    model = ScriptedModel({"action": "done", "arguments": {}})
    agent.run(FakeComputer(), "look", model, settle=0)
    system, prompt, image = model.prompts[0]
    assert image == b"png" and '[1] button "Go"' in prompt
    assert "click_ref" in system and "click(x" in system


def test_the_default_view_is_pixels_where_the_computer_has_no_text_view():
    model = ScriptedModel({"action": "done", "arguments": {}})
    agent.run(NoTextView(), "look", model, settle=0)
    system, prompt, image = model.prompts[0]
    assert image == b"png" and "(attached)" in prompt
    assert "click(x" in system and "click_ref" not in system
