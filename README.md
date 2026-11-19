# Computer use on Modal Sandboxes

Small classes that turn a Modal Sandbox into a computer an AI agent can use: a web browser, a Linux
desktop, or an Android phone. The only dependency is `modal`.

[The blog post](blog/post.md) walks through how it works. The code is short enough to read in one
sitting or to hand to a coding agent: start with `computers/base.py` and `agent/loop.py`.

| Folder | What is in it |
| --- | --- |
| `computers/` | `Desktop`, `Browser` and `Android`, built on one `Computer` base class |
| `agent/` | the agent loop and the model client |
| `examples/` | five short scripts to try by hand |
| `evals/` | tasks and benchmarks, with Browser Use as a baseline |

## Setup

```sh
uv sync
uv run modal setup          # once, if you have not authenticated
export MODAL_ENVIRONMENT=your-environment
```

The agent and the evals call a model on a [Modal Endpoint](https://modal.com/docs/guide/endpoints) named
`kimi-k3-1-pro`, and read a proxy token from `MODAL_PROXY_TOKEN_ID` and `MODAL_PROXY_TOKEN_SECRET`.
`Android` needs nested virtualization, which Modal offers to Enterprise workspaces.

## Use a computer

```python
from computers import Browser

with Browser.create() as browser:  # starts a Sandbox
    print(browser.live_view())  # a private link to watch it
    browser.goto("https://example.com")
    png = browser.screenshot()  # what a vision model looks at
    browser.click(640, 400)  # what it does next
    print(browser.describe())  # or read the page as text ...
    browser.click_ref(1)  # ... and click a control by its number
```

`Desktop` and `Android` work the same way. Try each one:

```sh
uv run python -m examples.desktop
uv run python -m examples.browser
uv run python -m examples.android            # boots in about a minute
uv run python -m examples.android_snapshot   # boot one phone, then start copies of it in seconds
```

## Let an agent use it

```python
import agent
from computers import Browser

model = agent.modal_endpoint("kimi-k3-1-pro")

with Browser.create() as browser:
    result = agent.run(browser, "Go to modal.com, open the Pricing page, and tell me its main headline.", model)
    print(result.answer)
```

`agent.run` shows the model the screen, asks it for one action, runs that action, and repeats until the
model says it is done. `view=` sets what the model sees: `"pixels"` (a screenshot), `"text"` (the screen as
text with numbered controls), or `"both"`. The default is `"both"` on the browser and Android, and
`"pixels"` on the desktop, which has no text view.

To give a computer one task after another from your terminal and watch it work:

```sh
uv run python -m examples.chat
uv run python -m examples.chat --computer android
```

## Evals

```sh
uv run python -m evals.run --trials 3            # ten small tasks across the three computers
uv run python -m evals.run --suite miniwob       # MiniWoB++, 125 small browser tasks
uv run python -m evals.run --suite webbench      # WebBench, 42 long browser tasks; needs a download, see evals/webbench.py
uv run python -m evals.run --suite androidworld  # AndroidWorld, 116 phone tasks; first run evals.androidworld.setup once
```

OSWorld, 36 desktop tasks, runs from a checkout of OSWorld with its own Python: see `evals/osworld/run.py`.

Every trial gets a fresh Sandbox, and a check reads the computer's real state (the page, a file, a phone
setting) and never trusts the agent's own claim. Results and a replay of each run land in `runs/`.

Results with Kimi K3.1 Pro, as trials passed. The first three columns are this repo's loop with each
view. The last is [Browser Use](https://github.com/browser-use/browser-use) 0.13.6 with the same model, in
the same Sandbox. Browser Use is about 64,000 lines of Python; `computers/` and `agent/` together are
about 1,000.

| Tasks | Pixels | Text | Both | Browser Use |
| --- | ---: | ---: | ---: | ---: |
| Browser, 5 small tasks, 3 trials each | 15/15 | 15/15 | 15/15 | 15/15 |
| Desktop, 2 small tasks, 3 trials each | 6/6 | - | - | - |
| Android, 3 small tasks, 3 trials each | 9/9 | 9/9 | 9/9 | - |
| MiniWoB++, 125 small browser tasks | 117/125 | 76/125 | 117/125 | 114/125 |
| WebBench, 42 long browser tasks | 18/42 | 28/42 | 26/42 | 33/42 |
| AndroidWorld, 116 phone tasks | 82/116 | 58/116 | 90/116 | - |
| OSWorld, 36 desktop tasks | 30/36 | - | - | - |

A dash means there is nothing to run: the desktop has no text view, and Browser Use only drives a
browser. On the small tasks the short loop matches Browser Use. On WebBench, where a task takes 35 to 70
steps, Browser Use is ahead. OSWorld gives partial credit, so its row is a total score; OSWorld's own
Kimi agent scored 32 on the same tasks.

## To do (maybe)

- **A faster control path.** Every action is one `Sandbox.exec`, about 100 ms from a laptop. A small
  server kept running in the Sandbox cut that to about 33 ms in a test. `Computer.run` is the one method
  to replace.
- **One action to click and type, for the pixels view.** A form field costs two steps today.
- **A text view that scrolls.** `describe()` cuts page text off at 12,000 characters.
