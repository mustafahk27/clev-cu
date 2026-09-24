"""Playwright executor: click, type, key, scroll, back, wait."""

from __future__ import annotations

from playwright.async_api import ElementHandle
from playwright.async_api import Error as PlaywrightError

from clev.core.errors import ActionError, StaleElementError
from clev.core.types import Action, Observation
from clev.observe.browser import BrowserSession

# Map Clev key names (planner/decider vocabulary) to Playwright's.
_KEY_NAMES = {
    "cmd": "Meta", "command": "Meta", "meta": "Meta", "ctrl": "Control", "control": "Control",
    "alt": "Alt", "option": "Alt", "shift": "Shift", "enter": "Enter", "return": "Enter",
    "esc": "Escape", "escape": "Escape", "tab": "Tab", "space": "Space",
    "backspace": "Backspace", "delete": "Delete", "up": "ArrowUp", "down": "ArrowDown",
    "left": "ArrowLeft", "right": "ArrowRight", "home": "Home", "end": "End",
    "pageup": "PageUp", "pagedown": "PageDown",
}  # fmt: skip

_RESOLVE_JS = """([ts, id]) => {
  const c = window.__clev;
  if (!c || c.ts !== ts) return null;
  const el = c.els.get(id);
  return el && el.isConnected ? el : null;
}"""


def to_playwright_key(key: str) -> str:
    """'cmd+enter' -> 'Meta+Enter'. Single characters and F-keys pass through."""
    parts = [p.strip() for p in key.split("+") if p.strip()]
    if not parts:
        raise ActionError(f"Empty key combo: {key!r}")
    out = []
    for p in parts:
        low = p.lower()
        if low in _KEY_NAMES:
            out.append(_KEY_NAMES[low])
        elif low[0] == "f" and low[1:].isdigit():
            out.append(low.upper())  # f5 -> F5
        else:
            out.append(p)  # single character, or already a Playwright name like "ArrowDown"
    return "+".join(out)


class BrowserExecutor:
    def __init__(
        self,
        session: BrowserSession,
        action_timeout_ms: int = 5000,
        settle_ms: int = 300,
        wait_ms: int = 1000,
    ):
        self.session = session
        self.action_timeout_ms = action_timeout_ms
        self.settle_ms = settle_ms
        self.wait_ms = wait_ms

    async def execute(self, action: Action, obs: Observation) -> None:
        page = self.session.page
        try:
            match action.kind:
                case "click":
                    el = await self._element(action, obs)
                    await el.click(timeout=self.action_timeout_ms)
                case "type":
                    if action.text is None:
                        raise ActionError("type action needs text")
                    el = await self._element(action, obs)
                    await self._type(el, action.text)
                case "key":
                    if not action.key:
                        raise ActionError("key action needs key")
                    key = to_playwright_key(action.key)
                    if action.element_id:
                        el = await self._element(action, obs)
                        await el.press(key, timeout=self.action_timeout_ms)
                    else:
                        await page.keyboard.press(key)
                case "scroll":
                    sign = -1 if action.direction == "up" else 1
                    js = "(el, s) => el.scrollBy(0, s * 0.8 * (el.clientHeight || innerHeight))"
                    if action.element_id:
                        el = await self._element(action, obs)
                        await el.evaluate(js, sign)
                    else:
                        await page.evaluate("s => scrollBy(0, s * 0.8 * innerHeight)", sign)
                case "back":
                    await page.go_back(wait_until="domcontentloaded")
                case "wait":
                    await page.wait_for_timeout(self.wait_ms)
                case "done" | "fail":
                    return
        except PlaywrightError as e:
            raise ActionError(f"{action.kind} failed: {e.message.splitlines()[0]}") from e
        await self._settle()

    async def _element(self, action: Action, obs: Observation) -> ElementHandle:
        if not action.element_id:
            raise ActionError(f"{action.kind} action needs element_id")
        handle = await self.session.page.evaluate_handle(
            _RESOLVE_JS, [obs.timestamp, action.element_id]
        )
        el = handle.as_element()
        if el is None:
            raise StaleElementError(
                f"{action.element_id} is not in the current page (stale observation or removed)"
            )
        return el

    async def _type(self, el: ElementHandle, text: str) -> None:
        # fill() clears the field first (plan §10). Fall back to click + select-all + typing for
        # custom widgets that fill() rejects.
        try:
            await el.fill(text, timeout=self.action_timeout_ms)
        except PlaywrightError:
            await el.click(timeout=self.action_timeout_ms)
            page = self.session.page
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.press("Delete")
            await page.keyboard.type(text)

    async def _settle(self) -> None:
        # Wait first: a tab opened by the action only registers with the session a moment later.
        await self.session.page.wait_for_timeout(self.settle_ms)
        page = self.session.page  # may now be the new tab
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self.action_timeout_ms)
        except PlaywrightError:
            pass  # slow pages still get observed; the next step can "wait"
