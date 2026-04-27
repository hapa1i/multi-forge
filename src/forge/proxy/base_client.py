"""
Abstract base class for all LLM provider clients.

This module defines the interface that all provider clients must implement,
ensuring consistent behavior across different LLM providers (OpenAI, Gemini, etc.).
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional

# Import canonical error types from core.llm.errors
from forge.core.llm.errors import LLMError


class AbstractLLMClient(ABC):
    """
    Base class for all LLM provider clients.

    All provider-specific clients must inherit from this class and implement
    the required methods. This ensures a consistent interface across providers.

    Methods accept and return data in OpenAI format for consistency, as it
    serves as both a universal intermediate format and the native format for
    OpenAI providers.
    """

    @abstractmethod
    async def create_completion(self, openai_request_dict: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        """
        Create a non-streaming completion.

        Args:
            openai_request_dict: Request in OpenAI format containing messages,
                                tools, model parameters, etc.
            request_id: Unique identifier for request tracking and logging

        Returns:
            Response in OpenAI format

        Raises:
            AuthenticationError: When authentication fails
            Exception: For other provider-specific errors
        """
        pass

    @abstractmethod
    async def create_streaming_completion(
        self, openai_request_dict: Dict[str, Any], request_id: str
    ) -> AsyncGenerator[str, None]:
        """
        Create a streaming completion.

        Args:
            openai_request_dict: Request in OpenAI format containing messages,
                                tools, model parameters, etc.
            request_id: Unique identifier for request tracking and logging

        Yields:
            Server-sent events (SSE) in OpenAI streaming format

        Raises:
            AuthenticationError: When authentication fails
            Exception: For other provider-specific errors
        """
        pass

    @abstractmethod
    async def count_tokens(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> int:
        """
        Count tokens for the given messages and optional tools.

        Args:
            messages: List of messages in OpenAI format
            tools: Optional list of tools in OpenAI format

        Returns:
            Total token count

        Raises:
            Exception: If token counting fails
        """
        pass


class ToolCallError(LLMError):
    """
    Raised when a tool call fails, formatted for LLM consumption.

    This error provides structured information that helps LLMs understand
    and potentially fix tool-related issues.
    """

    def __init__(self, error_type: str, tool_name: str, details: Dict[str, Any]):
        """
        Initialize a tool call error with LLM-friendly formatting.

        Args:
            error_type: Category of error (MISSING_PARAM, SCHEMA_MISMATCH, etc.)
            tool_name: Name of the tool that failed
            details: Additional context including expected/actual values and suggestions
        """
        self.error_type = error_type
        self.tool_name = tool_name
        self.details = details

        # Build LLM-friendly message
        message_parts = [f"Tool call failed [{error_type}]: {tool_name}"]

        if error_type == "MISSING_PARAM":
            if "param" in details:
                message_parts.append(f"Missing required parameter: '{details['param']}'")
            if "expected" in details:
                message_parts.append(f"Expected structure: {details['expected']}")
            if "actual" in details:
                message_parts.append(f"Received: {details['actual']}")

        elif error_type == "SCHEMA_MISMATCH":
            if "message" in details:
                message_parts.append(details["message"])
            if "expected_type" in details:
                message_parts.append(f"Expected type: {details['expected_type']}")
            if "actual_type" in details:
                message_parts.append(f"Actual type: {details['actual_type']}")

        elif error_type == "INVALID_FORMAT":
            if "message" in details:
                message_parts.append(details["message"])
            if "field" in details:
                message_parts.append(f"Invalid field: '{details['field']}'")

        # Add suggestion if available
        if "suggestion" in details:
            message_parts.append(f"Suggestion: {details['suggestion']}")

        super().__init__("\n".join(message_parts))


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
