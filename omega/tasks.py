"""Durable task queue with device-local, human-authorized execution.

SHARED EVIDENCE (synced):   TASK_QUEUED, TASK_AUTHORIZED, TASK_RESULT events.
DEVICE-LOCAL STATE (never synced): the `local_exec` table
    PENDING -> RUNNING(lease) -> DONE | FAILED | REFUSED
    AWAITING_AUTHORIZATION     (external task without a local authorization)
    NEEDS_REVIEW               (an external task was interrupted mid-run; it is
                                never retried automatically)

Rules (FW-SCS-001 rules 9 and 12):
  * Synchronization never executes anything. run_once() is only ever called
    by the operator / the local scheduler, never by sync.
  * A task is EXTERNAL if the task says so OR its executor declares it
    (the stricter of the two wins).
  * An external task runs only if THIS device holds a TASK_AUTHORIZED event
    for that exact task event, written locally (origin LOCAL) by a HUMAN
    actor AND carrying a valid operator attestation (omega/operator.py),
    re-verified at execution time. An authorization imported from another
    device does not count:
    events.validate() already requires authorized_device == writer device.
  * Unknown actions are refused, never guessed.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Optional

from omega import receipts
from omega.canonical import digest
from omega.events import event_id_for

LEASE_SECONDS = 300
MAX_ATTEMPTS = 3
SYSTEM_ACTOR = "system:omega-tasks"


@dataclass
class Executor:
    handler: Callable[[dict], str]
    external: bool = False      # sends, pays, posts, deletes outside this node...


class TaskQueue:
    def __init__(self, node, executors: Optional[dict] = None):
        self.node = node
        self.executors = executors or {}

    def queue(self, action: str, args: dict, *, actor: str, external_effect: bool,
              target_device: Optional[str] = None, privacy: str = "PRIVATE", links=()) -> str:
        task_id = "tk_" + digest("task", [self.node.device_id, action, args, self.node.vector()])[:24]
        payload = {"task_id": task_id, "action": action, "args": args, "external_effect": external_effect}
        if target_device:
            payload["target_device"] = target_device
        self.node.append("TASK_QUEUED", payload, actor=actor, privacy=privacy,
                         links=[f"task:{task_id}", *links], provenance=[{"kind": "source", "ref": actor}])
        return task_id

    def _task_event(self, task_id):
        for e in self.node.events("TASK_QUEUED", f"task:{task_id}"):
            if e.payload and e.payload["task_id"] == task_id:
                return e
        return None

    def authorize(self, task_id: str, *, actor: str, note: str = "", operator=None):
        ev = self._task_event(task_id)
        if ev is None:
            raise KeyError(task_id)
        return self.node.append("TASK_AUTHORIZED", {"task_id": task_id, "task_event": event_id_for(ev.header),
                                                    "authorized_device": self.node.device_id,
                                                    "note": note or "operator authorized"},
                                actor=actor, privacy="PRIVATE", links=[f"task:{task_id}"],
                                parents=[event_id_for(ev.header)], operator=operator)

    def _authorized_locally(self, task_ev) -> Optional[str]:
        teid = event_id_for(task_ev.header)
        for a in self.node.events("TASK_AUTHORIZED", f"task:{task_ev.payload['task_id']}"):
            h = a.header
            if (a.payload and a.payload["task_event"] == teid and h["actor_kind"] == "HUMAN"
                    and h["device_id"] == self.node.device_id
                    and self.node.origin_of(event_id_for(h)) == "LOCAL"
                    and self.node.attestation_problem(a) is None):   # re-verified at execution time
                return event_id_for(h)
        return None

    def _has_result(self, task_id):
        return any(e.payload and e.payload["task_id"] == task_id
                   and e.header["device_id"] == self.node.device_id
                   for e in self.node.events("TASK_RESULT", f"task:{task_id}"))

    def local_state(self, task_id) -> Optional[dict]:
        r = self.node.conn.execute("SELECT state, lease_until, attempts, detail FROM local_exec WHERE task_id=?",
                                   (task_id,)).fetchone()
        return {"state": r[0], "lease_until": r[1], "attempts": r[2], "detail": r[3]} if r else None

    def _set_state(self, conn, task_id, state, detail="", lease=None, bump=False):
        conn.execute("INSERT INTO local_exec(task_id, state, lease_until, attempts, detail) VALUES(?,?,?,?,?) "
                     "ON CONFLICT(task_id) DO UPDATE SET state=excluded.state, lease_until=excluded.lease_until, "
                     "attempts=local_exec.attempts + ?, detail=excluded.detail",
                     (task_id, state, lease, 1 if bump else 0, detail, 1 if bump else 0))

    def tasks(self) -> list:
        out = []
        for e in self.node.events("TASK_QUEUED"):
            if e.payload is None:
                continue
            out.append({"task_id": e.payload["task_id"], "action": e.payload["action"],
                        "external": e.payload["external_effect"], "origin_device": e.header["device_id"],
                        "local": self.local_state(e.payload["task_id"]) or {"state": "PENDING"}})
        return out

    def recover(self, now: Optional[float] = None) -> list:
        """After a crash: expired RUNNING leases go back to PENDING (internal
        tasks, bounded attempts) or to NEEDS_REVIEW (external tasks: the side
        effect may already have happened, so a human must decide)."""
        now = int(time.time() if now is None else now)
        changed = []
        with self.node.tx() as conn:
            for task_id, lease, attempts in conn.execute(
                    "SELECT task_id, lease_until, attempts FROM local_exec WHERE state='RUNNING'").fetchall():
                if lease is not None and lease > now:
                    continue
                if self._has_result(task_id):   # crashed after the result was committed
                    self._set_state(conn, task_id, "DONE", "result already recorded")
                    changed.append((task_id, "DONE"))
                    continue
                ev = self._task_event(task_id)
                external = ev.payload["external_effect"] or self.executors.get(ev.payload["action"], Executor(lambda a: "", False)).external
                new = "NEEDS_REVIEW" if external else ("FAILED" if attempts >= MAX_ATTEMPTS else "PENDING")
                self._set_state(conn, task_id, new, "recovered after interrupted run")
                changed.append((task_id, new))
            if changed:
                s = self.node.state_digest()
                receipts.issue(self.node, conn, "TASKS_RECOVERED", [t for t, _ in changed], s, s,
                               {"transitions": sorted([list(c) for c in changed])})
        return changed

    def run_once(self, now: Optional[float] = None) -> list:
        """Execute every runnable task once. Returns [(task_id, outcome)]."""
        now = int(time.time() if now is None else now)
        results = []
        for e in self.node.events("TASK_QUEUED"):
            p = e.payload
            if p is None:
                continue
            tid = p["task_id"]
            st = (self.local_state(tid) or {"state": "PENDING"})["state"]
            if st in ("DONE", "FAILED", "REFUSED", "RUNNING", "NEEDS_REVIEW") or self._has_result(tid):
                continue
            if p.get("target_device") and p["target_device"] != self.node.device_id:
                continue
            ex = self.executors.get(p["action"])
            if ex is None:
                self._finish(e, "REFUSED", f"unknown action {p['action']!r}", None)
                results.append((tid, "REFUSED_UNKNOWN_ACTION"))
                continue
            external = p["external_effect"] or ex.external
            auth = self._authorized_locally(e) if external else None
            if external and auth is None:
                if st != "AWAITING_AUTHORIZATION":
                    with self.node.tx() as conn:
                        self._set_state(conn, tid, "AWAITING_AUTHORIZATION", "external effect needs local human authorization")
                        s = self.node.state_digest()
                        receipts.issue(self.node, conn, "TASK_HELD_FOR_AUTHORIZATION", [event_id_for(e.header)], s, s,
                                       {"task_id": tid, "action": p["action"]})
                results.append((tid, "AWAITING_AUTHORIZATION"))
                continue
            with self.node.tx() as conn:
                self._set_state(conn, tid, "RUNNING", "", lease=now + LEASE_SECONDS, bump=True)
            try:
                summary = ex.handler(dict(p["args"]))
                self._finish(e, "SUCCEEDED", str(summary)[:4000], auth)
                results.append((tid, "SUCCEEDED"))
            except Exception as exc:
                self._finish(e, "FAILED", f"{type(exc).__name__}: {exc}"[:4000], auth)
                results.append((tid, "FAILED"))
        return results

    def _finish(self, task_ev, status, summary, auth):
        tid = task_ev.payload["task_id"]
        parents = [event_id_for(task_ev.header)] + ([auth] if auth else [])
        ev = self.node.append("TASK_RESULT", {"task_id": tid, "status": status, "summary": summary},
                              actor=SYSTEM_ACTOR, privacy="PRIVATE", links=[f"task:{tid}"], parents=parents)
        with self.node.tx() as conn:
            self._set_state(conn, tid, {"SUCCEEDED": "DONE", "FAILED": "FAILED", "REFUSED": "REFUSED"}[status],
                            json.dumps({"result_event": event_id_for(ev.header)}))
        return ev
