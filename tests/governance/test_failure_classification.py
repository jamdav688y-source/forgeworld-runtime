"""Failure-taxonomy and retry-policy tests.

Covers mission section 19 bullets:
  - transient network retry
  - 403 authorization failure
"""
from execution.failure_classification import classify_failure, retry_policy_for
from governance.types import FailureCategory


def test_bare_http_403_classifies_as_authority_denied_not_network():
    category = classify_failure(http_status=403)
    assert category == FailureCategory.AUTHORITY_DENIED


def test_git_push_403_stderr_text_classifies_as_authority_denied():
    """The actual NRM incident's stderr text, verbatim."""
    stderr = (
        "error: RPC failed; HTTP 403 curl 22 The requested URL returned error: 403\n"
        "send-pack: unexpected disconnect while reading sideband packet\n"
        "fatal: the remote end hung up unexpectedly"
    )
    category = classify_failure(stderr_text=stderr)
    assert category == FailureCategory.AUTHORITY_DENIED


def test_401_is_authentication_not_authority():
    assert classify_failure(http_status=401) == FailureCategory.AUTHENTICATION_FAILED


def test_connection_timeout_is_network_transient():
    category = classify_failure(stderr_text="curl: (28) Operation timed out after 30000 milliseconds")
    assert category == FailureCategory.NETWORK_TRANSIENT
    policy = retry_policy_for(category)
    assert policy.retryable is True
    assert policy.max_attempts >= 1


def test_dns_failure_is_network_permanent_not_transient():
    category = classify_failure(stderr_text="curl: (6) Could not resolve host: github.example.invalid")
    assert category == FailureCategory.NETWORK_PERMANENT
    assert retry_policy_for(category).retryable is False


def test_429_is_rate_limit_and_retryable():
    category = classify_failure(http_status=429)
    assert category == FailureCategory.RATE_LIMIT
    assert retry_policy_for(category).retryable is True


def test_authority_denied_is_not_retryable():
    policy = retry_policy_for(FailureCategory.AUTHORITY_DENIED)
    assert policy.retryable is False
    assert policy.max_attempts == 0


def test_validation_failed_is_not_retryable_identically():
    policy = retry_policy_for(FailureCategory.VALIDATION_FAILED)
    assert policy.retryable is False


def test_capability_missing_flag_takes_precedence_over_stderr_guess():
    category = classify_failure(capability_missing=True, stderr_text="HTTP 403 nonsense that would otherwise match")
    assert category == FailureCategory.CAPABILITY_MISSING


def test_server_5xx_is_transient():
    assert classify_failure(http_status=503) == FailureCategory.NETWORK_TRANSIENT


def test_404_on_target_is_target_rejected_not_network():
    assert classify_failure(http_status=404) == FailureCategory.TARGET_REJECTED


def test_every_category_has_a_retry_policy():
    for category in FailureCategory:
        policy = retry_policy_for(category)
        assert policy is not None
        assert isinstance(policy.retryable, bool)
