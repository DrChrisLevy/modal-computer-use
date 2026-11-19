"""How Android turns a UI dump into numbered elements, and what it sends to adb. No emulator needed."""

import pytest

from computers import Android

DUMP = """UI hierchary dumped to: /dev/tty
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node class="android.widget.FrameLayout" text="" clickable="false" bounds="[0,0][1080,2400]">
    <node class="android.widget.TextView" text="Settings" clickable="false" bounds="[40,100][400,200]" />
    <node class="android.widget.LinearLayout" text="" clickable="true" bounds="[0,300][1080,500]">
      <node class="android.widget.TextView" text="Battery" clickable="false" bounds="[100,320][500,400]" />
    </node>
    <node class="android.widget.ImageButton" text="" resource-id="com.android.settings:id/search"
          clickable="true" bounds="[900,100][1000,200]" />
    <node class="android.widget.Switch" text="Airplane mode" checkable="true" checked="false"
          clickable="true" bounds="[0,600][1080,800]" />
  </node>
</hierarchy>"""


class CannedAndroid(Android):
    """An Android whose adb returns a fixed UI dump and records what it was asked to do."""

    def __init__(self, dumps=(DUMP,)):
        self.dumps = list(dumps)
        self.commands = []

    def adb(self, *argv, binary=False):
        self.commands.append(argv)
        return self.dumps.pop(0) if len(self.dumps) > 1 else self.dumps[0]


def test_describe_numbers_everything_with_a_label():
    assert CannedAndroid().describe().splitlines() == [
        '[1] TextView "Settings"',
        '[2] TextView "Battery"',  # its clickable row has no label of its own, so only the text is listed
        '[3] ImageButton "search"',  # an unlabelled icon button falls back to its resource id
        '[4] Switch "Airplane mode" (off)',  # switches show their state
    ]


def test_describe_retries_once_while_the_screen_is_still_changing():
    phone = CannedAndroid(["ERROR: could not get idle state.", DUMP])
    assert phone.describe().startswith('[1] TextView "Settings"')


def test_a_screen_that_never_holds_still_is_described_as_unreadable_and_has_no_numbers():
    phone = CannedAndroid()
    phone.describe()
    phone.dumps = ["ERROR: could not get idle state."]
    assert phone.describe() == "(Something on the screen keeps moving, so it cannot be read as text.)"
    with pytest.raises(ValueError, match=r"No element \[1\]"):
        phone.click_ref(1)


def test_click_ref_taps_the_element_the_model_was_shown():
    phone = CannedAndroid()
    phone.describe()
    phone.dumps = ["<hierarchy></hierarchy>"]  # the screen has changed since; the numbers must not shift
    phone.click_ref(2)
    assert phone.commands[-1] == ("shell", "input", "tap", 300, 360)


def test_click_ref_rejects_numbers_that_were_not_in_the_description():
    phone = CannedAndroid()
    with pytest.raises(ValueError, match=r"No element \[1\]"):
        phone.click_ref(1)  # nothing has been described yet
    phone.describe()
    with pytest.raises(ValueError, match=r"No element \[9\]"):
        phone.click_ref(9)


def test_model_supplied_values_cannot_reach_the_phone_shell_unquoted():
    phone = CannedAndroid()
    phone.type("it's 5 o'clock; reboot")
    assert phone.commands[-1] == ("shell", "input", "text", "'it'\"'\"'s%s5%so'\"'\"'clock;%sreboot'")
    with pytest.raises(ValueError, match="not a key name"):
        phone.key("ENTER; reboot")
    with pytest.raises(ValueError):
        phone.click("10; reboot", 20)
    phone.key("back")
    assert phone.commands[-1] == ("shell", "input", "keyevent", "KEYCODE_BACK")


def test_a_swipe_moves_a_finger_across_the_middle_of_the_screen():
    phone = CannedAndroid()
    phone.swipe("up")
    assert phone.commands[-1] == ("shell", "input", "swipe", 540, 1680, 540, 720, 300)
    phone.swipe("right")
    assert phone.commands[-1] == ("shell", "input", "swipe", 216, 1200, 864, 1200, 300)
    with pytest.raises(ValueError, match="up, down, left or right"):
        phone.swipe("north")


def test_a_long_press_holds_a_finger_on_one_point_for_a_second():
    phone = CannedAndroid()
    phone.click(100, 200, hold=True)
    assert phone.commands[-1] == ("shell", "input", "swipe", 100, 200, 100, 200, 1000)
    phone.describe()
    phone.click_ref(2, hold=True)
    assert phone.commands[-1] == ("shell", "input", "swipe", 300, 360, 300, 360, 1000)


def test_typing_can_empty_the_field_first():
    phone = CannedAndroid()
    phone.type("new", clear=True)
    assert phone.commands == [
        ("shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A"),
        ("shell", "input", "keyevent", "KEYCODE_DEL"),
        ("shell", "input", "text", "new"),
    ]


APPS = """com.android.settings/.Settings
com.google.android.deskclock/com.android.deskclock.DeskClock
com.google.android.calendar/com.android.calendar.AllInOneActivity
com.simplemobiletools.calendar.pro/.activities.SplashActivity$Orange
"""


def test_open_app_starts_the_one_app_whose_package_or_activity_has_every_word_of_the_name():
    phone = CannedAndroid([APPS])
    phone.open_app("Clock")
    assert phone.commands[-1] == (
        "shell",
        "am",
        "start",
        "-n",
        "com.google.android.deskclock/com.android.deskclock.DeskClock",
    )
    phone.open_app("Simple Calendar Pro")  # quoted, because the phone's shell would expand $Orange
    assert phone.commands[-1][-1] == "'com.simplemobiletools.calendar.pro/.activities.SplashActivity$Orange'"
    phone.open_app("com.android.settings")
    assert phone.commands[-1][-1] == "com.android.settings/.Settings"


def test_open_app_names_the_choices_when_the_name_fits_several_apps_or_none():
    phone = CannedAndroid([APPS])
    with pytest.raises(
        ValueError, match="Choose from: com.google.android.calendar, com.simplemobiletools.calendar.pro$"
    ):
        phone.open_app("Calendar")
    with pytest.raises(ValueError, match="'Files; reboot' does not name one app. Choose from: com.android.settings, "):
        phone.open_app("Files; reboot")
    assert not any("start" in command for command in phone.commands)
