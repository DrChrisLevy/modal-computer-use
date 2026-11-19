"""The commands Desktop and Browser send, checked with a `run` that records instead of executing."""

import json

import pytest

from computers import Browser, Desktop


class Recorder:
    """Mixed into a computer to capture the commands it would run in the Sandbox."""

    def __init__(self, replies=()):
        self.commands = []
        self.replies = list(replies)

    def run(self, *argv, timeout=60, binary=False, env=None):
        self.commands.append(argv)
        return self.replies.pop(0) if self.replies else ""


class RecordingDesktop(Recorder, Desktop):
    pass


class RecordingBrowser(Recorder, Browser):
    pass


def test_click_and_drag_are_single_xdotool_calls_without_sync():
    desktop = RecordingDesktop()
    desktop.click(10, 20, button="right", count=2)
    desktop.drag(1, 2, 3, 4)
    assert desktop.commands == [
        ("xdotool", "mousemove", 10, 20, "click", "--repeat", 2, 3),
        ("xdotool", "mousemove", 1, 2, "mousedown", 1, "mousemove", 3, 4, "mouseup", 1),
    ]


def test_click_rejects_an_unknown_button_with_an_error_the_loop_can_show():
    with pytest.raises(ValueError, match="left, middle, right"):
        RecordingDesktop().click(10, 20, button="double")


def test_scroll_converts_pixels_to_wheel_turns_and_caps_them():
    desktop = RecordingDesktop()
    desktop.scroll(5, 5, 600)
    desktop.scroll(5, 5, -30)
    desktop.scroll(5, 5, 1_000_000)
    turns_and_wheel = [(command[6], command[9]) for command in desktop.commands]
    assert turns_and_wheel == [(5, 5), (1, 4), (50, 5)]  # wheel button 5 scrolls down, 4 up


def test_typed_text_is_passed_as_one_argument_after_a_double_dash():
    desktop = RecordingDesktop()
    desktop.type("--help; rm -rf /")
    assert desktop.commands[0][-2:] == ("--", "--help; rm -rf /")


def test_fill_clicks_the_located_control_clears_it_and_types():
    browser = RecordingBrowser(replies=[json.dumps([300, 200])])
    browser.fill(4, "")
    assert [command[:2] for command in browser.commands] == [
        ("python", "/opt/cdp.py"),  # find control [4] on the page
        ("xdotool", "mousemove"),  # click it
        ("xdotool", "key"),  # select all
        ("xdotool", "key"),  # delete, so an empty string really clears the field
        ("xdotool", "type"),
    ]
    assert browser.commands[1][2:4] == (300, 200)


def test_a_control_number_that_is_not_on_the_page_is_an_error():
    browser = RecordingBrowser(replies=["null"])
    with pytest.raises(ValueError, match=r"No control \[7\]"):
        browser.click_ref(7)
    with pytest.raises(ValueError, match="no option 'Gold'"):
        RecordingBrowser(replies=["false"]).select(2, "Gold")
