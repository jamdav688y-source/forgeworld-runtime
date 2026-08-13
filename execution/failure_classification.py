"""Execution-failure taxonomy and retry policy.

Motivated directly by the NRM incident: a bare "HTTP 403" must not be
filed under a generic network-failure bucket and retried forever. HTTP
status codes carry real semantic content -- 401 means authentication
failed, 403 means the request was authenticated but not authorized for
this specific operation -- and this classifier honors that distinction
instead of collapsing every non-2xx response into "network error".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from governance.types import FailureCategory

_TRANSIENT_KEYWORDS = (
    "connection timed out",
    "connection reset",
    "temporary failure",
    "could not connect",
    "network is unreachable",
    "operation timed out",
)
_PERMANENT_NETWORK_KEYWORDS = (
    "could not resolve host",
    "name or service not known",
    "no route to host",
)
_HTTP_STATUS_RE = re.compile(r"\bHTTP\s+(\d{3})\b", re.IGNORECASE)


@dataclass(frozen=True)
class RetryPolicy:
    retryable: bool
    max_attempts: int
    backoff: str  # "none" | "fixed" | "exponential"
    guidance: str


RETRY_POLICIES: dict[FailureCategory, RetryPolicy] = {
    FailureCategory.CAPABILITY_MISSING: RetryPolicy(False, 0, "none", "install/provision the missing capability; retrying without it changes nothing"),
    FailureCategory.AUTHORITY_DENIED: RetryPolicy(False, 0, "none", "do not endlessly retry; escalate to an approval/authority holder"),
    FailureCategory.AUTHORITY_UNKNOWN: RetryPolicy(False, 0, "none", "establish authority explicitly (policy lookup or human decision) before attempting again"),
    FailureCategory.APPROVAL_REQUIRED: RetryPolicy(False, 0, "none", "pause and escalate; do not attempt again until an approval is APPROVED"),
    FailureCategory.AUTHENTICATION_FAILED: RetryPolicy(False, 0, "none", "credentials are wrong or expired; retrying the same request will not help"),
    FailureCategory.NETWORK_TRANSIENT: RetryPolicy(True, 4, "exponential", "bounded retry permitted (matches this repo's documented 2s/4s/8s/16s backoff convention)"),
    FailureCategory.NETWORK_PERMANENT: RetryPolicy(False, 0, "none", "DNS/routing failure that a retry will not fix; needs configuration repair"),
    FailureCategory.RATE_LIMIT: RetryPolicy(True, 3, "exponential", "bounded retry with backoff, respecting any Retry-After hint"),
    FailureCategory.TARGET_REJECTED: RetryPolicy(False, 0, "none", "the target itself was rejected (bad ref, conflict, etc.); repair before retrying"),
    FailureCategory.VALIDATION_FAILED: RetryPolicy(False, 0, "none", "repair/revalidate rather than retrying the identical action"),
    FailureCategory.EVIDENCE_INSUFFICIENT: RetryPolicy(False, 0, "none", "gather stronger evidence; retrying execution does not strengthen evidence by itself"),
    FailureCategory.PROMOTION_DENIED: RetryPolicy(False, 0, "none", "promotion requires its own authority/evidence; re-attempting execution is unrelated"),
    FailureCategory.EXECUTION_ERROR: RetryPolicy(True, 1, "fixed", "one bounded retry for a plain unexpected error, then escalate"),
}


def retry_policy_for(category: FailureCategory) -> RetryPolicy:
    return RETRY_POLICIES[category]


def _matches_any(text: str, keywords: tuple) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def classify_failure(
    *,
    http_status: Optional[int] = None,
    stderr_text: Optional[str] = None,
    capability_missing: bool = False,
    approval_required: bool = False,
    authority_unknown: bool = False,
    evidence_insufficient: bool = False,
    promotion_denied: bool = False,
    validation_failed: bool = False,
) -> FailureCategory:
    """Classify a failure into the taxonomy. Explicit flags (capability_missing,
    approval_required, ...) take precedence because they represent
    decisions this codebase already made upstream (e.g. pipeline.py knows
    it halted on APPROVAL_REQUIRED without needing to guess from text).
    Otherwise falls back to interpreting http_status / stderr_text.
    """
    if capability_missing:
        return FailureCategory.CAPABILITY_MISSING
    if approval_required:
        return FailureCategory.APPROVAL_REQUIRED
    if authority_unknown:
        return FailureCategory.AUTHORITY_UNKNOWN
    if evidence_insufficient:
        return FailureCategory.EVIDENCE_INSUFFICIENT
    if promotion_denied:
        return FailureCategory.PROMOTION_DENIED
    if validation_failed:
        return FailureCategory.VALIDATION_FAILED

    if http_status is None and stderr_text:
        m = _HTTP_STATUS_RE.search(stderr_text)
        if m:
            http_status = int(m.group(1))

    if http_status is not None:
        if http_status == 401:
            return FailureCategory.AUTHENTICATION_FAILED
        if http_status == 403:
            # HTTP semantics: 403 means the request WAS authenticated but
            # is not authorized for this specific operation. This is the
            # NRM incident's exact status code -- do not reclassify it as
            # a network problem.
            return FailureCategory.AUTHORITY_DENIED
        if http_status == 429:
            return FailureCategory.RATE_LIMIT
        if http_status in (500, 502, 503, 504):
            return FailureCategory.NETWORK_TRANSIENT
        if http_status in (400, 404, 409, 410, 422):
            return FailureCategory.TARGET_REJECTED

    if stderr_text:
        if _matches_any(stderr_text, _PERMANENT_NETWORK_KEYWORDS):
            return FailureCategory.NETWORK_PERMANENT
        if _matches_any(stderr_text, _TRANSIENT_KEYWORDS):
            return FailureCategory.NETWORK_TRANSIENT

    return FailureCategory.EXECUTION_ERROR


def classify_git_push_failure(stderr_text: str, sibling_operation_succeeded_same_credentials: bool = False) -> FailureCategory:
    """Convenience wrapper for the exact shape of failure `git push` produces
    (a nonzero exit code with the real diagnostic text in stderr, no clean
    HTTP status object). `sibling_operation_succeeded_same_credentials`
    documents -- it does not change the classification, since a bare 403
    already means AUTHORITY_DENIED by HTTP semantics -- but it is recorded
    as corroborating evidence for the explanation.
    """
    category = classify_failure(stderr_text=stderr_text)
    return category
