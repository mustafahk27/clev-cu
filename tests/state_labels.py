"""Hand-labeled steps over the real-site fixtures, for ranking recall (Phase 3 'done when').

Each label: (fixture, subgoal, target). A target matches an element by role, exact name (or a
'prefix*' / '*suffix' pattern for names with changing counts), and optionally a substring of
its context. Matching by description instead of id keeps labels valid across re-captures.

Caveat: labels were written after seeing the fixtures, and ranking weights were tuned on them,
so recall here is optimistic. Phase 6 (Mind2Web) gives the unbiased number.
"""

from __future__ import annotations

from dataclasses import dataclass

from clev.core.types import Element


@dataclass(frozen=True)
class Target:
    role: str
    name: str
    context: str = ""

    def matches(self, e: Element) -> bool:
        if e.role != self.role or self.context not in e.context:
            return False
        if self.name.endswith("*"):
            return e.name.startswith(self.name[:-1])
        if self.name.startswith("*"):
            return e.name.endswith(self.name[1:])
        return e.name == self.name


LABELS: list[tuple[str, str, Target]] = [
    # Wikipedia: Karachi (~3,200 visible candidates, the real test of ranking)
    ("wikipedia", 'Type "Lahore" into the search box', Target("searchbox", "Search Wikipedia")),
    ("wikipedia", "Click the search button", Target("button", "Search", "search > form")),
    ("wikipedia", "Open the History section", Target("link", "History", "Contents")),
    ("wikipedia", "Go to the References section", Target("link", "References", "Contents")),
    ("wikipedia", "Log in to Wikipedia", Target("link", "Log in")),
    ("wikipedia", "Create a new account", Target("link", "Create account")),
    ("wikipedia", "View the revision history of this article", Target("link", "View history")),
    ("wikipedia", "Open the talk page", Target("link", "Talk")),
    ("wikipedia", "Read this article in another language", Target("button", "181 languages")),
    ("wikipedia", "Open the Port of Karachi article", Target("link", "Port of Karachi")),
    (
        "wikipedia",
        "Open the Jinnah International Airport article",
        Target("link", "Jinnah International Airport"),
    ),
    (
        "wikipedia",
        "Expand the Economy subsection in the table of contents",
        Target("button", "Toggle Economy subsection"),
    ),
    ("wikipedia", "Open the Indus River article", Target("link", "Indus River")),
    (
        "wikipedia",
        "Open the Clifton link in the Economy section",
        Target("link", "Clifton", 'region "Economy"'),
    ),
    # GitHub: microsoft/playwright-python
    ("github", "Open the Issues tab", Target("link", "Issues*")),
    ("github", "Open the pull requests", Target("link", "Pull requests*")),
    ("github", 'Type "setup.py" into the go to file box', Target("combobox", "Go to file")),
    ("github", "Sign in to GitHub", Target("link", "Sign in")),
    ("github", "Open the tests folder", Target("link", "tests, (Directory)")),
    ("github", "See the full commit history", Target("link", "*Commits")),
    ("github", "Switch to a different branch", Target("button", "main branch")),
    # Shop: books.toscrape.com
    ("shop", "Open the Mystery category", Target("link", "Mystery")),
    (
        "shop",
        "Add Tipping the Velvet to the basket",
        Target("button", "Add to basket", 'article "Tipping the Velvet"'),
    ),
    ("shop", "Go to the next page of results", Target("link", "next")),
    ("shop", "Open the Sharp Objects book", Target("link", "Sharp Objects")),
    # Form: demoqa practice form
    ("form", 'Type "Mustafa" into the First Name field', Target("textbox", "First Name")),
    ("form", 'Enter "a@b.com" as the email', Target("textbox", "name@example.com")),
    ("form", "Select Male as the gender", Target("radio", "Male")),
    ("form", "Tick the Reading hobby", Target("checkbox", "Reading")),
    ("form", "Submit the registration form", Target("button", "Submit")),
    (
        "form",
        'Type "03001234567" into the mobile number field',
        Target("textbox", "Mobile Number"),
    ),
]

# Held-out: written for pages the ranker had never seen, before any ranking ran on them
# (2026-09-25). Recall before the fix-ranking-recall change: 17/18 in top 200, 12/18 at #1.
# Don't tune weights to these. When changing ranking, add fresh held-out pages instead.
HELDOUT: list[tuple[str, str, Target]] = [
    ("heldout_wiki_muscat", "Open the Climate section", Target("link", "*Climate")),
    ("heldout_wiki_muscat", "Open the article about Oman", Target("link", "Oman")),
    (
        "heldout_wiki_muscat",
        "Open the Sultan Qaboos Grand Mosque article",
        Target("link", "Sultan Qaboos Grand Mosque"),
    ),
    (
        "heldout_wiki_muscat",
        'Type "Salalah" into the search box',
        Target("searchbox", "Search Wikipedia"),
    ),
    ("heldout_wiki_muscat", "View the page's edit history", Target("link", "View history")),
    (
        "heldout_wiki_python",
        "Open the article on Guido van Rossum",
        Target("link", "Guido van Rossum"),
    ),
    (
        "heldout_wiki_python",
        "Go to the Syntax and semantics section",
        Target("link", "*Syntax and semantics"),
    ),
    ("heldout_wiki_python", "Open the Talk page", Target("link", "Talk")),
    ("heldout_wiki_python", "Open the CPython article", Target("link", "CPython")),
    ("heldout_hn", "Log in to Hacker News", Target("link", "login")),
    ("heldout_hn", "Go to the next page of stories", Target("link", "More")),
    ("heldout_hn", "Open the Ask HN section", Target("link", "ask")),
    ("heldout_hn", "Submit a new story", Target("link", "submit")),
    ("heldout_hn", "Show the newest stories", Target("link", "new")),
    ("heldout_gh_playwright", "Open the Issues tab", Target("link", "Issues*")),
    ("heldout_gh_playwright", "Open the Actions tab", Target("link", "Actions")),
    ("heldout_gh_playwright", "Star this repository", Target("link", "*star a repository")),
    ("heldout_gh_playwright", "Sign in to GitHub", Target("link", "Sign in")),
]
