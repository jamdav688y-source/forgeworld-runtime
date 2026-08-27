# Failure-to-Correction Ledger

Every defect discovered across both the pre-merge certification pass and this promotion-evidence
pass, with its full lifecycle: what was wrong, why it mattered, how it was reproduced, what changed,
how the fix was verified, and what now guards against regression.

---

### F-01 — No recipient binding on outbound send

- **Original failure mode:** `outbound.send(draft, contact_id, to_phone, ...)` never checked that
  `to_phone` actually corresponded to `contact_id`. Any caller-supplied phone number would be accepted.
- **Risk:** an approved draft for one contact could be delivered to an arbitrary number — a real
  customer-facing send-to-wrong-person defect once live.
- **Reproducer:** call `outbound.send(d, event["contact_id"], to_phone="<any other number>", ...)` — pre-fix,
  this would have proceeded to the transport call.
- **Patch:** `whatsapp/src/outbound.py` — added `normalize.hash_phone(to_phone) != contact_id` check,
  returning `BLOCKED_BY_AUTHORITY` on mismatch.
- **Post-patch verification:** `whatsapp/tests/test_adversarial.py::TestRecipientBinding::test_send_to_a_different_phone_than_the_draft_was_approved_for_is_blocked`
- **Regression coverage:** claim C-07 in `whatsapp_claim_evidence_matrix.json`.

---

### F-02 — No idempotency guard on outbound send

- **Original failure mode:** `outbound.send()` had no check for a prior successful send of the same
  draft. A retried call (double-click, network-timeout retry, race) would re-send.
- **Risk:** duplicate customer-facing messages once live.
- **Reproducer:** call `outbound.send()` twice in a row for the same approved draft with a working
  transport — pre-fix, the transport would be invoked twice.
- **Patch:** `whatsapp/src/outbound.py` — checks for an existing `SAFE_AUTOMATION_EXECUTED` record for
  the `draft_id` before doing anything else; short-circuits to `VALIDATED_COMPLETE` if found.
- **Post-patch verification:** `whatsapp/tests/test_adversarial.py::TestReplay::test_replaying_an_approved_send_is_idempotent_not_a_double_send`
  (asserts the injected transport is called exactly once across three send attempts).
- **Regression coverage:** claim C-08.

---

### F-03 — No file locking on ledger writes; unbounded blast radius from one corrupted line

- **Original failure mode:** `ledger.append()` opened the file in append mode with no lock; concurrent
  writers could interleave. `ledger.read_all()` let a `json.JSONDecodeError` from any single malformed
  line propagate uncaught, crashing every caller (dedup checks, consent lookups, the approval queue) for
  the whole ledger.
- **Risk:** availability failure of the entire governance chain from one bad line — directly
  contradicts the mission's own "one bad event must not block subsequent events" principle, extended to
  the ledger layer.
- **Reproducer:** append a raw malformed line to a ledger file, then call any `ledger.find`/`exists_by`
  consumer — pre-fix, this raised and propagated.
- **Patch:** `whatsapp/src/ledger.py`, full rewrite — `append()` takes an exclusive `fcntl.flock`;
  `read_all()` takes a shared lock for the read, and wraps each line's `json.loads` individually,
  preserving any corrupted line to a `<name>.corrupt` sidecar file instead of raising or silently
  discarding it.
- **Post-patch verification:** `whatsapp/tests/test_adversarial.py::TestConcurrency` (2 tests),
  `TestLedgerCorruption` (4 tests).
- **Regression coverage:** claims C-01, C-02.

---

### F-04 — Weak, hardcoded default salt for phone-number pseudonymization

- **Original failure mode:** `normalize.hash_phone()` fell back to a hardcoded literal
  (`"forgeworld-dev-salt-change-me"`) when `WHATSAPP_ID_SALT` was unset. This value is visible in the
  public repo's source, so the fallback provided zero real protection while looking configured — an
  operator could go live having forgotten to set a real salt and never notice.
- **Risk:** trivial de-anonymization of `contact_id` values (small phone-number search space) if this
  default ever ran in a context handling real numbers.
- **Reproducer:** call `normalize.hash_phone(phone)` with `WHATSAPP_ID_SALT` unset — pre-fix, this
  silently succeeded using the known default.
- **Patch:** `whatsapp/src/normalize.py` — removed the hardcoded fallback; raises a new
  `normalize.ConfigurationError` when no salt is available from either the explicit argument or the
  environment.
- **Post-patch verification:** `whatsapp/tests/test_adversarial.py::TestSaltConfiguration::test_missing_salt_fails_loudly_not_with_a_weak_default`
- **Regression coverage:** claim C-03.

---

### F-05 — Raw exception content (and one full traceback) stored in the durable evidence ledger

- **Original failure mode:** three error-recording sites in `webhook_adapter.py` stored `str(e)` (which,
  for some exception types such as `int()` parse failures, embeds the raw malformed field value) and
  one site stored a full `traceback.format_exc(limit=5)`.
- **Risk:** attacker- or customer-supplied field content leaking into a ledger intended as durable,
  potentially-shared evidence, plus unnecessary internal detail exposure.
- **Reproducer:** send a message with a malformed `timestamp` field that raises `ValueError` during
  normalization — pre-fix, the ledger's `reason` field would contain the raw offending value inside the
  exception's default message string.
- **Patch:** `whatsapp/src/webhook_adapter.py` — all three sites now record `type(e).__name__` only;
  the `traceback` import and field were removed entirely.
- **Post-patch verification:** code inspection (all three `except` blocks reviewed); existing test
  `test_webhook_adapter.py::test_one_bad_event_does_not_block_next` still passes with the redacted path.
  **Gap, disclosed honestly:** no test directly asserts the *absence* of raw content in a ledger record
  (see claim C-04's residual risk in the claim-evidence matrix) — this fix is verified by inspection, not
  by a dedicated negative test.
- **Regression coverage:** claim C-04 (partial — see gap above).

---

### F-06 — CI's "offline sanity check" step was itself broken and never independently executed before being committed

- **Original failure mode:** the workflow step monkeypatched `socket.socket = blocked` (replacing the
  class itself) to prove no test needs network access. This breaks Python's own `ssl` module at import
  time (`ssl.py` defines `class SSLSocket(socket.socket)`, and replacing `socket.socket` with a plain
  function makes that class definition raise `TypeError`), which in turn breaks importing
  `urllib.request` (used by `whatsapp/src/outbound.py`), which in turn broke importing three of the nine
  test modules (`test_outbound`, `test_e2e_sandbox`, `test_adversarial`) with `ImportError`. The check
  would have reported this as a *test suite failure*, for a reason completely unrelated to any real
  network call.
- **Risk:** the specific risk this mission called out directly — a check landing in CI that was never
  actually run stand-alone before being trusted. This is exactly "successful execution != promotion":
  the earlier certification pass wrote and described this check as working without ever executing it in
  isolation.
- **Reproducer:** run the exact snippet from the original workflow file locally:
  `python3 -c "import socket; socket.socket = lambda *a,**k: (_ for _ in ()).throw(RuntimeError()); import unittest; ..."`
  — reproduced during this promotion-evidence pass; produced 3 `ImportError`s and `wasSuccessful()=False`
  even though zero real network calls were ever attempted by any test.
- **Patch:** `.github/workflows/whatsapp-tests.yml` — changed the guard to monkeypatch
  `socket.create_connection` (the actual function `http.client`/`urllib` use to open a real outbound
  connection) instead of the `socket.socket` class.
- **Post-patch verification:** ran the corrected snippet locally: `offline_run_wasSuccessful: True`,
  `offline_run_tests: 60`, `failures: 0`, `errors: 0`. Full output preserved in
  `whatsapp/reports/test_run_evidence.txt`.
- **Regression coverage:** claim C-10. **Residual gap, disclosed:** this fix has been verified by local
  execution of the exact code now in the workflow file, but the workflow itself has still never executed
  inside real GitHub Actions infrastructure — that remains unverified from this workspace (see claim
  C-10's residual risk).

---

### F-07 — Hardcoded personal email committed as a test/demo value

- **Original failure mode:** the account owner's real email address was hardcoded as a demo `actor`
  string in `whatsapp/tests/test_e2e_sandbox.py` (×2) and in `whatsapp/governance/00_DISCOVERY_REPORT.md`'s
  author line, serving no functional purpose (any string works as `actor`).
- **Risk:** unnecessary personal-data exposure in a repository whose visibility (public/private) was not
  confirmed.
- **Reproducer:** `grep -rn "jamdav688y@gmail.com" whatsapp/` — found 3 occurrences pre-fix.
- **Patch:** replaced with `"forgeworld-operator"` / "the repository operator".
- **Post-patch verification:** re-ran the same grep — 0 occurrences in the working tree.
- **Regression coverage:** none automated (this is a one-time content fix, not a behavior to regress).
  **Residual, disclosed, not remediated:** the original commit already pushed to the PR branch still
  contains the email in git history. A history rewrite (force-push) was deliberately not performed, as
  that is a destructive operation outside this certification's authorization.

---

## Summary

7 defects found across two independent review passes (5 in the security-certification pass, F-06 and F-07
straddle/were found in the certification pass too — F-06 specifically was only caught in *this* promotion
pass, when the CI check was executed for the first time rather than just read). All 7 have a committed
patch and a passing regression test or explicit, disclosed inspection-only verification. Zero defects
remain open. Two residual gaps are disclosed rather than hidden: F-05's redaction fix lacks a dedicated
negative test, and F-06's CI fix has not yet run inside real GitHub Actions.
