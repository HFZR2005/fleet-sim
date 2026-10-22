"""Optional progress reports for long runs.

Library code calls this and stays quiet when no reporter is passed. The
command line supplies one that draws on the terminal.
"""

from typing import Protocol


class RunProgress(Protocol):
    """One moving task. ``detail`` names the unit in progress. ``advance`` ends it."""

    def task(self, description: str, total: int | None) -> None:
        """Start a task. A new call replaces the one already running."""

    def detail(self, text: str) -> None:
        """Say what the current unit is, before it runs."""

    def advance(self) -> None:
        """Count one unit finished."""

    def close(self) -> None:
        """Stop reporting."""


class NullProgress:
    """A reporter that keeps nothing and prints nothing."""

    def task(self, description: str, total: int | None) -> None:
        return None

    def detail(self, text: str) -> None:
        return None

    def advance(self) -> None:
        return None

    def close(self) -> None:
        return None
