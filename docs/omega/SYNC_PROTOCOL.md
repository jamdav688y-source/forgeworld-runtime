# Synchronization Protocol — `fw-omega-sync-v1`

Implementation: `omega/sync.py`, `omega/reconcile.py`, `omega/discovery.py`.
Tests: `omega/tests/test_sync.py`, `test_e2e.py`, `test_tasks_recovery.py`.

## Goals

Mutual authentication · encryption · per-node monotonic sequences · idempotent import ·
integrity verification · missing-event discovery · resume after interruption · explicit
conflicts · deterministic reconciliation · no silent destructive merge · **no execution on sync**
· no requirement that both devices are online at the same time.

## 1. Pairing (once, human-confirmed)

1. Each device prints an offer (`omega offer`): `FWPAIR1:` + base64url(canonical
   `{device_id, label, sign_pub (Ed25519), kx_pub (X25519), nonce}`). `device_id` must equal
   `sha256(sign_pub)[:32]`.
2. The operator carries each offer to the other device.
3. Both compute a 6-digit **SAS** = `sha256(domain "pairing-sas", both offers sorted by
   device_id) mod 10^6`. The operator checks the two screens show the same digits and types them.
   A substituted key changes the SAS (`test_man_in_the_middle_offer_changes_the_sas`).
4. Each device records the peer with a **privacy clearance** (`max_privacy`, default `PRIVATE`)
   and a `DEVICE_LOCAL` `PEER_PAIRED` event. Pairing requires a `human:` actor.

## 2. Live session handshake

```
I → R  HELLO      {v, device_id_I, eph_I, nonce_I(32B), to}
R:     refuse if: wrong protocol, `to` ≠ R, I unknown, I revoked, nonce_I seen before (REPLAY)
R → I  HELLO_ACK  {device_id_R, eph_R, nonce_R, sig_R = Ed25519_R("R|" + T)}
I:     refuse if: R unknown / revoked / not the expected peer, bad sig_R, nonce_R seen before
I → R  AUTH       {sig_I = Ed25519_I("I|" + T)}
R → I  READY      (first encrypted frame: proves key agreement)
T = sha256(domain "sync-transcript", [HELLO, {device_id_R, eph_R, nonce_R}])
(k_I→R ‖ k_R→I) = HKDF-SHA256(X25519(eph_I, eph_R), salt = nonce_I‖nonce_R, info = "fw-omega-sync-v1|" + T)
```

* Both identities are bound to the transcript by signatures over fresh nonces from **both**
  sides, so a recorded handshake cannot be replayed (`test_replayed_hello_nonce_is_refused`,
  `test_impostor_with_copied_device_id_fails_authentication`).
* Ephemeral X25519 gives forward secrecy for session traffic.
* Frames: ChaCha20-Poly1305 with a 96-bit counter nonce and a direction label as associated
  data. The receiver requires counter = previous + 1: a replayed, reordered or dropped frame
  ends the session (`FRAME_REPLAYED_OR_REORDERED`); a modified one fails authentication.

## 3. Session

```
both   VECTOR {vector: {device_id: max contiguous seq}, withheld: [ids whose payload I lack]}
I      repeat: BATCH {events[≤100], artifacts{sha: b64}} → R imports → ACK {vector, problems}
I      END
R      the same in the other direction, then END
```

* **Missing-event discovery** = vector difference. The sender sends every event the peer lacks,
  in the sender's local order, which respects causality (a node only stores an event after its
  parents).
* **Clearance**: payloads above the peer's `max_privacy`, and every `DEVICE_LOCAL` payload, are
  sent header-only (WITHHELD). Headers always go, so per-device chains stay contiguous and
  verifiable. When clearance is raised later, WITHHELD payloads are backfilled (hash-checked).
* **Import** (`Node.import_event`, one transaction per event): schema + governance validation →
  signer known and not revoked → signature over the recomputed id → result:
  `DUPLICATE` (idempotent) · `BACKFILLED` · `EQUIVOCATION` (same device+seq, different event:
  recorded as a conflict and quarantined) · `GAP` (seq not contiguous or parent missing:
  refused now, re-sent later) · `REJECTED` (with a code, quarantined) · `IMPORTED`.
* **Progress guard**: if an ACK shows no progress, the sender stops instead of looping.
* **Interruption**: every imported event is already committed. A dropped connection ends the
  session with a `SYNC_INTERRUPTED` receipt; the next session recomputes vectors and continues.
  Tested at 5 fault positions on both sides (`test_interrupted_sync_resumes_without_loss_or_duplication`)
  and with the process killed mid-import (`test_recovery_after_kill_during_import`).
* **After every session** (complete or not): reconciliation runs and a receipt is written.
  **Tasks are never executed by sync** (`test_sync_never_executes_and_remote_authorization_does_not_count`).

## 4. Offline bundles (store and forward)

For when the devices are never online together (USB, SD card, file share):

```
header = {v: "fw-omega-bundle-v1", from, to, nonce(32B), eph (X25519), events}
key    = HKDF-SHA256(X25519(eph, recipient kx_pub), salt = nonce, info = "fw-omega-bundle-v1|from|to")
ct     = ChaCha20-Poly1305(key, 0^96, canonical({events, artifacts, vector}), aad = canonical(header))
file   = {header + ct_sha256, sig = Ed25519_from(digest(header)), ct}
```

The recipient refuses a wrong recipient, an unknown or revoked sender, a bad signature, a
ciphertext hash mismatch, a failed decryption, and a **bundle nonce it has seen before**
(`REPLAY_DETECTED`). Import is the same idempotent path as a live session. The sender exports
from the last vector it knows the peer has (`--full` resends everything; duplicates are no-ops).

## 5. Reconciliation (deterministic, no last-writer-wins)

Mutable state is keyed (`fact|<subject>|<attribute>`, `commitment|<id>|status`,
`contact|<id>|display_name`). For each key: **heads** = assertions not in the causal ancestry
of another assertion of the key. One head, or heads that agree → `RESOLVED`. Heads that disagree
→ `CONFLICTED`: value `None`, an explicit conflict row, a `CONFLICTS_RECONCILED` receipt, and
draft logic sees `CONFLICTED`, never a guessed value. A human resolves by writing
`CONFLICT_RESOLVED` whose parents are the conflicting heads, so it dominates them on every
node. Writers add the current heads of a key as parents, so sequential edits never conflict.
The result does not depend on import order (`test_resolution_is_independent_of_import_order`).

**Device-local vs shared**: events form the shared evidence view; `local_exec` (task execution
state), `peers`, `seen_nonces` and `quarantine` are per device and never synced.

## 6. Discovery (optional)

`omega announce` broadcasts a signed UDP beacon `{device_id, port, nonce}` on port 47474. A
listener accepts it only from a paired, non-revoked peer, with a valid signature and an unseen
nonce. Discovery is a hint only: the handshake authenticates again.

## Transports

TCP (`omega serve` / `omega sync`; binds loopback unless the operator passes a LAN address),
in-process pipes (tests), files (bundles). Frames are length-prefixed and capped at 16 MiB;
artifacts are capped at 8 MiB.
