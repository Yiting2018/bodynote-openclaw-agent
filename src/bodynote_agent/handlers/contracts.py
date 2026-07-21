from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable


@dataclass(frozen=True)
class HandlerResult:
    """Stable result envelope shared by every record-producing Handler."""

    intent: str
    event_type: str
    occurred_at: str
    payload: dict[str, Any]
    confidence: float
    required_fields: tuple[str, ...] = field(default_factory=tuple)
    ambiguities: tuple[str, ...] = field(default_factory=tuple)
    follow_up_question: str | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)
    handler: str = ""
    intent_candidates: tuple[str, ...] = field(default_factory=tuple)

    def routed(
        self,
        *,
        handler: str,
        occurred_at: str,
        payload: dict[str, Any],
        candidates: tuple[str, ...],
        ambiguities: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> "HandlerResult":
        return replace(
            self,
            handler=handler,
            occurred_at=occurred_at,
            payload=payload,
            intent_candidates=candidates,
            ambiguities=ambiguities,
            warnings=warnings,
        )


@dataclass(frozen=True)
class DomainHandler:
    name: str
    intent: str
    event_type: str
    required_fields: tuple[str, ...]
    parser: Callable[[str], HandlerResult | None]


@dataclass(frozen=True)
class CorrectionCommand:
    action: str
    target_event_type: str | None = None
    payload_patch: dict[str, Any] = field(default_factory=dict)
    occurred_at_text: str | None = None
    confidence: float = 0.9
    ambiguities: tuple[str, ...] = field(default_factory=tuple)


def result(
    event_type: str,
    payload: dict[str, Any],
    confidence: float,
    *,
    intent: str | None = None,
    required_fields: tuple[str, ...] = (),
    follow_up: str | None = None,
    warnings: tuple[str, ...] = (),
    ambiguities: tuple[str, ...] = (),
) -> HandlerResult:
    return HandlerResult(
        intent=intent or f"record_{event_type}",
        event_type=event_type,
        occurred_at="",
        payload=payload,
        confidence=confidence,
        required_fields=required_fields,
        ambiguities=ambiguities,
        follow_up_question=follow_up,
        warnings=warnings,
    )
