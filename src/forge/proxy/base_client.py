"""Proxy client errors shared by the adapter and server."""

from forge.core.llm.errors import LLMError


class ProxyStreamError(LLMError):
    """Raised during streaming when an error occurs.

    This error carries structured information that allows the proxy server
    to return appropriate HTTP status codes and OpenAI-compatible error responses
    instead of generic 500 errors.

    Common error types and their HTTP mappings:
    - "authentication_error" -> 401
    - "rate_limit_error" -> 429
    - "invalid_request_error" -> 400
    - "api_error" -> 500
    """

    # Standard error type to HTTP status code mapping
    ERROR_STATUS_MAP = {
        "authentication_error": 401,
        "rate_limit_error": 429,
        "invalid_request_error": 400,
        "permission_error": 403,
        "not_found_error": 404,
        "api_error": 500,
    }

    def __init__(
        self,
        message: str,
        error_type: str = "api_error",
        status_code: int | None = None,
    ) -> None:
        """Initialize a proxy stream error.

        Args:
            message: Human-readable error message.
            error_type: OpenAI-compatible error type for client handling.
            status_code: HTTP status code override. If None, derived from error_type.
        """
        self.error_type = error_type
        self.status_code = status_code or self.ERROR_STATUS_MAP.get(error_type, 500)
        super().__init__(message)
