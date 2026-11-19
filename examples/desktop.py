"""Start a Linux desktop in a Modal Sandbox and type into a text editor.

uv run python -m examples.desktop
"""

import time

from computers import Desktop

with Desktop.create() as desktop:
    print("Watch it live:", desktop.live_view())
    input("Open the link, then press Enter to start. ")

    desktop.launch("mousepad")
    time.sleep(3)  # give the window a moment to appear
    desktop.type("Hello from a Modal Sandbox.")
    desktop.key("ctrl+a")  # select what we typed

    input("Press Enter to shut the desktop down. ")
