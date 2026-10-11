"""Lightweight adapter facts shared by native source selection and policy contexts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeReviewBoundary:
    """Trusted hook identity; never populated from proposed tool arguments."""

    thread_id: str
    turn_id: str
    transcript_path: str
    event: str
    last_assistant_message: str | None = None
