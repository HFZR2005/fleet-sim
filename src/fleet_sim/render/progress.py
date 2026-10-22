"""A progress reporter for the terminal.

A terminal gets one updating bar. Anywhere else, each unit is a line on
stderr, so a redirected run still leaves a trace. The result table stays
on stdout.
"""

import time
from types import TracebackType
from typing import Self

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)


class ConsoleProgress:
    """``RunProgress`` drawn with Rich on stderr."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console if console is not None else Console(stderr=True)
        self._started = time.perf_counter()
        self._bar: Progress | None = None
        self._task_id: TaskID | None = None
        self._closed = False
        if self._console.is_terminal:
            self._bar = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                TimeRemainingColumn(),
                console=self._console,
                transient=True,
            )
            self._bar.start()

    def task(self, description: str, total: int | None) -> None:
        if self._bar is not None:
            if self._task_id is not None:
                self._bar.remove_task(self._task_id)
            self._task_id = self._bar.add_task(description, total=total)
        else:
            self._console.print(description, highlight=False)

    def detail(self, text: str) -> None:
        if self._bar is not None and self._task_id is not None:
            self._bar.update(self._task_id, description=text)
        elif self._bar is None:
            self._console.print(text, highlight=False)

    def advance(self) -> None:
        if self._bar is not None and self._task_id is not None:
            self._bar.advance(self._task_id)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_bar()
        elapsed = time.perf_counter() - self._started
        self._console.print(f"finished in {elapsed:.1f}s", highlight=False)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.close()
        else:
            self._closed = True
            self._stop_bar()

    def _stop_bar(self) -> None:
        if self._bar is not None:
            self._bar.stop()
            self._bar = None
