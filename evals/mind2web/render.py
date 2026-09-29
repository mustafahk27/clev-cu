"""Turn a Mind2Web step's saved HTML into a Clev Observation with our real browser observer.

The HTML is Mind2Web's cleaned DOM snapshot (no CSS or scripts), loaded with set_content, so
every element renders as visible: ranking has more candidates than the live page would have.

The cleaning also drops `href` from links and renames `aria-*` attributes to `aria_*`; both are
restored before rendering, or most links would lose their role and name. This is eval-only
preprocessing; the live observer is unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clev.core.types import Observation
from clev.observe.browser import BrowserObserver, BrowserSession

_A_WITHOUT_HREF = re.compile(r"<a\b(?![^>]*\bhref=)", re.IGNORECASE)
_ARIA_UNDERSCORE = re.compile(r"\baria_([a-z]+)=")

# Element ids (ours) for every element, plus which ones count as hitting the target.
_MATCH_JS = """(targetIds) => {
  const ids = {}, strict = [], equivalent = [];
  const targets = targetIds
    .map((b) => document.querySelector(`[backend_node_id="${b}"]`))
    .filter(Boolean);
  const CLICK_WRAPPERS = new Set(["A", "BUTTON", "LABEL", "SUMMARY"]);
  for (const [id, el] of window.__clev.els) {
    const b = el.getAttribute("backend_node_id");
    if (b) ids[id] = b;
    for (const t of targets) {
      if (el === t) { strict.push(id); equivalent.push(id); break; }
      const same =
        t.contains(el) ||                                        // target wraps our element
        (CLICK_WRAPPERS.has(el.tagName) && el.contains(t)) ||    // our link/button wraps target
        (t.tagName === "LABEL" && (t.control === el || t.contains(el))) ||
        (el.labels && [...el.labels].includes(t));               // target labels our input
      if (same) { equivalent.push(id); break; }
    }
  }
  return { ids, strict, equivalent, found: targets.length };
}"""


def prepare_html(html: str) -> str:
    html = _A_WITHOUT_HREF.sub('<a href="#"', html)
    return _ARIA_UNDERSCORE.sub(r"aria-\1=", html)


@dataclass
class Rendered:
    obs: Observation
    backend_ids: dict[str, str]  # our element id -> Mind2Web backend_node_id
    strict: set[str]  # our ids that are the target element
    equivalent: set[str]  # our ids that click the same thing (includes strict)
    target_in_html: bool


class Mind2WebRenderer:
    def __init__(self, session: BrowserSession):
        self.session = session
        self.observer = BrowserObserver(session)

    async def render(self, html: str, website: str, target_ids: list[str]) -> Rendered:
        page = self.session.page
        await page.set_content(prepare_html(html), wait_until="domcontentloaded")
        obs = await self.observer.observe()
        m = await page.evaluate(_MATCH_JS, target_ids)
        # The snapshot has no URL; give the decider the site name instead.
        obs = obs.model_copy(update={"title": website, "url": f"https://{website}.example/"})
        return Rendered(obs, m["ids"], set(m["strict"]), set(m["equivalent"]), m["found"] > 0)
