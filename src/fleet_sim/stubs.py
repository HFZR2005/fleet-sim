"""Mark a function whose result is a placeholder.

A stub is registered when it runs, not when it is defined, so a run can
list the stubs it actually called. ``--release`` refuses a run that called
any.
"""

from collections.abc import Callable
from typing import TypeVar, cast

F = TypeVar("F", bound=Callable[..., object])

_active: list[str] = []


class StubActiveError(ValueError):
    """A ``--release`` run called a stub."""

    def __init__(self, stubs: list[str]) -> None:
        self.stubs = stubs
        lines = "\n".join(stubs)
        super().__init__(f"STUB --release cannot run while stubs are active:\n{lines}")


def stub(reason: str) -> Callable[[F], F]:
    """Register ``reason`` each time the decorated function runs."""

    def decorate(fn: F) -> F:
        def wrapper(*args: object, **kwargs: object) -> object:
            text = f"{fn.__qualname__}: {reason}"
            if text not in _active:
                _active.append(text)
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__qualname__ = fn.__qualname__
        return cast(F, wrapper)

    return decorate


def begin_stub_run() -> None:
    """Forget stubs recorded by an earlier run in this process."""
    _active.clear()


def active_stubs() -> list[str]:
    """Stubs called since ``begin_stub_run``, in the order they first ran."""
    return list(_active)


def require_no_stubs() -> None:
    """Raise when this run called a stub."""
    found = active_stubs()
    if found:
        raise StubActiveError(found)
