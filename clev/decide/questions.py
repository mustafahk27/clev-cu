"""The typed questions asked each step (plan §8), vendor-neutral.

All are answered in one Jev call. Jev takes questions literally (TypeSafe's jaggedness notes),
so the wording is concrete and each yes/no question describes both outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

NEXT_ACTION = "next_action"
SUBGOAL_COMPLETE = "subgoal_complete"
ERROR_VISIBLE = "error_visible"
PROGRESS = "progress"


@dataclass(frozen=True)
class YesNo:
    instructions: str
    true: str
    false: str


NEXT_ACTION_INSTRUCTIONS = (
    "Which option should the agent take next to achieve the GOAL on this screen? "
    "'type' options mean typing into that field; the text is supplied separately. "
    "Choose SUBGOAL_DONE only if the GOAL is already achieved. Choose NONE_OF_THESE if no "
    "option fits. Don't repeat an action from RECENT ACTIONS that failed or changed nothing."
)

YES_NO: dict[str, YesNo] = {
    SUBGOAL_COMPLETE: YesNo(
        "Is the GOAL already achieved on the current screen?",
        true="The screen already shows the GOAL's end state (e.g. the requested page is open, "
        "the text is in the field).",
        false="Something still has to be done on this screen to achieve the GOAL.",
    ),
    ERROR_VISIBLE: YesNo(
        "Does the screen show an error, a warning, or an unexpected dialog that blocks the GOAL?",
        true="An error message, failure notice, 'page not found', or blocking pop-up is shown.",
        false="No error or blocking dialog is shown.",
    ),
    PROGRESS: YesNo(
        "Did the LAST ACTION move the agent closer to the GOAL?",
        true="The screen changed in a way that helps achieve the GOAL.",
        false="Nothing useful changed, or the agent moved away from the GOAL.",
    ),
}
