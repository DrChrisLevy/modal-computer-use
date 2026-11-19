"""A web browser: full-screen Chromium on the Desktop, with a text view of the page on top.

The mouse and keyboard controls are inherited from Desktop, so a Browser can be driven by
screenshots alone. `goto`, `describe` and the `ref` actions talk to Chromium directly.

It is a single-tab browser: there is no tab strip, and the text view reads the first tab.
"""

import json

from .base import action
from .desktop import ASSETS, Desktop, desktop_image

CHROMIUM = (
    "chromium",
    "--kiosk",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
    "--remote-debugging-port=9222",
    "--user-data-dir=/home/agent/chromium",
    "about:blank",
)

browser_image = desktop_image.uv_pip_install("websockets==15.0.1").add_local_file(
    ASSETS / "cdp.py", "/opt/cdp.py", copy=True
)

# Numbers every visible control on the page and returns the page as text. A control is an element the
# page marks as one, or the outermost element that shows a hand cursor (pages often build links from plain spans).
DESCRIBE = """(() => {
  const controls = 'a[href], button, input, select, textarea, summary, [role=button], [role=link], ' +
    '[role=checkbox], [role=radio], [role=tab], [role=menuitem], [onclick], [contenteditable=true]';
  const hand = el => getComputedStyle(el).cursor === 'pointer';
  document.querySelectorAll('[data-ref]').forEach(el => delete el.dataset.ref);
  const lines = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (!el.matches(controls) && !(hand(el) && !hand(el.parentElement))) continue;
    const box = el.getBoundingClientRect();
    if (!box.width || !box.height || el.disabled || getComputedStyle(el).visibility === 'hidden') continue;
    el.dataset.ref = lines.length + 1;
    const kind = el.getAttribute('role') || (el.tagName === 'INPUT' ? el.type : el.tagName.toLowerCase());
    const label = (el.getAttribute('aria-label') || el.labels?.[0]?.innerText || el.innerText || el.placeholder ||
      el.title || el.alt || el.name || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    let state = '';
    if (el.tagName === 'SELECT') {
      state = ` = "${el.selectedOptions[0]?.text ?? ''}", options: ${[...el.options].map(o => o.text).join(' | ')}`;
    } else if (el.type === 'checkbox' || el.type === 'radio') {
      state = el.checked ? ' (checked)' : ' (unchecked)';
    } else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      state = ` = "${el.value}"`;
    }
    lines.push(`[${el.dataset.ref}] ${kind} "${label}"${state}`);
  }
  let text = document.body.innerText.trim();
  if (text.length > 12000) text = text.slice(0, 12000) + ' ... (the rest of the page text is cut off)';
  return `Page: ${document.title} (${location.href})\\n\\n${text}\\n\\nControls:\\n${lines.join('\\n')}`;
})()"""

# Scrolls a numbered control into view and returns the screen coordinates of the centre of its first line.
LOCATE = """(() => {
  const el = document.querySelector('[data-ref="%d"]');
  if (!el) return null;
  el.scrollIntoView({block: 'center', inline: 'center'});
  // A link that wraps has one box per line, and the centre of them all can be the gap between two lines.
  const box = [...el.getClientRects()].find(part => part.width && part.height) ?? el.getBoundingClientRect();
  const zoom = window.devicePixelRatio;  // page pixels to screen pixels, when the page is zoomed
  return [Math.round((box.x + box.width / 2) * zoom), Math.round((box.y + box.height / 2) * zoom)];
})()"""

# Chooses an option of a numbered <select> by its visible text.
SELECT = """(() => {
  const el = document.querySelector('[data-ref="%d"]');
  const option = [...(el?.options ?? [])].find(o => o.text === %s);
  if (!option) return false;
  el.value = option.value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return true;
})()"""


class Browser(Desktop):
    kind = "web browser"
    image = browser_image
    command = (*Desktop.command, *CHROMIUM)

    def wait_ready(self) -> None:
        super().wait_ready()
        self.run("python", "/opt/cdp.py", "ready")

    @action
    def goto(self, url: str):
        """Load a URL in the browser."""
        self.run("python", "/opt/cdp.py", "goto", url)

    def eval(self, javascript: str):
        """Evaluate a JavaScript expression in the page and return its value."""
        return json.loads(self.run("python", "/opt/cdp.py", "eval", javascript))

    def describe(self) -> str:
        """The page as text: its title, URL, visible text, and a numbered list of its controls."""
        return self.eval(DESCRIBE)

    def _locate(self, ref: int) -> tuple[int, int]:
        point = self.eval(LOCATE % ref)
        if point is None:
            raise ValueError(f"No control [{ref}] on the page. Numbers come from the latest description.")
        return point[0], point[1]

    @action(view="text")
    def click_ref(self, ref: int):
        """Click the control with this number."""
        self.click(*self._locate(ref))

    @action(view="text")
    def fill(self, ref: int, text: str):
        """Replace the contents of the text field with this number."""
        self.click(*self._locate(ref))
        self.key("ctrl+a")
        self.key("BackSpace")
        self.type(text)

    @action(view="text")
    def select(self, ref: int, option: str):
        """Choose an option, by its visible text, in the dropdown with this number."""
        if not self.eval(SELECT % (ref, json.dumps(option))):
            raise ValueError(f"Control [{ref}] has no option {option!r}")
