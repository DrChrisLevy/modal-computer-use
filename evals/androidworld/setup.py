"""Prepare the phone AndroidWorld expects, once, and save it for every trial to start from.

    uv run python -m evals.androidworld.setup

AndroidWorld installs about twenty apps and taps through their first-run screens. This does that in one
Sandbox, switches the phone off so its disk is in a consistent state, takes a filesystem snapshot and
publishes it as a Modal Image named "androidworld-phone".
"""

from computers import Android

from . import PREPARED, SCRIPT, unprepared_image


class UnpreparedPhone(Android):
    image = unprepared_image
    # The Sandbox normally ends when the emulator exits. Here it has to outlive the phone being switched off.
    command = ("bash", "-c", "bash /opt/boot-android.sh; sleep infinity")


if __name__ == "__main__":
    with UnpreparedPhone.create() as phone:
        print(f"Installing AndroidWorld's apps. Watch at {phone.live_view()}")
        phone.sandbox.filesystem.write_text(SCRIPT.read_text(), "/tmp/androidworld.py")
        phone.run("python", "/tmp/androidworld.py", "apps", timeout=3600)
        # Shut down the way the power button does, so Android writes out what it still holds in memory
        # (the permissions just granted, for one). Then wait for the emulator to exit.
        power_off = "adb shell svc power shutdown; while pgrep qemu-system >/dev/null; do sleep 1; done"
        phone.run("bash", "-c", power_off, timeout=300)
        phone.sandbox.snapshot_filesystem(timeout=900, ttl=None).publish(PREPARED)
        print(f"Published the prepared phone as the Image {PREPARED!r}.")
