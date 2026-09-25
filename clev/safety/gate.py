"""Safety gate: runs before every action (plan §11)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from clev.core.types import Action, Observation
from clev.safety.rules import domain_allowed, is_credential_field, is_destructive

Confirm = Callable[[str], Awaitable[bool]]


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None = None
    stop: bool = False  # end the run (credential field, domain, user declined) vs just skip


ALLOW = Verdict(allowed=True)


class SafetyGate:
    def __init__(
        self,
        confirm_destructive: bool = True,
        allowed_domains: list[str] | None = None,
        confirm: Confirm | None = None,
    ):
        self.confirm_destructive = confirm_destructive
        self.allowed_domains = allowed_domains or []
        self.confirm = confirm

    async def check(self, action: Action, obs: Observation) -> Verdict:
        if action.kind == "goto" and not domain_allowed(action.url, self.allowed_domains):
            return Verdict(False, f"{action.url} is outside ALLOWED_DOMAINS", stop=True)
        if not domain_allowed(obs.url, self.allowed_domains):
            return Verdict(False, f"current page {obs.url} is outside ALLOWED_DOMAINS", stop=True)

        target = obs.element(action.element_id) if action.element_id else None
        if target is None:
            return ALLOW
        if action.kind == "type" and is_credential_field(target):
            return Verdict(
                False,
                f"won't type into credential field {target.name!r}; please enter it yourself",
                stop=True,
            )
        if self.confirm_destructive and action.kind in ("click", "key") and is_destructive(target):
            question = f"Clev wants to {action.kind} {target.role} {target.name!r}"
            if target.context:
                question += f" (in {target.context})"
            if self.confirm is None:
                return Verdict(False, f"{question}: needs confirmation", stop=True)
            if not await self.confirm(question + ". Allow?"):
                return Verdict(False, f"user declined: {action.kind} {target.name!r}", stop=True)
            return Verdict(True, "confirmed by user")
        return ALLOW
