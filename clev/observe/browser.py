"""Playwright browser session and observer.

One in-page script walks the DOM (including open shadow roots) and computes role, accessible
name, value, state, bounds and landmark context per element. Live element references stay in
the page (window.__clev), keyed by element id and tagged with the observation timestamp, so the
executor gets reliable handles without mutating the page.
"""

from __future__ import annotations

import json
import time
from importlib.resources import files

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from clev.core.types import Element, Observation

_SNAPSHOT_JS = files("clev.observe").joinpath("dom_snapshot.js").read_text(encoding="utf-8")


class BrowserSession:
    """Owns the Playwright browser. Follows new tabs: `page` is the most recent open one."""

    def __init__(
        self,
        headless: bool = True,
        viewport: tuple[int, int] = (1280, 800),
        storage_state: str | None = None,
    ):
        self.headless = headless
        self.viewport = viewport
        self.storage_state = storage_state
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._pages: list[Page] = []

    async def start(self) -> BrowserSession:
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless)
        w, h = self.viewport
        self._context = await self._browser.new_context(
            viewport={"width": w, "height": h}, storage_state=self.storage_state
        )
        self._context.on("page", self._on_page)
        await self._context.new_page()
        return self

    def _on_page(self, page: Page) -> None:
        self._pages.append(page)

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()
        self._browser = self._pw = self._context = None
        self._pages.clear()

    async def __aenter__(self) -> BrowserSession:
        return await self.start()

    async def __aexit__(self, *exc) -> None:
        await self.close()

    @property
    def context(self) -> BrowserContext:
        if self._context is None:
            raise RuntimeError("Session not started")
        return self._context

    @property
    def page(self) -> Page:
        open_pages = [p for p in self._pages if not p.is_closed()]
        if not open_pages:
            raise RuntimeError("No open page; is the session started?")
        return open_pages[-1]

    async def goto(self, url: str, timeout_ms: int = 30000) -> None:
        await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)


class BrowserObserver:
    def __init__(self, session: BrowserSession, max_elements: int = 5000):
        self.session = session
        self.max_elements = max_elements

    async def observe(self) -> Observation:
        page = self.session.page
        ts = time.time()
        raw = await page.evaluate(_SNAPSHOT_JS, {"ts": ts, "maxElements": self.max_elements})
        return Observation(
            app="chromium",
            title=await page.title(),
            url=page.url,
            elements=decode_elements(json.loads(raw)),
            timestamp=ts,
        )


def decode_elements(payload: dict) -> list[Element]:
    """Decode the snapshot script's compact rows (see dom_snapshot.js)."""
    contexts = payload["contexts"]
    return [
        Element(
            id=f"e{i}",
            role=role,
            name=name,
            value=value,
            context=contexts[ctx],
            enabled=bool(flags & 1),
            focused=bool(flags & 2),
            visible=bool(flags & 4),
            bounds=(x, y, w, h),
        )
        for i, (role, name, value, ctx, flags, x, y, w, h) in enumerate(payload["rows"])
    ]
