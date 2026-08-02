"""Cognitive Alert Engine.

Pipeline: Signal -> Normalize -> Classify -> Score -> Present -> Acknowledge
-> Resolve -> Persist. `detect()` runs the first five stages synchronously
(they're deterministic given the signal); Acknowledge/Action/Resolve/
Dismiss/Escalate are explicit operator- or engine-driven transitions.

This mirrors the cognition depicted in the film on purpose:
  sensory contact          -> detect()            receive signals
  neural convergence       -> _normalize()/_classify()  normalize
  executive competition    -> _score()             rank salience
  mission selection        -> recommended action in present state
  coordinated construction -> action()             execute bounded repair
  reality testing          -> resolve() validation  validate
  cinematic emergence      -> resolution_evidence   produce corrected artifact
  external release         -> can_proceed_to_publish() expose output
  recursive learning       -> persist()             retain outcome

Hard guardrail, enforced structurally (not by a flag that could be
flipped): this module has no method that publishes anything externally,
deletes evidence, overwrites a promoted release, reads/exposes
credentials, or resolves/dismisses/escalates its own alerts without an
explicit caller-supplied actor. It can only *block* progression via
`can_proceed_to_publish()` -- callers (renderer/player) are responsible
for actually honoring that before they publish or overwrite anything.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from alerts.models import (
    Alert, CLASSES, CODES_BY_CLASS, STATES, TERMINAL_STATES,
    STATE_DETECTED, STATE_CLASSIFIED, STATE_PRESENTED, STATE_ACKNOWLEDGED,
    STATE_ACTIONED, STATE_RESOLVED, STATE_DISMISSED, STATE_ESCALATED,
    CLASS_BLOCKING, dedup_key, severity_score, SOURCES,
)

DEFAULT_SUPPRESSION_WINDOW_S = 30.0


class UnknownAlertError(KeyError):
    pass


class InvalidTransitionError(ValueError):
    pass


class AlertEngine:
    def __init__(self, persist_dir: Path, suppression_window_s: float = DEFAULT_SUPPRESSION_WINDOW_S):
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = persist_dir / "alerts.jsonl"
        self.state_path = persist_dir / "current_state.json"
        self.suppression_window_s = suppression_window_s
        self._alerts: dict[str, Alert] = {}
        self._load()

    # ------------------------------------------------------------- persist

    def _load(self) -> None:
        """Restart persistence: replay the append-only log to rebuild
        current in-memory state. Each line is one snapshot of an alert at
        the moment it changed; the last line for a given id wins."""
        if not self.log_path.exists():
            return
        with self.log_path.open("r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self._alerts[data["id"]] = Alert.from_dict(data)

    def _persist(self, alert: Alert) -> None:
        with self.log_path.open("a") as fh:
            fh.write(json.dumps(alert.as_dict()) + "\n")
        self._write_current_state()

    def _write_current_state(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        payload = {
            "generated_at": time.time(),
            "total_alerts": len(self._alerts),
            "active_count": len(self.active_alerts()),
            "blocking_count": len(self.blocking_alerts()),
            "can_proceed_to_publish": self.can_proceed_to_publish(),
            "alerts": [a.as_dict() for a in sorted(self._alerts.values(), key=lambda a: -a.severity)],
        }
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(self.state_path)

    # --------------------------------------------------------------- pipeline

    def detect(self, source: str, code: str, alert_class: str, message: str,
               context: dict | None = None, group_key: str | None = None) -> Alert:
        if source not in SOURCES:
            raise ValueError(f"unknown alert source '{source}', valid: {SOURCES}")
        if alert_class not in CLASSES:
            raise ValueError(f"unknown alert class '{alert_class}', valid: {CLASSES}")
        if code not in CODES_BY_CLASS[alert_class]:
            raise ValueError(f"code '{code}' is not valid for class '{alert_class}'")

        key = dedup_key(source, code, group_key)

        existing = self._alerts.get(key)
        now = time.time()
        if existing is not None and existing.state not in TERMINAL_STATES:
            # DEDUPLICATION: the same live issue (source+code+group_key)
            # always merges into the same alert for its whole lifetime --
            # it never gets a second identity just because time passed.
            existing.occurrence_count += 1
            existing.message = message
            existing.context = context or existing.context
            # SUPPRESSION WINDOW: if the alert is being handled
            # (ACKNOWLEDGED/ACTIONED) and keeps recurring within the
            # window, don't yank it back to PRESENTED on every duplicate
            # -- that would just be noise for whoever's already on it. If
            # it keeps recurring *past* the window despite being handled,
            # resurface it: it isn't actually going away.
            if existing.state != STATE_PRESENTED and now - existing.updated_at >= self.suppression_window_s:
                existing.state = STATE_PRESENTED
            existing.updated_at = now
            self._alerts[key] = existing
            self._persist(existing)
            return existing

        alert = Alert(
            id=key, source=source, code=code, alert_class=alert_class,
            message=message, context=context or {}, group_key=group_key,
            state=STATE_DETECTED, created_at=now, updated_at=now,
        )
        # Normalize -> Classify -> Score -> Present happen synchronously:
        # given a signal, its classification and severity are deterministic.
        alert.state = STATE_CLASSIFIED
        alert.severity = severity_score(alert_class, code)
        alert.state = STATE_PRESENTED
        alert.updated_at = time.time()

        self._alerts[key] = alert
        self._persist(alert)
        return alert

    def get(self, alert_id: str) -> Alert:
        if alert_id not in self._alerts:
            raise UnknownAlertError(alert_id)
        return self._alerts[alert_id]

    def acknowledge(self, alert_id: str, by: str) -> Alert:
        alert = self.get(alert_id)
        if alert.state not in (STATE_PRESENTED, STATE_ESCALATED):
            raise InvalidTransitionError(f"cannot acknowledge alert in state {alert.state}")
        alert.state = STATE_ACKNOWLEDGED
        alert.acknowledged_by = by
        alert.acknowledged_at = time.time()
        alert.updated_at = alert.acknowledged_at
        self._persist(alert)
        return alert

    def action(self, alert_id: str, note: str) -> Alert:
        alert = self.get(alert_id)
        if alert.state != STATE_ACKNOWLEDGED:
            raise InvalidTransitionError(f"cannot action alert in state {alert.state}")
        alert.state = STATE_ACTIONED
        alert.actioned_note = note
        alert.actioned_at = time.time()
        alert.updated_at = alert.actioned_at
        self._persist(alert)
        return alert

    def resolve(self, alert_id: str, evidence: str) -> Alert:
        alert = self.get(alert_id)
        if alert.state not in (STATE_ACTIONED, STATE_PRESENTED, STATE_ACKNOWLEDGED, STATE_ESCALATED):
            raise InvalidTransitionError(f"cannot resolve alert in state {alert.state}")
        if not evidence:
            raise ValueError("resolve() requires non-empty resolution_evidence")
        alert.state = STATE_RESOLVED
        alert.resolution_evidence = evidence
        alert.resolved_at = time.time()
        alert.updated_at = alert.resolved_at
        self._persist(alert)
        return alert

    def dismiss(self, alert_id: str, by: str, reason: str) -> Alert:
        alert = self.get(alert_id)
        if alert.state in TERMINAL_STATES:
            raise InvalidTransitionError(f"cannot dismiss alert already in terminal state {alert.state}")
        alert.state = STATE_DISMISSED
        alert.dismissed_reason = f"{by}: {reason}"
        alert.dismissed_at = time.time()
        alert.updated_at = alert.dismissed_at
        self._persist(alert)
        return alert

    def escalate(self, alert_id: str, reason: str) -> Alert:
        alert = self.get(alert_id)
        if alert.state in TERMINAL_STATES:
            raise InvalidTransitionError(f"cannot escalate alert already in terminal state {alert.state}")
        alert.state = STATE_ESCALATED
        alert.escalated_reason = reason
        alert.escalated_at = time.time()
        alert.updated_at = alert.escalated_at
        self._persist(alert)
        return alert

    # --------------------------------------------------------------- queries

    def active_alerts(self) -> list[Alert]:
        return sorted(
            (a for a in self._alerts.values() if a.state not in TERMINAL_STATES),
            key=lambda a: -a.severity,
        )

    def blocking_alerts(self) -> list[Alert]:
        return [a for a in self.active_alerts() if a.alert_class == CLASS_BLOCKING]

    def alerts_by_group(self, group_key: str) -> list[Alert]:
        return [a for a in self._alerts.values() if a.group_key == group_key]

    def can_proceed_to_publish(self) -> bool:
        """The one piece of real leverage this engine has: it can say no.
        It cannot act on that itself (see module docstring) -- the caller
        (renderer/player/launcher) must check this before publishing,
        overwriting a release, or promoting an artifact."""
        return len(self.blocking_alerts()) == 0
