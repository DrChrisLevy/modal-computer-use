"""Boot an Android phone in a Modal Sandbox, open Settings, and read the screen as text.

Needs a workspace with nested virtualization (Enterprise). Booting takes about a minute.

uv run python -m examples.android
"""

import time

from computers import Android

with Android.create() as phone:
    print("Watch it live:", phone.live_view())
    input("Open the link, then press Enter to start. ")

    phone.adb("shell", "am", "start", "-a", "android.settings.SETTINGS")
    time.sleep(2)
    phone.swipe("up")
    time.sleep(1)
    print(phone.describe())  # the screen as text, with its elements numbered

    input("Press Enter to shut the phone down. ")
