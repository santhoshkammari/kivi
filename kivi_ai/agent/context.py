"""Cancellation and request-scoped context for Kivi agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event as ThreadEvent

__all__ = ["CancelledError", "CancellationToken", "Context"]


class CancelledError(Exception):
    """Raised when work is interrupted by cancellation."""


@dataclass(slots=True)
class CancellationToken:
    _event: ThreadEvent = field(default_factory=ThreadEvent, init=False, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.is_cancelled:
            raise CancelledError("operation cancelled")


@dataclass(slots=True, init=False)
class Context:
    _work_dir: str
    _session_id: str | None
    _cancel_token: CancellationToken

    def __init__(self, work_dir: str = ".", session_id: str | None = None, cancel_token: CancellationToken | None = None):
        self._work_dir = str(Path(work_dir).resolve())
        self._session_id = session_id
        self._cancel_token = cancel_token or CancellationToken()

    @property
    def work_dir(self) -> str:
        return self._work_dir

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def cancel(self) -> None:
        self._cancel_token.cancel()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_token.is_cancelled

    def check(self) -> None:
        self._cancel_token.check()

    def __enter__(self) -> Context:
        return self

    def __exit__(self, *args) -> bool:
        self.cancel()
        return False

    def child(self, work_dir: str | None = None) -> Context:
        child_dir = str(Path(work_dir).resolve()) if work_dir else self._work_dir
        return Context(work_dir=child_dir, session_id=self._session_id, cancel_token=self._cancel_token)

    def resolve_path(self, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path(self._work_dir) / candidate
        return candidate.resolve()
