"""Shared fixtures.

Browser tests use a fake origin (https://clev.test) served by a Playwright route, so navigation
and history are real but nothing touches the network.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from clev.observe.browser import BrowserSession

ORIGIN = "https://clev.test"


class Site:
    """Pages served at https://clev.test/<path> for the current test."""

    def __init__(self):
        self.pages: dict[str, str] = {}

    def add(self, path: str, body: str, title: str = "Test") -> str:
        head = f"<!doctype html><html><head><title>{title}</title></head>"
        self.pages[path] = f"{head}<body>{body}</body></html>"
        return f"{ORIGIN}/{path}"


@pytest_asyncio.fixture(scope="session")
async def browser_session():
    async with BrowserSession(headless=True) as session:
        yield session


@pytest_asyncio.fixture
async def site(browser_session: BrowserSession):
    site = Site()

    async def handle(route):
        path = route.request.url.removeprefix(ORIGIN + "/").split("#")[0].split("?")[0]
        if path in site.pages:
            await route.fulfill(status=200, content_type="text/html", body=site.pages[path])
        else:
            await route.fulfill(status=404, body="not found")

    await browser_session.context.route(f"{ORIGIN}/**", handle)
    yield site
    await browser_session.context.unroute(f"{ORIGIN}/**", handle)
    # Close tabs a test opened so the next test starts on the original page.
    pages = browser_session.context.pages
    for extra in pages[1:]:
        await extra.close()


@pytest.fixture
def open_page(browser_session: BrowserSession, site: Site):
    async def _open(body: str, path: str = "index.html", title: str = "Test") -> None:
        await browser_session.goto(site.add(path, body, title))

    return _open
