"""Registered, independently testable intent handlers."""

from bodynote_agent.handlers.contracts import (
    CorrectionCommand,
    DomainHandler,
    HandlerResult,
)

__all__ = ["CorrectionCommand", "DomainHandler", "HandlerResult"]
