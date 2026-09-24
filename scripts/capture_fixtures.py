"""Capture observation fixtures from real sites into tests/fixtures/<name>.json.gz.

Run: uv run python scripts/capture_fixtures.py [name ...]

Each site lists candidate URLs; the first one that loads with enough elements (and isn't a
bot-check page) is saved. Only public pages: fixtures are committed to git, so never capture
logged-in or personal pages.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from clev.observe.browser import BrowserObserver, BrowserSession
from clev.observe.io import save_observation

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

SITES: dict[str, list[str]] = {
    "wikipedia": ["https://en.wikipedia.org/wiki/Karachi"],
    "github": ["https://github.com/microsoft/playwright-python"],
    # Amazon-like: public demo shops built for automation testing (Amazon's ToS forbids bots).
    "shop": [
        "https://demo.nopcommerce.com/",
        "https://demo.opencart.com/",
        "https://books.toscrape.com/",
    ],
    "form": [
        "https://demoqa.com/automation-practice-form",
        "https://www.selenium.dev/selenium/web/web-form.html",
    ],
    # Gmail-like: public webmail demos (a real inbox would leak personal mail into git).
    "mail": [
        "https://demo.mailpit.axllent.org/",
        "https://roundcube.net/demo/",
    ],
}

BLOCKED = ("captcha", "just a moment", "attention required", "access denied", "robot")


async def capture(session: BrowserSession, name: str, urls: list[str]) -> None:
    observer = BrowserObserver(session)
    for url in urls:
        try:
            await session.goto(url)
            await session.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception as e:  # noqa: BLE001 - try the next candidate
            print(f"  {name}: {url} failed to load ({type(e).__name__})")
            if "networkidle" not in str(e) and "Timeout" not in type(e).__name__:
                continue
        obs = await observer.observe()
        interactive = sum(e.role not in ("heading", "alert", "status") for e in obs.elements)
        if interactive < 20 or any(b in obs.title.lower() for b in BLOCKED):
            print(f"  {name}: {url} rejected ({interactive} interactive, title {obs.title!r})")
            continue
        path = OUT / f"{name}.json.gz"
        save_observation(obs, path)
        kb = path.stat().st_size / 1024
        print(f"  {name}: {url} -> {len(obs.elements)} elements ({interactive} interactive), "
              f"{kb:.0f} KB")  # fmt: skip
        return
    print(f"  {name}: NO FIXTURE (all candidates failed)")


async def main(names: list[str]) -> None:
    async with BrowserSession(headless=True) as session:
        for name in names or SITES:
            await capture(session, name, SITES[name])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
