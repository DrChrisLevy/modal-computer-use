"""Runs inside the Sandbox: a tiny Chrome DevTools Protocol client for the Chromium on port 9222.

python cdp.py ready             wait until the browser has a page open
python cdp.py goto <url>        load a URL and wait for it to finish loading
python cdp.py eval <javascript> evaluate an expression in the page and print the result as JSON
"""

import json
import sys
import time
import urllib.request

from websockets.sync.client import connect


def page_socket_url() -> str:
    with urllib.request.urlopen("http://127.0.0.1:9222/json") as response:
        targets = json.load(response)
    return next(target["webSocketDebuggerUrl"] for target in targets if target["type"] == "page")


def send(socket, method: str, **params) -> dict:
    """Send one command and return its result, skipping the events that arrive in between."""
    socket.send(json.dumps({"id": 1, "method": method, "params": params}))
    while True:
        message = json.loads(socket.recv(timeout=30))
        if message.get("id") == 1:
            if "error" in message:
                sys.exit(message["error"]["message"])
            return message["result"]


def ready() -> None:
    deadline = time.monotonic() + 30
    while True:
        try:
            page_socket_url()
            return
        except (OSError, StopIteration):
            if time.monotonic() > deadline:
                sys.exit("Chromium did not open a page within 30 seconds")
            time.sleep(0.2)


def goto(url: str) -> None:
    with connect(page_socket_url()) as socket:
        send(socket, "Page.enable")
        error = send(socket, "Page.navigate", url=url).get("errorText")
        if error:
            sys.exit(f"Could not load {url}: {error}")
        while json.loads(socket.recv(timeout=30)).get("method") != "Page.loadEventFired":
            pass


def evaluate(javascript: str) -> None:
    with connect(page_socket_url()) as socket:
        result = send(socket, "Runtime.evaluate", expression=javascript, returnByValue=True, awaitPromise=True)
    if "exceptionDetails" in result:
        sys.exit(result["exceptionDetails"]["exception"].get("description", "JavaScript error"))
    print(json.dumps(result["result"].get("value")))


if __name__ == "__main__":
    {"ready": ready, "goto": goto, "eval": evaluate}[sys.argv[1]](*sys.argv[2:])
