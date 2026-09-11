"""Explicit, fail-closed analysis-task state transitions."""

from collections.abc import Mapping

TERMINAL_STATES = frozenset({"completed", "dead_lettered", "skipped"})
_TRANSITIONS: Mapping[str, frozenset[str]] = {
    "queued": frozenset({"processing", "skipped", "dead_lettered"}),
    "processing": frozenset({"queued", "completed", "skipped", "dead_lettered"}),
    "completed": frozenset(),
    "skipped": frozenset(),
    "dead_lettered": frozenset(),
}


class InvalidTaskTransition(ValueError):
    """Raised when a worker attempts a transition outside the task lifecycle."""


def assert_transition(current: str, target: str) -> None:
    if target not in _TRANSITIONS.get(current, frozenset()):
        raise InvalidTaskTransition(
            f"cannot transition knowledge task from {current!r} to {target!r}"
        )
