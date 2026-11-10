# Recovery and Rollback Procedures

## What survives a crash

Every material transition is one SQLite transaction (WAL, `synchronous=FULL`). A killed process
leaves the whole transition or none of it. `test_recovery_after_process_killed_mid_transaction`
and `test_recovery_after_kill_during_import` kill a real process (`os._exit`) inside the
transaction and verify the store afterwards.

## After a crash or power loss

1. `omega verify`: recomputes every event id, signature, payload hash, per-device chain, the
   receipt chain and `PRAGMA integrity_check`. Exit 0 means the node is consistent.
2. `omega task-recover`: tasks left RUNNING with an expired lease move to:
   * DONE, if their result event was already committed;
   * PENDING, for internal tasks (at most 3 attempts, then FAILED);
   * **NEEDS_REVIEW**, for external tasks. The side effect may already have happened, so a human
     checks before anything runs again.
3. Re-run sync (`omega sync …` or a bundle). Interrupted sessions resume from vectors; duplicates
   are no-ops.

## If `omega verify` reports problems

| Problem | Meaning | Action |
|---|---|---|
| `SQLITE_INTEGRITY` | file-level corruption | restore the latest backup (below), then sync from the peer to recover newer events |
| `SIGNATURE_INVALID` / `EVENT_ID_MISMATCH` / `PAYLOAD_HASH_MISMATCH` | a row was altered outside omega | treat the node as compromised: keep a copy for forensics, restore from backup or rebuild from the peer |
| `CHAIN_BROKEN` | a device's sequence has a hole or fork | export diagnostics (`omega diag --out d.json`) and check `conflicts` for EQUIVOCATION |
| `RECEIPT_*` | the receipt chain was altered | same as signature failures |

## Backups

`omega backup --out <file>` uses SQLite's online backup API, which is consistent while the node
runs. Back up **the node home separately**: the `identity/` directory holds the device keys,
which the database backup does not contain. Keep the backup on the device or encrypted storage:
it contains private records.

**Restoring:** stop omega, copy `node.db` from the backup into the node home (keep the same
`identity/`), run `omega verify`, then sync with the peer. The peer re-sends every event the
restored node lacks, including events the node itself wrote after the backup, because the peer
holds them signed (`test_restore_from_backup_then_resync_recovers_own_events`). These
events come back marked IMPORTED, so a `TASK_AUTHORIZED` among them no longer counts as a local
authorization: re-authorize any task you still want to run. Events this device wrote after the backup that **never reached the peer** are
lost. The device then writes new events with sequence numbers the peer already holds, which the
peer flags as **EQUIVOCATION**. Restore only after syncing, or sync immediately after restoring
and resolve the conflicts by hand.

## Lost or stolen device

On the surviving device: `omega revoke --peer <lost device_id> --actor human:<you>`. Sessions
from that device are then refused, and so are events it originated, including relayed ones.
Pair a replacement device as new: it gets a new identity. Events the lost device already synced
stay valid history.

## Rolling back a capability change (code)

Promotion is never automatic (ADR-0007). Every `PROMOTION_DECISION` names a `rollback_point` (a
git commit the gate checked exists):

```bash
git log --oneline                       # find the change
git revert <commit>                     # preferred: history stays intact
# or, to return to the recorded known-good point on a branch:
git checkout -b rollback/<date> <rollback_point>
python -m pytest -q omega/tests && python -m unittest discover -s cognition/tests -t .
```

Then record the outcome: write `PROMOTION_DECISION` with `decision: ROLLBACK` through
`PromotionGate.decide`. Code rollback never touches the event store. Events are data and stay
valid across code versions, because schema `fw.omega.event/1` is versioned and unknown versions
are refused, not reinterpreted.

## Erasure requests

`omega delete --event <id> --reason "<why>" --actor human:<you>` purges the payload, the search
index rows and any unshared artifacts, keeps the verifiable header, and propagates to peers on
the next sync. Copies outside omega (backups, exported bundles, diagnostics files) must be
handled by the operator.
