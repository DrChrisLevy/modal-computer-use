"""Start a browser in a Modal Sandbox, read a page as text, and click a link.

uv run python -m examples.browser
"""

import time

from computers import Browser

with Browser.create() as browser:
    print("Watch it live:", browser.live_view())
    browser.goto("https://example.com")
    input("Open the link, then press Enter to start. ")

    print(browser.describe())  # the page as text, with its controls numbered
    browser.click_ref(1)  # the only link on the page
    time.sleep(2)  # give the next page a moment to load
    print(browser.describe().splitlines()[0])

    input("Press Enter to shut the browser down. ")
