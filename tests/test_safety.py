import pytest

from clev.core.types import Action, Element, Observation
from clev.safety.gate import SafetyGate
from clev.safety.rules import domain_allowed, is_credential_field, is_destructive


def el(role, name, context="", value=None):
    return Element(id="e0", role=role, name=name, context=context, value=value)


@pytest.mark.parametrize(
    "name", ["Delete", "Remove item", "Send", "Pay now", "Place order", "Checkout", "Submit",
             "Confirm transfer", "Unsubscribe", "Sign out", "Log out", "Cancel subscription"],
)  # fmt: skip
def test_destructive_names(name):
    assert is_destructive(el("button", name))


@pytest.mark.parametrize("name", ["Search", "History", "Sign in", "Next", "Add to cart"])
def test_non_destructive_names(name):
    assert not is_destructive(el("button", name))


def test_known_false_positive_asks_more_than_needed():
    # Word matching errs on the side of asking: "Payment methods" is harmless but matches.
    assert is_destructive(el("link", "Payment methods"))


def test_generic_dialog_button_inherits_dialog_meaning():
    assert is_destructive(el("button", "OK", context='dialog "Delete this file?"'))
    assert not is_destructive(el("link", "OK", context='dialog "Delete this file?"'))
    assert not is_destructive(el("button", "OK", context='dialog "Welcome"'))


@pytest.mark.parametrize(
    "name", ["Password", "Card number", "CVV", "Security code", "Enter OTP", "PIN",
             "One-time code", "Verification code"],
)  # fmt: skip
def test_credential_fields(name):
    assert is_credential_field(el("textbox", name))


def test_redacted_value_counts_as_credential():
    assert is_credential_field(el("textbox", "Secret thing", value="[redacted]"))
    assert not is_credential_field(el("textbox", "First name"))


def test_domain_allowlist():
    allow = ["wikipedia.org"]
    assert domain_allowed("https://en.wikipedia.org/wiki/X", allow)
    assert domain_allowed("https://wikipedia.org", allow)
    assert not domain_allowed("https://wikipedia.org.evil.test", allow)
    assert not domain_allowed("https://example.com", allow)
    assert domain_allowed("about:blank", allow)
    assert domain_allowed("https://anything.test", [])


def obs_with(e, url="https://shop.test/cart"):
    return Observation(app="chromium", title="t", url=url, elements=[e])


async def test_gate_confirms_destructive_clicks():
    answers = []

    async def yes(q):
        answers.append(q)
        return True

    gate = SafetyGate(confirm=yes)
    v = await gate.check(Action(kind="click", element_id="e0"), obs_with(el("button", "Pay now")))
    assert v.allowed and v.reason == "confirmed by user"
    assert "button 'Pay now'" in answers[0]


async def test_gate_without_confirmer_stops_on_destructive():
    v = await SafetyGate().check(
        Action(kind="click", element_id="e0"), obs_with(el("button", "Delete"))
    )
    assert not v.allowed and v.stop


async def test_gate_can_disable_confirmation():
    gate = SafetyGate(confirm_destructive=False)
    v = await gate.check(Action(kind="click", element_id="e0"), obs_with(el("button", "Delete")))
    assert v.allowed


async def test_gate_blocks_credentials_even_without_confirmation_setting():
    gate = SafetyGate(confirm_destructive=False)
    action = Action(kind="type", element_id="e0", text="hunter2")
    v = await gate.check(action, obs_with(el("textbox", "Password")))
    assert not v.allowed and v.stop and "credential" in v.reason


async def test_gate_blocks_off_allowlist_pages():
    gate = SafetyGate(allowed_domains=["wikipedia.org"])
    v = await gate.check(Action(kind="click", element_id="e0"), obs_with(el("link", "Home")))
    assert not v.allowed and v.stop
    ok = await gate.check(
        Action(kind="click", element_id="e0"),
        obs_with(el("link", "Home"), url="https://en.wikipedia.org"),
    )
    assert ok.allowed
