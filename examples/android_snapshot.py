"""Boot an Android phone once, then start copies of it in a few seconds.

Android takes about a minute to boot. A memory snapshot of the booted Sandbox skips that: a new
Sandbox restored from it has the phone already on, exactly as it was, so every eval trial can begin
from the same screen. The phone answers adb within a second and the first screenshot takes a few more.

Memory snapshots are an alpha feature. Taking one ends the original Sandbox, a snapshot expires
after 7 days, and it restores only onto the kind of machine it was taken on.

    uv run python -m examples.android_snapshot
"""

import time
from pathlib import Path

import modal

from computers import Android

started = time.monotonic()
phone = Android.create(_experimental_enable_snapshot=True)  # the one slow boot
print(f"Booted a phone in {time.monotonic() - started:.0f} seconds")
phone.key("HOME")  # whatever is on screen now is what every copy starts with
time.sleep(1)
booted = phone.sandbox._experimental_snapshot()  # ends that Sandbox
print("Snapshot:", booted.object_id, "(modal.SandboxSnapshot.from_id finds it again later)")

for trial in range(3):
    started = time.monotonic()
    with Android(modal.Sandbox._experimental_from_snapshot(booted)) as copy:
        png = copy.screenshot()
        print(f"Copy {trial + 1} showed its screen after {time.monotonic() - started:.1f} seconds")
        # The phone's clock stopped when the snapshot was taken. Android catches up on its own after
        # some seconds; this makes it fetch the time now.
        copy.adb("shell", "cmd", "network_time_update_service", "force_refresh")

Path("android-copy.png").write_bytes(png)
print("Saved android-copy.png")
