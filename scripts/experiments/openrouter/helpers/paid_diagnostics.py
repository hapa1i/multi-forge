"""Allowlisted diagnostics for private probe receipts, including upstream error events."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterator


def envelope(raw: bytes) -> dict:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object.")
    return obj


def sse_objects(raw: bytes) -> Iterator[dict]:
    for frame in raw.replace(b"\r\n", b"\n").split(b"\n\n"):
        lines = frame.splitlines()
        payload = b"\n".join(line[5:].lstrip(b" ") for line in lines if line.startswith(b"data:"))
        if payload and payload != b"[DONE]":
            obj = envelope(payload)
            event = next((line[6:].strip() for line in reversed(lines) if line.startswith(b"event:")), None)
            if event in (b"error", b"response.failed"):
                obj["type"] = event.decode("ascii")
            yield obj


_SECRET = re.compile(r"\b(?:bearer|basic)\s+[^\s,;]+|\bsk-[\w-]+|\beyJ[\w.-]+", re.I)
_ASSIGNMENT = re.compile(
    r"""["']?\b(?:[\w-]*(?:api[_-]?key|token|password|secret)|authorization)\b["']?\s*[:=]""", re.I
)
_PRIVATE_PATH = re.compile(r"/(?:Users|home|private|tmp|var/folders)/[^\s'\"<>]+")
_ROUTING_INTRO = re.compile(
    r"\d{1,5} endpoints? out of \d{1,5} requested are available matching your guardrail restrictions and data policy\. "
    r"We removed them for the following reasons(?: \(an endpoint may have matched multiple reasons\))?:",
    re.I,
)
_ROUTING_POLICY = re.compile(
    r"\b(?:zdr|zero[ -]data[ -]retention|safety retention|data (?:collection|retention|polic(?:y|ies))|"
    r"guardrails?|privacy|training|(?:allowed|blocked) (?:models?|providers?)|"
    r"(?:model|provider) (?:allowlist|blocklist|restrictions?))\b",
    re.I,
)
# Reason sentences may include operator-supplied guardrail names. Only publish lines made of policy vocabulary.
_ROUTING_WORDS = set(
    """a above account all allow allowed allows allowlist an and are as available be because blocked blocklist but by
    can cannot collect collection configured data denied disabled disallowed do does eligible enabled endpoint endpoints
    enforce enforced exclude excluded excludes for from guardrail guardrails has have in include included ineligible
    is it key level list log logging match matched matches matching meet meets model models no non not of on only or our out permit
    permitted policies policy preference preferences privacy prompt prompts provider providers removed request
    requested require required requirement requirements requires restrict restricted restriction restrictions
    retain retained retains retention route routes safety satisfy selected setting settings source store stored stores
    support supported supports that the their them they this to train training unavailable under unsupported usage use
    used uses was were which wide with without would your zdr zero""".split()
)
_REASON_CODE_WORDS = _ROUTING_WORDS | {"author", "free", "ignored", "paid", "parameter", "region", "violation"}


def _routing_reasons(message: Any, private: list[str]) -> list[str]:
    if not isinstance(message, str) or len(message) > 4096:
        return []
    lines = message.splitlines()
    if not lines or not _ROUTING_INTRO.fullmatch(lines[0].strip()):
        return []
    reasons = []
    for line in lines[1:]:
        candidate = line.strip().removeprefix("- ").removeprefix("* ").removeprefix("• ").strip()
        # A slash between two counts such as 1/1 is the only slash allowed.
        counted = re.sub(r"\b(\d{1,5})/(\d{1,5})\b", r"\1 of \2", candidate)
        if not _ROUTING_POLICY.search(candidate) or not re.fullmatch(r"[A-Za-z0-9 ,.:()-]{1,180}", counted):
            continue
        words = re.findall(r"[a-z]+|[0-9]+", candidate.lower())
        if not all(word in _ROUTING_WORDS or (word.isdigit() and len(word) <= 5) for word in words):
            continue
        if any(value and value in candidate for value in private):
            continue
        if candidate not in reasons:
            reasons.append(candidate)
        if len(reasons) == 6:
            break
    return reasons


def _ineligibility_reasons(items: list, private: list[str]) -> list[dict]:
    reasons = []
    for item in items[:16]:
        if not isinstance(item, dict):
            continue
        code = item.get("reason")
        if not isinstance(code, str) or not 1 <= len(code) <= 96 or not set(code.split("-")) <= _REASON_CODE_WORDS:
            continue
        if any(value and value in code for value in private):
            continue
        reason: dict = {"reason": code}
        count = item.get("endpoint_count")
        if type(count) is int and 0 <= count <= 2**31 - 1:
            reason["endpoint_count"] = count
        if item.get("configure_url") == "https://openrouter.ai/settings/privacy":
            reason["configure_url"] = item["configure_url"]
        reasons.append(reason)
    return reasons


def _request_strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            if k not in {"model", "type", "role", "name"}:
                yield from _request_strings(v)
    elif isinstance(value, list):
        for item in value:
            yield from _request_strings(item)
    elif isinstance(value, str) and len(value) >= 8:
        yield value
        yield from (line for line in value.splitlines() if len(line) >= 8)


def _error_fields(error: dict, private_strings: list[str]) -> dict:
    def clean(text: Any) -> str:
        if not isinstance(text, str):
            return ""
        if len(text) > 4096:
            return "<oversized diagnostic omitted>"
        # A provider can embed the offending request, HTTP headers or a stack trace in its message.
        # Keep a single diagnostic line and cut off embedded structured data before promotion.
        for private in private_strings:
            if private:
                text = text.replace(private, "<redacted>")
        line = text.strip().split("\n", 1)[0].split("\r", 1)[0].split("{", 1)[0]
        line = re.split(r"\[\s*[\"'\{]|<html\b|<!doctype\b", line, maxsplit=1, flags=re.I)[0]
        line = "".join(c for c in line if c.isprintable())
        if match := _ASSIGNMENT.search(line):
            line = line[: match.start()] + "<redacted>"
        line = _SECRET.sub("<redacted>", line)
        line = _PRIVATE_PATH.sub("<path>", line)
        return line.strip()[:600]

    fields: dict = {}
    for k in ("message", "code", "type", "param"):
        value = error.get(k)
        if k == "code" and type(value) is int and abs(value) <= 2**32:
            fields[k] = value
        elif cleaned := clean(value):
            fields[k] = cleaned
    return fields


def provider_diagnostic(status: int, headers: dict, raw: bytes, body: dict | None, secret: str) -> dict | None:
    """Describe an error without retaining arbitrary provider payloads, headers or generated text."""
    media = headers.get("content-type", "").lower().split(";", 1)[0].strip()
    streaming = media == "text/event-stream" or bool(
        body and body.get("stream") and raw.lstrip().startswith((b"event:", b"data:"))
    )
    error: dict = {}
    format_name = "sse" if streaming else "json"
    event_type = None
    terminal_seen = False
    try:
        payloads = sse_objects(raw) if streaming else iter((envelope(raw),))
        for payload in payloads:
            response = payload.get("response")
            result = response if isinstance(response, dict) else payload
            detail = result.get("error")
            failed = payload.get("type") in ("error", "response.failed") or result.get("status") == "failed"
            if payload.get("type") in ("response.completed", "response.incomplete"):
                terminal_seen = True
            if detail or failed or (status >= 300 and not streaming):
                if isinstance(detail, dict):
                    error = detail
                elif isinstance(detail, str):
                    error = {"message": detail}
                else:
                    error = result
                event_type = payload.get("type") if payload.get("type") in ("error", "response.failed") else None
                break
        else:
            if status < 300 and (not streaming or terminal_seen):
                return None
            if streaming:
                format_name = "sse_without_terminal"
    except (ValueError, UnicodeError, RecursionError):
        format_name = "unparsed"
        if media == "text/plain" and status >= 300:
            format_name = "text"
            error = {"message": raw[:2048].decode("utf-8", "replace")}

    private = [secret, *sorted(set(_request_strings(body)), key=len, reverse=True)]
    diagnostic: dict = {"format": format_name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    request_id = headers.get("x-request-id", "")
    if request_id and re.fullmatch(r"[\w.:-]{1,128}", request_id):
        diagnostic["request_id"] = _error_fields({"message": request_id}, private)["message"]
    diagnostic.update(_error_fields(error, private))
    if format_name == "json" and status in {400, 403, 404, 422}:
        reasons = _routing_reasons(error.get("message"), private)
        if reasons:
            diagnostic["routing_reasons"] = reasons
    if event_type:
        diagnostic["event"] = event_type
    meta = error.get("metadata")
    if isinstance(meta, dict):
        if "ineligibility_reasons" in meta:
            items = meta["ineligibility_reasons"]
            if not isinstance(items, list):
                items = []
            kept = _ineligibility_reasons(items, private)
            diagnostic["ineligibility_reasons"] = kept
            if len(kept) < len(items):
                diagnostic["ineligibility_reasons_omitted"] = len(items) - len(kept)
        provider = _error_fields({"message": meta.get("provider_name")}, private).get("message")
        if provider:
            diagnostic["provider"] = provider
        detail = meta.get("raw")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (ValueError, RecursionError):
                detail = {"message": detail}
        if isinstance(detail, dict):
            nested = detail.get("error", detail)
            if isinstance(nested, str):
                nested = {"message": nested}
            if isinstance(nested, dict) and (fields := _error_fields(nested, private)):
                diagnostic["upstream"] = fields
    return diagnostic
