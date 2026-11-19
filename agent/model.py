"""Talk to a chat model over the OpenAI-compatible API, using only the standard library."""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import modal

BUSY_WAITS = (2, 5, 15)  # seconds to wait before each retry when the server says it is busy (HTTP 429 or 503)


@dataclass(frozen=True)
class Model:
    name: str  # the model id sent in each request
    url: str  # the server's base URL, without /v1
    api_key: str
    options: dict = field(default_factory=dict)  # extra request fields, such as reasoning_effort
    grid: int | None = None  # set to 1000 for models that give positions on a 0-1000 grid, not in pixels

    def complete(self, system: str, text: str, image: bytes | None = None) -> str:
        """Send one user turn, optionally with a PNG, and return the model's reply."""
        content = [{"type": "text", "text": text}]
        if image:
            data = base64.b64encode(image).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}})
        payload = {
            "model": self.name,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            # The loop asks for one JSON object, and this has the server hold the model to it.
            # Left to itself, Kimi sometimes answers in its own tool-call syntax.
            "response_format": {"type": "json_object"},
            **self.options,
        }
        request = urllib.request.Request(
            f"{self.url}/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        for wait in (*BUSY_WAITS, None):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    # A reply that is all reasoning has no content; treat it as empty text.
                    return json.load(response)["choices"][0]["message"]["content"] or ""
            except urllib.error.HTTPError as error:
                if error.code not in (429, 503) or wait is None:
                    raise
                time.sleep(wait)


# Settings for models on Modal Endpoints, from measuring where each one says known targets are.
# Kimi and GLM answer in screenshot pixels (within about 3 px); Qwen and Gemma answer on a 0-1000 grid.
ENDPOINTS = {
    "kimi-k3-1-pro": {"options": {"reasoning_effort": "low"}},
    "glm-5-3-flash": {},
    "qwen3-8-max-vl": {"grid": 1000, "options": {"reasoning_effort": "none"}},
    "gemma-4-31b-it": {"grid": 1000},
}


def modal_endpoint(name: str) -> Model:
    """A model served by a Modal Endpoint in the current environment, such as "kimi-k3-1-pro".

    Authenticates with the proxy token in MODAL_PROXY_TOKEN_ID and MODAL_PROXY_TOKEN_SECRET.
    """
    url = modal.Server.from_name(f"ep-{name}", "Server").get_url()
    api_key = f"{os.environ['MODAL_PROXY_TOKEN_ID']}.{os.environ['MODAL_PROXY_TOKEN_SECRET']}"
    request = urllib.request.Request(f"{url}/v1/models", headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=60) as response:
        model_id = json.load(response)["data"][0]["id"]
    return Model(model_id, url, api_key, **ENDPOINTS.get(name, {}))
