"""A baseline to compare against: the Browser Use library, driving the same browser with the same model."""

import json
from pathlib import Path

from agent import Model
from computers import Browser
from computers.browser import browser_image

SCRIPT = Path(__file__).with_name("browser_use_script.py")


class BrowserWithBrowserUse(Browser):
    """A Browser whose image also has the Browser Use library installed."""

    image = browser_image.uv_pip_install("browser-use==0.13.6").add_local_file(
        SCRIPT, "/opt/browser_use_script.py", copy=True
    )


def drive(browser: Browser, prompt: str, model: Model, max_steps: int) -> int:
    """Run Browser Use inside the Sandbox against the page that is already open. Returns the steps taken."""
    settings = {
        "TASK": f"{prompt} The page is already open in the browser.",
        "MODEL": model.name,
        "BASE_URL": f"{model.url}/v1",
        "API_KEY": model.api_key,
        "REASONING": model.options.get("reasoning_effort", "low"),
        "MAX_STEPS": str(max_steps),
    }
    output = browser.run("python", "/opt/browser_use_script.py", timeout=900, env=settings)
    return json.loads(output.strip().splitlines()[-1])["steps"]
