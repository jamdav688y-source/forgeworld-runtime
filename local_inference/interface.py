"""Local Inference Seam: a provider-neutral contract for invoking a local
model, and nothing else.

MISSION: LOCAL-INFERENCE-SEAM-001.

ROUTING LAW (the reason this module exists at this specific tier, and not
earlier or later):

    deterministic -> retrieval -> existing capability -> composed
    capability -> LOCAL INFERENCE -> synthesized capability -> optional
    frontier inference -> human judgment.

This module is the "local inference" link in that chain. Nothing here
decides WHEN to invoke local inference instead of an earlier tier -- that
decision belongs to router/mission_router.py (see the module docstring
there and ROUTER_TIER below). This module only makes local inference
*invocable* once something upstream has already decided to reach for it.

PROVIDER-NEUTRALITY LAW: this file contains no Ollama-specific code, no
Ollama-specific defaults, and no import of anything Ollama-specific.
`LocalInferenceProvider` is a Protocol; `local_inference/ollama_adapter.py`
is one implementation of it, not the architecture. A second provider
(llama.cpp, LM Studio, vLLM, ...) is a second file implementing the same
Protocol -- this module does not change.

TWO LAWS THIS MODULE ENFORCES STRUCTURALLY (not by convention, not by
caller discipline):

  1. MODEL OUTPUT IS NOT EVIDENCE. `InferenceResult.evidence_status` is a
     read-only property that always returns NOT_EVIDENCE -- it cannot be
     constructed, overridden, or upgraded by any caller. Promoting model
     output to evidence (e.g. attaching it to an evidence_envelope
     mission or trajectory record) is a separate, explicit, later act
     performed by other code that has its own authority to do so; nothing
     in this module performs or implies that act.

  2. INVOCATION DOES NOT IMPLY TRUTH OR PROMOTION. `interpretation_status`
     and `promotion_status` are likewise fixed, read-only properties. A
     successful COMPLETED invocation only means a local process produced
     output text before its timeout -- it does not mean the output is
     correct, verified, or acted upon.

FAILURE LAW: `run_inference()` never raises for an expected failure mode
(unreachable provider, timeout, provider error, invalid request). It
always returns a structured InferenceResult with an honest status --
mirroring capabilities/discover.py (which reports UNREACHABLE/TIMEOUT
rather than raising) and router/mission_router.py (which returns a
"queued_no_reachable_capability" decision rather than raising). An
unreachable provider is *never* silently substituted or retried against
a different provider by this module -- that composition, if wanted, is a
router-level decision, not this seam's.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from evidence_envelope import envelope  # noqa: E402 -- reused only for validate_mission_id's identifier contract

# ---------------------------------------------------------------------------
# The tier this module occupies in the inference-economy routing chain.
# Read by router/mission_router.py (or its future ROUTER_V2 layer) to place
# local inference correctly; not consumed by anything in this file.
# ---------------------------------------------------------------------------
ROUTING_CHAIN = (
    "deterministic",
    "retrieval",
    "existing_capability",
    "composed_capability",
    "local_inference",
    "synthesized_capability",
    "frontier_inference",
    "human_judgment",
)
ROUTER_TIER = "local_inference"

LOCALITY_LOCAL_ONLY = "local_only"

# -- failure/outcome states, in the same honest, non-euphemistic vocabulary
# capabilities/discover.py already uses (UNREACHABLE, TIMEOUT). -----------
STATUS_COMPLETED = "COMPLETED"
STATUS_TIMEOUT = "TIMEOUT"
STATUS_UNREACHABLE = "UNREACHABLE"
STATUS_PROVIDER_ERROR = "PROVIDER_ERROR"
STATUS_INVALID_REQUEST = "INVALID_REQUEST"
_TERMINAL_STATUSES = (
    STATUS_COMPLETED, STATUS_TIMEOUT, STATUS_UNREACHABLE,
    STATUS_PROVIDER_ERROR, STATUS_INVALID_REQUEST,
)

# -- fixed, non-overridable classifications every InferenceResult carries.
NOT_EVIDENCE = "NOT_EVIDENCE_MODEL_OUTPUT"
UNVERIFIED_MODEL_OUTPUT = "UNVERIFIED_MODEL_OUTPUT"
NOT_PROMOTED = "NOT_PROMOTED"


class LocalInferenceError(Exception):
    """Base error for this module. Only raised for programmer misuse
    (e.g. constructing an InferenceResult with an invalid status) --
    never for an expected runtime failure, which is represented as a
    structured InferenceResult instead."""


@dataclass(frozen=True)
class InferenceRequest:
    """A structured request for local inference. Every field is explicit;
    nothing is inferred or defaulted to an Ollama-shaped assumption."""

    request_id: str
    provider: str
    model: str
    prompt: str
    timeout_seconds: float
    locality: str = LOCALITY_LOCAL_ONLY
    parameters: dict = field(default_factory=dict)
    requested_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@dataclass(frozen=True)
class InferenceResult:
    """A structured result. `evidence_status`, `interpretation_status`,
    and `promotion_status` are properties, not constructor fields -- see
    the module docstring's two structural laws. They are the same for
    every result, success or failure, so a caller can never construct a
    result that claims otherwise."""

    request_id: str
    status: str
    provider: str
    model: str
    locality: str
    output_text: Optional[str]
    error_detail: Optional[str]
    started_at: str
    completed_at: str
    duration_seconds: float
    reachability_evidence: Optional[str] = None

    def __post_init__(self):
        if self.status not in _TERMINAL_STATUSES:
            raise LocalInferenceError(f"status {self.status!r} is not one of {_TERMINAL_STATUSES}")
        if self.status == STATUS_COMPLETED and self.output_text is None:
            raise LocalInferenceError("status COMPLETED requires output_text to be set")
        if self.status != STATUS_COMPLETED and self.output_text is not None:
            raise LocalInferenceError(f"status {self.status!r} must not carry output_text")

    @property
    def evidence_status(self) -> str:
        return NOT_EVIDENCE

    @property
    def interpretation_status(self) -> str:
        return UNVERIFIED_MODEL_OUTPUT

    @property
    def promotion_status(self) -> str:
        return NOT_PROMOTED

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "locality": self.locality,
            "output_text": self.output_text,
            "error_detail": self.error_detail,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "reachability_evidence": self.reachability_evidence,
            "evidence_status": self.evidence_status,
            "interpretation_status": self.interpretation_status,
            "promotion_status": self.promotion_status,
        }


class LocalInferenceProvider(Protocol):
    """The contract every adapter (Ollama, or anything later) implements.
    Nothing in this Protocol, or in run_inference() below, references a
    specific provider by name."""

    provider_id: str

    def reachability_check(self) -> dict:
        """Return {"reachable": bool, "confidence": float, "evidence": str,
        "evidence_level": Optional[str]}. Must not raise; must not block
        longer than a bounded, short probe; must not start a service."""
        ...

    def invoke(self, request: "InferenceRequest") -> "InferenceResult":
        """Perform one bounded local invocation and return a structured
        InferenceResult. Must respect request.timeout_seconds and must
        never raise for an expected failure (timeout, non-zero exit,
        malformed provider output) -- translate those into the
        appropriate InferenceResult status instead."""
        ...


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _validate_request(request: InferenceRequest) -> Optional[str]:
    """Return an error message if `request` is malformed, else None."""
    try:
        envelope.validate_mission_id(request.request_id)
    except envelope.InvalidMissionIdError as exc:
        return f"request_id invalid: {exc}"
    if not isinstance(request.provider, str) or not request.provider.strip():
        return "provider must be a non-empty string"
    if not isinstance(request.model, str) or not request.model.strip():
        return "model must be a non-empty string"
    if not isinstance(request.prompt, str) or not request.prompt.strip():
        return "prompt must be a non-empty string"
    if request.locality != LOCALITY_LOCAL_ONLY:
        return f"locality must be {LOCALITY_LOCAL_ONLY!r} in this seam, got {request.locality!r}"
    if not isinstance(request.timeout_seconds, (int, float)) or request.timeout_seconds <= 0:
        return "timeout_seconds must be a positive number"
    return None


def _invalid_result(request: InferenceRequest, reason: str, started_at: str) -> InferenceResult:
    completed_at = _now()
    return InferenceResult(
        request_id=request.request_id if isinstance(request.request_id, str) else "UNKNOWN",
        status=STATUS_INVALID_REQUEST,
        provider=request.provider,
        model=request.model,
        locality=request.locality,
        output_text=None,
        error_detail=reason,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=0.0,
        reachability_evidence=None,
    )


def run_inference(request: InferenceRequest, provider: LocalInferenceProvider) -> InferenceResult:
    """Provider-neutral orchestration: validate, check reachability
    honestly, then (only if reachable) delegate to provider.invoke().

    An unreachable provider is reported as unreachable and provider.invoke()
    is never called -- there is no silent fallback, retry, or substitution
    here. Composing "try local inference, then fall back to X" is a
    router-level decision that belongs above this function, not inside it.
    """
    started_at = _now()

    reason = _validate_request(request)
    if reason is not None:
        return _invalid_result(request, reason, started_at)

    if request.provider != getattr(provider, "provider_id", None):
        return _invalid_result(
            request,
            f"request.provider {request.provider!r} does not match "
            f"provider.provider_id {getattr(provider, 'provider_id', None)!r}",
            started_at,
        )

    reach = provider.reachability_check()
    if not reach.get("reachable", False):
        completed_at = _now()
        return InferenceResult(
            request_id=request.request_id,
            status=STATUS_UNREACHABLE,
            provider=request.provider,
            model=request.model,
            locality=request.locality,
            output_text=None,
            error_detail=f"provider {request.provider!r} is not reachable",
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=0.0,
            reachability_evidence=reach.get("evidence"),
        )

    result = provider.invoke(request)
    if result.request_id != request.request_id:
        raise LocalInferenceError(
            "provider.invoke() returned a result for a different request_id "
            f"({result.request_id!r} != {request.request_id!r})"
        )
    return result
