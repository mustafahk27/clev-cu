"""Safety patterns (plan §11)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from clev.core.types import Element

# Clicking these needs the user's OK.
DESTRUCTIVE = re.compile(
    r"\b(delete|remove|send|pay|payment|purchase|buy|place order|checkout|check out|submit|"
    r"confirm|transfer|unsubscribe|sign out|log out|logout|deactivate|close account|"
    r"cancel (?:subscription|order|account|membership)|empty trash)\b",
    re.IGNORECASE,
)
# Never type into these: hand control back to the user.
CREDENTIAL = re.compile(
    r"password|passcode|passphrase|card number|credit card|debit card|\bcvv\b|\bcvc\b|"
    r"security code|\botp\b|one[- ]time|\bpin\b|verification code|\bssn\b|social security|"
    r"account number|routing number|\biban\b",
    re.IGNORECASE,
)


def is_destructive(e: Element) -> bool:
    if DESTRUCTIVE.search(e.name):
        return True
    # A generic button ("OK", "Yes") in a dialog asking to delete/pay/... is destructive too.
    return e.role == "button" and "dialog" in e.context and bool(DESTRUCTIVE.search(e.context))


def is_credential_field(e: Element) -> bool:
    return e.value == "[redacted]" or bool(CREDENTIAL.search(f"{e.name} {e.context}"))


def host(url: str | None) -> str:
    return (urlparse(url or "").hostname or "").lower()


def domain_allowed(url: str | None, allowlist: list[str]) -> bool:
    """Empty allowlist allows everything. Non-web pages (about:blank) are always allowed."""
    if not allowlist or not (url or "").startswith("http"):
        return True
    h = host(url)
    return any(h == d or h.endswith("." + d) for d in allowlist)
