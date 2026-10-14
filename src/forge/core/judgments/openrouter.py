"""Async OpenRouter Decisions transport with mandatory ZDR."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from forge.core.llm.credentials import CredentialManager
from forge.core.llm.errors import NoApiKeyError
from forge.core.reactive.env import RunIdentity, get_run_identity
from forge.core.telemetry.downstream import mint_downstream_event_id
from forge.core.usage.correlation import mint_request_id, resolve_direct_provider_user

from .types import (
    ChoiceQuestion,
    JudgmentAttempt,
    JudgmentError,
    JudgmentResponse,
    JudgmentResult,
    NoulQuestion,
    Question,
    ScoreQuestion,
    partial_metadata,
    validate_answers,
)
from .usage import emit_attempt

DEFAULT_MODEL = "typesafe/jev-1.13"
MAX_INPUT_BYTES = 30_000
MAX_RESPONSE_BYTES = 256_000


class OpenRouterJudgmentClient:
    """Evaluate typed questions; callers own the overall monotonic deadline."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        credentials: CredentialManager | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_attempts: int = 2,
        command: str = "jev",
    ) -> None:
        if not model.strip() or "latest" in model or model.startswith("~"):
            raise ValueError("select an explicit judgment model, not a moving alias")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not command.strip():
            raise ValueError("command must identify the judgment consumer")
        self.model = model
        self.credentials = credentials or CredentialManager.default()
        self.transport = transport
        self.max_attempts = max_attempts
        self.command = command

    async def judge(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, Question],
        *,
        deadline: float,
        provider_options: dict[str, Any] | None = None,
    ) -> JudgmentResult:
        """Return usable judgments or a typed failure with independently valid attempt evidence."""
        payload = build_payload(self.model, state, questions, provider_options)
        question_snapshot = {
            key: type(question).model_validate(payload["questions"][key]) for key, question in questions.items()
        }
        if not math.isfinite(deadline) or deadline <= time.monotonic():
            raise JudgmentError("deadline", "Judgment deadline expired before dispatch")
        identity = get_run_identity()
        session = os.environ.get("FORGE_SESSION")
        attempts: list[JudgmentAttempt] = []
        try:
            async with asyncio.timeout(deadline - time.monotonic()):
                creds = await self.credentials.get_credentials("openrouter")
                url = decisions_url(creds["base_url"])
                grouping = resolve_direct_provider_user("jev")
                if grouping:
                    payload["user"] = grouping
                    payload["session_id"] = grouping
                encoded = encode_payload(payload)
                async with httpx.AsyncClient(transport=self.transport, follow_redirects=False) as client:
                    for number in range(self.max_attempts):
                        if time.monotonic() >= deadline:
                            raise JudgmentError("deadline", "Judgment deadline expired before dispatch")
                        response, delay = await self._attempt(
                            client,
                            url,
                            encoded,
                            creds,
                            question_snapshot,
                            deadline,
                            attempts,
                            identity=identity,
                            session=session,
                            grouping=grouping,
                        )
                        attempt = attempts[-1]
                        if response is not None:
                            return JudgmentResult(response, tuple(attempts))
                        if (
                            attempt.status_code not in {429, 500, 502, 503, 529}
                            or attempt.failure not in {"rate_limit", "provider_error", "overloaded"}
                            or number + 1 == self.max_attempts
                        ):
                            raise JudgmentError(
                                attempt.failure or "invalid_response",
                                f"OpenRouter judgment failed: {attempt.failure} (HTTP {attempt.status_code})",
                            )
                        backoff = delay if delay is not None else min(0.25 * 2**number, 2.0)
                        if backoff >= deadline - time.monotonic():
                            raise JudgmentError("deadline", "Judgment retry would exceed the caller deadline")
                        await asyncio.sleep(backoff)
        except NoApiKeyError as exc:
            raise JudgmentError("authentication", str(exc)) from None
        except JudgmentError as exc:
            raise JudgmentError(exc.kind, str(exc), attempts=tuple(attempts)) from None
        except TimeoutError:
            kind = "ambiguous_timeout" if attempts and attempts[-1].failure == "ambiguous_timeout" else "deadline"
            raise JudgmentError(kind, "Judgment deadline expired", attempts=tuple(attempts)) from None
        except Exception:
            raise JudgmentError(
                "internal_error", "Judgment client failed unexpectedly", attempts=tuple(attempts)
            ) from None
        raise AssertionError("bounded judgment loop must return or fail")

    async def _attempt(
        self,
        client: httpx.AsyncClient,
        url: str,
        encoded: bytes,
        creds: dict[str, Any],
        questions: dict[str, Question],
        deadline: float,
        attempts: list[JudgmentAttempt],
        *,
        identity: RunIdentity | None,
        session: str | None,
        grouping: str | None,
    ) -> tuple[JudgmentResponse | None, float | None]:
        request_id = mint_request_id()
        started = time.monotonic()
        status: int | None = None
        failure: str | None = "internal_error"
        body: Any = None
        response = None
        delay = None
        try:
            async with client.stream(
                "POST",
                url,
                content=encoded,
                headers={
                    **creds.get("extra_headers", {}),
                    "Authorization": f"Bearer {creds['api_key']}",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                },
                timeout=max(0.001, deadline - started),
            ) as wire:
                status = wire.status_code
                delay = retry_after(wire.headers.get("Retry-After"))
                chunks = bytearray()
                async for chunk in wire.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        raise JudgmentError("invalid_response", "Judgment response exceeds the byte limit")
                try:
                    body = json.loads(chunks, object_pairs_hook=_unique_object)
                except (ValueError, UnicodeError, RecursionError):
                    body = None
                status_error = status_failure(status, body)
                if status_error is not None:
                    failure = status_error
                else:
                    try:
                        candidate = JudgmentResponse.model_validate(body)
                        validate_answers(candidate, questions)
                        response = candidate
                    except ValueError:
                        failure = "invalid_response"
            # A validated body is successful only after the response stream closes cleanly.
            if response is not None:
                failure = None
        except asyncio.CancelledError:
            failure = "ambiguous_timeout" if time.monotonic() >= deadline else "cancelled"
            raise
        except httpx.TimeoutException:
            failure = "ambiguous_timeout"
        except httpx.HTTPError:
            failure = "transport"
        except JudgmentError as exc:
            failure = exc.kind
        except Exception:
            # Unknown failures must neither look successful nor become retryable provider errors.
            failure = "internal_error"
        finally:
            attempt = JudgmentAttempt(
                request_id,
                mint_downstream_event_id(),
                self.model,
                (time.monotonic() - started) * 1000,
                status_code=status,
                failure=failure,
                **partial_metadata(body),
            )
            attempts.append(attempt)
            emit_attempt(
                attempt,
                identity=identity,
                session=session,
                grouping=grouping,
                command=self.command,
                direct=url == "https://openrouter.ai/api/alpha/decisions",
            )
        return (None if failure else response), delay


def retry_after(value: str | None) -> float | None:
    """Interpret seconds or an HTTP date; invalid values use the bounded default backoff."""
    if value is None:
        return None
    try:
        delay = float(value) if value.isdigit() else parsedate_to_datetime(value).timestamp() - time.time()
    except (ValueError, TypeError, OverflowError):
        return None
    return max(0, delay) if math.isfinite(delay) else None


def decisions_url(base_url: str) -> str:
    """Resolve only known API-base shapes, retaining a custom gateway's path prefix."""
    try:
        parts = urlsplit(base_url)
        httpx.URL(base_url)
        parts.port
    except (ValueError, httpx.InvalidURL):
        raise JudgmentError("unsupported_route", "OpenRouter base URL is malformed") from None
    if (
        parts.scheme not in {"https", "http"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or any(char.isspace() for char in base_url)
    ):
        raise JudgmentError(
            "unsupported_route",
            "OpenRouter base URL must be an HTTP(S) API base without credentials or query",
        )
    if parts.scheme == "http" and parts.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise JudgmentError("unsupported_route", "Remote OpenRouter bases require HTTPS")
    path = parts.path.rstrip("/")
    if path.endswith("/api/v1"):
        path = path[:-3] + "/alpha/decisions"
    elif path.endswith("/api/alpha/decisions"):
        pass
    elif path in {"", "/api"}:
        path = "/api/alpha/decisions"
    else:
        raise JudgmentError(
            "unsupported_route",
            "Use an OpenRouter /api/v1 base or an explicit /api/alpha/decisions URL",
        )
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def build_payload(
    model: str,
    state: Any,
    questions: dict[str, Question],
    provider_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and snapshot all input; the byte screen is not an exact token counter."""
    if not isinstance(state, (str, dict, list)) or not isinstance(questions, dict) or not questions:
        raise JudgmentError("validation", "Supply state and at least one named question")
    if provider_options is not None and not isinstance(provider_options, dict):
        raise JudgmentError("validation", "Provider options must be a JSON object")
    if any(
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(value, (ChoiceQuestion, NoulQuestion, ScoreQuestion))
        for key, value in questions.items()
    ):
        raise JudgmentError("validation", "Questions require nonempty IDs and typed criteria")
    try:
        question_data = {
            key: type(value).model_validate(value.model_dump()).model_dump() for key, value in questions.items()
        }
    except ValueError:
        raise JudgmentError("validation", "Question criteria are invalid") from None
    payload = {
        "model": model,
        "state": state,
        "questions": question_data,
        "provider": {**(provider_options or {}), "zdr": True},
    }
    try:
        return json.loads(encode_payload(payload))
    except RecursionError:
        raise JudgmentError("validation", "Judgment input exceeds the JSON nesting limit") from None


def encode_payload(payload: dict[str, Any]) -> bytes:
    """Screen the actual wire envelope, including optional attribution, before dispatch."""
    try:
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise JudgmentError("validation", "Judgment state and options must contain finite JSON values") from None
    if len(encoded) > MAX_INPUT_BYTES:
        raise JudgmentError(
            "payload_too_large",
            f"Judgment request exceeds the conservative {MAX_INPUT_BYTES}-byte input cap",
        )
    return encoded


def status_failure(status: int, body: Any = None) -> str | None:
    """Classify HTTP outcomes without claiming a generic 404 proves a ZDR refusal."""
    if status == 400 and isinstance(body, dict):
        error = body.get("error")
        message = error.get("message") if isinstance(error, dict) else None
        # Observed TypeSafe rejection wrapped by OpenRouter; do not infer from free-form prose.
        if isinstance(message, str) and message.startswith("HTTP 400: "):
            try:
                detail = json.loads(message.removeprefix("HTTP 400: "), object_pairs_hook=_unique_object)
            except (ValueError, RecursionError):
                detail = None
            inner = detail.get("detail") if isinstance(detail, dict) else None
            if isinstance(inner, dict) and inner.get("error_type") == "max_tokens_exceeded":
                return "payload_too_large"
    return (
        None
        if status == 200
        else {
            400: "validation",
            401: "authentication",
            402: "insufficient_credit",
            403: "permission",
            404: "unsupported_route",
            413: "payload_too_large",
            429: "rate_limit",
            524: "ambiguous_timeout",
            529: "overloaded",
        }.get(status, "provider_error")
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result
