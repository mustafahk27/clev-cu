"""Vendor-neutral errors that adapters raise and the control loop handles."""


class ClevError(Exception):
    """Base class for Clev errors."""


class StaleElementError(ClevError):
    """The element id is from an older observation, or the element left the page."""


class ObservationError(ClevError):
    """The UI couldn't be read (e.g. the page kept navigating)."""


class DeciderError(ClevError):
    """The decision model (Jev) failed after its SDK's retries."""


class LLMError(ClevError):
    """A model call failed or returned something unusable (after the adapter's retries)."""


class ActionError(ClevError):
    """An action could not be performed (bad arguments, element not actionable, timeout)."""
