"""V17 NDM exception / failure classification."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from .recent_action import RecentActionContractError


RECOVERABLE_REASONING_FAILURE = "RECOVERABLE_REASONING_FAILURE"
RUNTIME_CONTRACT_VIOLATION = "RUNTIME_CONTRACT_VIOLATION"
PROGRAMMING_ERROR = "PROGRAMMING_ERROR"
TRANSIENT_PROVIDER_FAILURE = "TRANSIENT_PROVIDER_FAILURE"
INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"

FALLBACK_ELIGIBLE = frozenset({
    RECOVERABLE_REASONING_FAILURE,
    TRANSIENT_PROVIDER_FAILURE,
    INVALID_MODEL_OUTPUT,
})

BLOCK_CLASSES = frozenset({
    RUNTIME_CONTRACT_VIOLATION,
    PROGRAMMING_ERROR,
})


class NDMRuntimeContractViolation(RuntimeError):
    code = "NDM_RUNTIME_CONTRACT_VIOLATION"

    def __init__(self, message: str, *, evidence: Optional[dict] = None):
        super().__init__(message)
        self.evidence = dict(evidence or {})


class SafeFallbackFailure(RuntimeError):
    code = "SAFE_FALLBACK_FAILURE"

    def __init__(self, message: str, *, evidence: Optional[dict] = None):
        super().__init__(message)
        self.evidence = dict(evidence or {})


@dataclass
class ClassifiedFailure:
    error_id: str
    error_class: str
    module: str
    schema_version: Any = None
    input_shape: str = ""
    reasoning_id: str = ""
    decision_transaction_id: str = ""
    cycle: Any = None
    turn: Any = None
    message: str = ""
    fallback_eligible: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def classify_exception(
    exc: BaseException,
    *,
    module: str = "",
    reasoning_id: str = "",
    decision_transaction_id: str = "",
    cycle: Any = None,
    turn: Any = None,
) -> ClassifiedFailure:
    msg = str(exc)
    input_shape = getattr(exc, "input_shape", "") or ""
    schema_version = getattr(exc, "schema_version", None)
    mod = getattr(exc, "module", None) or module or type(exc).__module__

    if isinstance(exc, RecentActionContractError) or isinstance(exc, NDMRuntimeContractViolation):
        error_class = RUNTIME_CONTRACT_VIOLATION
    elif isinstance(exc, SafeFallbackFailure):
        error_class = RUNTIME_CONTRACT_VIOLATION  # fallback failure blocks; counted separately
    elif isinstance(exc, (AttributeError, TypeError, KeyError)):
        # Internal contract / programming — never SAFE_LEGACY
        error_class = PROGRAMMING_ERROR
        if "list" in msg and "get" in msg:
            input_shape = input_shape or "list_get_mismatch"
    elif type(exc).__name__ in {"TimeoutError", "ConnectionError"} or "timeout" in msg.lower():
        error_class = TRANSIENT_PROVIDER_FAILURE
    elif type(exc).__name__ in {"JSONDecodeError", "ValueError"} and "model" in msg.lower():
        error_class = INVALID_MODEL_OUTPUT
    elif type(exc).__name__ == "UnexplainedActionError":
        # existing: fail-closed REJECT, not SAFE_LEGACY via this classifier path
        error_class = INVALID_MODEL_OUTPUT
        # but unbound/unexplained keep existing raise paths; mark not fallback by policy in decide
    else:
        # Default: treat unknown as recoverable reasoning only if explicitly tagged;
        # otherwise programming-safe block for Attribute-like internals already handled.
        # Remaining generic Exception from PL/model path → recoverable.
        error_class = RECOVERABLE_REASONING_FAILURE

    # Unexplained / knowledge / unbound must not become SAFE_LEGACY via classifier
    name = type(exc).__name__
    if name in {"UnexplainedActionError", "KnowledgeBoundaryError", "UnboundDecisionCommit", "FallbackUnboundedError"}:
        error_class = PROGRAMMING_ERROR if name == "FallbackUnboundedError" else error_class
        if name == "FallbackUnboundedError":
            error_class = RUNTIME_CONTRACT_VIOLATION

    fallback_eligible = error_class in FALLBACK_ELIGIBLE and name not in {
        "UnexplainedActionError",
        "KnowledgeBoundaryError",
        "UnboundDecisionCommit",
        "FallbackUnboundedError",
        "NDMRuntimeContractViolation",
        "SafeFallbackFailure",
        "RecentActionContractError",
    }

    return ClassifiedFailure(
        error_id=f"err_{uuid.uuid4().hex[:12]}",
        error_class=error_class,
        module=str(mod),
        schema_version=schema_version,
        input_shape=str(input_shape),
        reasoning_id=str(reasoning_id or ""),
        decision_transaction_id=str(decision_transaction_id or ""),
        cycle=cycle,
        turn=turn,
        message=msg,
        fallback_eligible=fallback_eligible and error_class in FALLBACK_ELIGIBLE,
    )
