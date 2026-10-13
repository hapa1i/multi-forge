"""Lightweight adapter facts shared by native source selection and policy contexts."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class NativeReviewBoundary:
    """Trusted hook identity; never populated from proposed tool arguments."""

    thread_id: str
    turn_id: str
    transcript_path: str
    event: str
    last_assistant_message: str | None = None


def native_billing_mode(auth_mode: str) -> Literal["api", "subscription_quota"]:
    """Classify the selected native route; status and usage must agree."""
    return "api" if auth_mode == "api" else "subscription_quota"
