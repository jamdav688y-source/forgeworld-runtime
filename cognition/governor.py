"""FW-RECURSION-GOVERNOR-R4-001: the Recursion Governor.

Decides whether one more cognitive cycle may run, and records the decision
durably so the same cycle can never be admitted twice, budgets cannot be
overspent, and nothing a cycle produces can authorize the next one.

CYCLE IDENTITY
    cycle_id       = H(purpose, sorted input content_ids, parent_cycle_id)
                     (domain-separated sha256, like every CXP identity; no
                     time and no randomness). The same purpose over the same
                     content under the same parent is the same cycle.
    root_cycle_id  = cycle_id for a root cycle, else the parent's root.
    depth          = 0 for a root, parent depth + 1 otherwise.
    A parent must be an already-ADMITTED, already-COMPLETED cycle in this
    governor's ledger; anything else is refused (INVALID_PARENT,
    PARENT_NOT_COMPLETED). Budgets are accounted per root lineage.

DECISIONS: ADMIT | NEEDS_HUMAN | REFUSE, each with one reason code, the
cycle identity, the evidence references that decided it, and the budget
remaining. evaluate() only PROPOSES (committed=False, writes nothing).
admit() re-evaluates under an exclusive file lock and, only on ADMIT,
appends an ADMITTED entry in one atomic write (committed=True). Two
concurrent admit() calls for one cycle: exactly one commits, the other is
refused DUPLICATE_CYCLE.

CHECK ORDER (first failure decides):
    LEDGER_INTEGRITY_FAILURE   the ledger is unreadable or inconsistent
    INVALID_INPUT / INPUT_ERASED
    INVALID_PARENT / PARENT_NOT_COMPLETED
    DUPLICATE_CYCLE
    UNACCOUNTED_USAGE          an admitted cycle in this lineage never
                               reported its usage: its spend is unknown
    DEPTH_EXCEEDED / FAILURE_LIMIT / BUDGET_EXHAUSTED
    NO_NEW_EVIDENCE            a child cycle must add an OBSERVATION or
                               AUDIENCE_QUESTION root citing a source
                               origin its whole ancestry has never used.
                               Paraphrases, inferences,
                               contradictions, lens outputs and
                               dramatizations add no roots; a new record
                               of an already-used origin adds no origin.
    COMMERCIAL_INPUT           (NEEDS_HUMAN) any input traces to a
                               COMMERCIAL_SIGNAL, or to an AUDIENCE_QUESTION
                               marked commercial_interest
    RECYCLED_INPUTS_ONLY       (NEEDS_HUMAN) every input incorporates a
                               LENS_OUTPUT or CONTRADICTION
    otherwise ADMITTED.
A NEEDS_HUMAN decision becomes ADMIT only with an APPROVAL recorded for
exactly that cycle_id and that reason code; an approval cannot override any
REFUSE. Approvals are refused while a governed cycle is running (so a lens
cannot approve its own cycle) and from approver ids in the lens namespace.
approved_by is recorded, not authenticated.

BUDGET ACCOUNTING (units: lens invocations x policy.cost_per_lens_invocation)
    On admission a cycle RESERVES its planned invocations and their cost.
    complete() records ACTUAL invocations and failures (never more than
    reserved). Spend for a lineage = actual for completed cycles + full
    reservation for incomplete ones, so a crash mid-run can only make the
    accounting more conservative -- and an incomplete cycle blocks further
    admissions in its lineage (UNACCOUNTED_USAGE) until completed.

The governor authorizes cognition cycles only. It has no notion of
publishing, contacting, spending or executing, and every decision answers
grants_execution_authority -> False.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from evidence_envelope import envelope
from cognition import cxp, lineage

ADMIT = "ADMIT"
NEEDS_HUMAN = "NEEDS_HUMAN"
REFUSE = "REFUSE"

R_ADMITTED = "ADMITTED"
R_APPROVED = "ADMITTED_WITH_HUMAN_APPROVAL"
R_LEDGER = "LEDGER_INTEGRITY_FAILURE"
R_INVALID_INPUT = "INVALID_INPUT"
R_INPUT_ERASED = "INPUT_ERASED"
R_INVALID_PARENT = "INVALID_PARENT"
R_PARENT_NOT_COMPLETED = "PARENT_NOT_COMPLETED"
R_DUPLICATE = "DUPLICATE_CYCLE"
R_UNACCOUNTED = "UNACCOUNTED_USAGE"
R_DEPTH = "DEPTH_EXCEEDED"
R_FAILURES = "FAILURE_LIMIT"
R_BUDGET = "BUDGET_EXHAUSTED"
R_NO_NEW_EVIDENCE = "NO_NEW_EVIDENCE"
R_COMMERCIAL = "COMMERCIAL_INPUT"
R_RECYCLED = "RECYCLED_INPUTS_ONLY"
APPROVABLE_REASONS = (R_COMMERCIAL, R_RECYCLED)

_PURPOSE = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_CYCLE_ID = re.compile(r"^cxp-cycle-[0-9a-f]{64}$")
_COGNITIVE_KINDS = (cxp.KIND_LENS_OUTPUT, cxp.KIND_CONTRADICTION, cxp.KIND_EPISODE_CANDIDATE, cxp.KIND_EPISODE_REVIEW,
                    cxp.KIND_PRODUCTION_PACKAGE, cxp.KIND_PACKAGE_REVIEW)
_EVIDENCE_ROOT_KINDS = (cxp.KIND_OBSERVATION, cxp.KIND_AUDIENCE_QUESTION)
_ENTRY_ADMITTED, _ENTRY_COMPLETED, _ENTRY_APPROVAL = "ADMITTED", "COMPLETED", "APPROVAL"


class GovernorError(Exception):
    pass


@dataclass(frozen=True)
class GovernorPolicy:
    policy_id: str
    approved_by: str
    max_depth: int = 3
    max_lens_invocations: int = 21
    cost_per_lens_invocation: int = 1
    max_cost_units: int = 21
    max_failures: int = 3
    cost_unit: str = "lens-invocation-units"

    def __post_init__(self):
        cxp._validate_identifier(self.policy_id, "policy_id")
        cxp._validate_identifier(self.approved_by, "approved_by")
        for name in ("max_depth", "max_lens_invocations", "cost_per_lens_invocation", "max_cost_units", "max_failures"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < (0 if name in ("max_depth", "max_failures") else 1):
                raise ValueError(f"{name} must be a non-negative (or, for budgets, positive) integer")

    @property
    def grants_execution_authority(self) -> bool:
        return False


@dataclass(frozen=True)
class CycleRequest:
    purpose: str
    input_record_ids: tuple
    planned_lens_invocations: int
    parent_cycle_id: str = None
    approval_id: str = None


@dataclass(frozen=True)
class CycleDecision:
    decision: str
    reason_code: str
    cycle_id: str = None
    root_cycle_id: str = None
    parent_cycle_id: str = None
    depth: int = None
    input_record_ids: tuple = ()
    evidence_refs: dict = field(default_factory=dict)
    budget_remaining: dict = field(default_factory=dict)
    committed: bool = False
    detail: str = ""

    @property
    def grants_execution_authority(self) -> bool:
        return False

    def to_dict(self) -> dict:
        return {"decision": self.decision, "reason_code": self.reason_code, "cycle_id": self.cycle_id,
                "root_cycle_id": self.root_cycle_id, "parent_cycle_id": self.parent_cycle_id, "depth": self.depth,
                "input_record_ids": list(self.input_record_ids), "evidence_refs": self.evidence_refs,
                "budget_remaining": self.budget_remaining, "committed": self.committed, "detail": self.detail,
                "grants_execution_authority": False}


def cycle_id_for(purpose: str, input_content_ids, parent_cycle_id) -> str:
    return cxp.digest_id("cycle", {"purpose": purpose, "inputs": sorted(set(input_content_ids)),
                                   "parent": parent_cycle_id})


class RecursionGovernor:
    def __init__(self, exchange, root: Path, policy: GovernorPolicy, lock_timeout_seconds: float = 5.0):
        self.exchange = exchange
        self.policy = policy
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._ledger = self.root / "governor.jsonl"
        self._lock_path = self.root / "governor.lock"
        self._lock_timeout = lock_timeout_seconds
        self._active_cycles = 0

    @property
    def grants_execution_authority(self) -> bool:
        return False

    # -- ledger -----------------------------------------------------------------

    def _lock(self):
        return envelope._FileLock(self._lock_path, timeout_seconds=self._lock_timeout)

    def _entries(self) -> list:
        if not self._ledger.exists():
            return []
        entries = []
        with open(self._ledger, "r", encoding="utf-8") as f:
            for n, line in enumerate(f, start=1):
                if not line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(f"governor ledger line {n} is not newline-terminated")
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    raise envelope.LedgerIntegrityError(f"governor ledger line {n} is not JSON") from None
        return entries

    def _state(self) -> dict:
        """Replays and validates the whole ledger. Any inconsistency raises
        LedgerIntegrityError: usage that cannot be reconstructed exactly is
        never guessed at."""
        admitted, completed, approvals = {}, {}, {}
        for e in self._entries():
            kind = e.get("entry")
            if kind == _ENTRY_APPROVAL:
                expected = cxp.digest_id("approval", {k: e[k] for k in ("cycle_id", "reason_code", "approved_by")})
                if e.get("approval_id") != expected or e["reason_code"] not in APPROVABLE_REASONS:
                    raise envelope.LedgerIntegrityError("approval entry does not match its identity")
                approvals[e["approval_id"]] = e
            elif kind == _ENTRY_ADMITTED:
                cid = e["cycle_id"]
                if cycle_id_for(e["purpose"], e["input_content_ids"], e["parent_cycle_id"]) != cid:
                    raise envelope.LedgerIntegrityError(f"{cid} does not match its identity fields")
                if cid in admitted:
                    raise envelope.LedgerIntegrityError(f"{cid} admitted twice")
                parent = e["parent_cycle_id"]
                if parent is None:
                    if e["root_cycle_id"] != cid or e["depth"] != 0:
                        raise envelope.LedgerIntegrityError(f"{cid} is a root with inconsistent root/depth")
                else:
                    if parent not in admitted:  # also rules out cyclic ancestry: parents precede children
                        raise envelope.LedgerIntegrityError(f"{cid} names a parent not admitted before it")
                    if e["root_cycle_id"] != admitted[parent]["root_cycle_id"] or e["depth"] != admitted[parent]["depth"] + 1:
                        raise envelope.LedgerIntegrityError(f"{cid} has inconsistent root/depth for its parent")
                if e.get("approval_id") is not None:
                    approval = approvals.get(e["approval_id"])
                    if approval is None or approval["cycle_id"] != cid:
                        raise envelope.LedgerIntegrityError(f"{cid} cites an approval not recorded for it")
                admitted[cid] = e
            elif kind == _ENTRY_COMPLETED:
                cid = e["cycle_id"]
                if cid not in admitted or cid in completed:
                    raise envelope.LedgerIntegrityError(f"completion for {cid} has no single admission")
                a = admitted[cid]
                if not (0 <= e["failures"] <= e["lens_invocations"] <= a["reserved_lens_invocations"]
                        and e["cost_units"] == e["lens_invocations"] * a["cost_per_lens_invocation"]):
                    raise envelope.LedgerIntegrityError(f"usage reported for {cid} exceeds or contradicts its reservation")
                completed[cid] = e
            else:
                raise envelope.LedgerIntegrityError(f"unknown governor ledger entry {kind!r}")
        return {"admitted": admitted, "completed": completed, "approvals": approvals}

    def _append(self, entries: list) -> None:
        envelope._atomic_write_bytes(self._ledger, envelope._serialize_ledger(self._entries() + entries))

    # -- accounting ---------------------------------------------------------------

    def _lineage_usage(self, state: dict, root_cycle_id: str) -> dict:
        invocations = cost = failures = 0
        incomplete = []
        for cid, a in state["admitted"].items():
            if a["root_cycle_id"] != root_cycle_id:
                continue
            done = state["completed"].get(cid)
            if done is None:
                incomplete.append(cid)
                invocations += a["reserved_lens_invocations"]
                cost += a["reserved_cost_units"]
            else:
                invocations += done["lens_invocations"]
                cost += done["cost_units"]
                failures += done["failures"]
        return {"invocations": invocations, "cost": cost, "failures": failures, "incomplete": sorted(incomplete)}

    def _remaining(self, usage: dict, depth) -> dict:
        p = self.policy
        return {"lens_invocations": p.max_lens_invocations - usage["invocations"],
                "cost_units": p.max_cost_units - usage["cost"], "cost_unit": p.cost_unit,
                "failures": p.max_failures - usage["failures"],
                "generations": None if depth is None else p.max_depth - depth}

    # -- evaluation -------------------------------------------------------------

    def _ancestry(self, state: dict, cycle_id: str) -> list:
        chain, seen = [], set()
        while cycle_id is not None:
            if cycle_id in seen:
                raise envelope.LedgerIntegrityError("cyclic cycle ancestry")
            seen.add(cycle_id)
            chain.append(state["admitted"][cycle_id])
            cycle_id = state["admitted"][cycle_id]["parent_cycle_id"]
        return chain

    def _input_profile(self, record_id: str) -> dict:
        t = lineage.trace(self.exchange.record_metadata, record_id)
        kinds = {n["record_id"]: n["kind"] for n in t["nodes"]}
        # Evidence roots: what was observed, or what an audience was observed to ask.
        observation_roots = sorted(r for r in t["observation_roots"] if kinds[r] in _EVIDENCE_ROOT_KINDS)
        origins = sorted({s["origin"] for s in t["sources"] if set(s["cited_by"]) & set(observation_roots)})
        return {"observation_roots": observation_roots, "origins": origins,
                "commercial": sorted(r for r, k in kinds.items() if k == cxp.KIND_COMMERCIAL_SIGNAL
                                    or (k == cxp.KIND_AUDIENCE_QUESTION
                                        and self.exchange.record_metadata(r)["audience"]["commercial_interest"])),
                "recycled": sorted(r for r, k in kinds.items() if k in _COGNITIVE_KINDS)}

    def _decide(self, state: dict, request: CycleRequest) -> CycleDecision:
        p = self.policy
        if not isinstance(request.purpose, str) or not _PURPOSE.match(request.purpose):
            return CycleDecision(REFUSE, R_INVALID_INPUT, detail="purpose must be a lowercase slug")
        if (not isinstance(request.planned_lens_invocations, int) or isinstance(request.planned_lens_invocations, bool)
                or request.planned_lens_invocations < 1):
            return CycleDecision(REFUSE, R_INVALID_INPUT, detail="planned_lens_invocations must be a positive integer")
        ids = tuple(sorted(set(request.input_record_ids or ())))
        if not ids:
            return CycleDecision(REFUSE, R_INVALID_INPUT, detail="at least one input record is required")
        content_ids = []
        for rid in ids:
            meta = self.exchange.record_metadata(rid)
            if meta is None:
                return CycleDecision(REFUSE, R_INVALID_INPUT, input_record_ids=ids, detail=f"{rid} is not an accepted record")
            if meta["erased"]:
                return CycleDecision(REFUSE, R_INPUT_ERASED, input_record_ids=ids, detail=f"{rid} has been erased")
            # research-topic identity: an audience question contributes its
            # question text only, so equal questions are one topic
            content_ids.append(meta["audience"]["topic_id"] if meta.get("audience") else meta["content_id"])

        parent = request.parent_cycle_id
        if parent is not None:
            if not isinstance(parent, str) or not _CYCLE_ID.match(parent) or parent not in state["admitted"]:
                return CycleDecision(REFUSE, R_INVALID_PARENT, parent_cycle_id=parent, input_record_ids=ids,
                                     detail="parent is not an admitted cycle")
            if parent not in state["completed"]:
                return CycleDecision(REFUSE, R_PARENT_NOT_COMPLETED, parent_cycle_id=parent, input_record_ids=ids,
                                     detail="a parent must report its usage before it can have children")
        cycle_id = cycle_id_for(request.purpose, content_ids, parent)
        root_cycle_id = cycle_id if parent is None else state["admitted"][parent]["root_cycle_id"]
        depth = 0 if parent is None else state["admitted"][parent]["depth"] + 1
        usage = self._lineage_usage(state, root_cycle_id)
        reserve_invocations = request.planned_lens_invocations
        reserve_cost = reserve_invocations * p.cost_per_lens_invocation
        base = dict(cycle_id=cycle_id, root_cycle_id=root_cycle_id, parent_cycle_id=parent, depth=depth,
                    input_record_ids=ids)

        def decision(kind, reason, refs=None, detail="", committed=False, spent=None):
            return CycleDecision(kind, reason, evidence_refs=refs or {}, detail=detail, committed=committed,
                                 budget_remaining=self._remaining(spent or usage, depth), **base)

        if cycle_id in state["admitted"]:
            return decision(REFUSE, R_DUPLICATE, {"admitted_cycle": cycle_id}, "this cycle was already admitted")
        if usage["incomplete"]:
            return decision(REFUSE, R_UNACCOUNTED, {"incomplete_cycles": usage["incomplete"]},
                            "an admitted cycle in this lineage has not reported its usage")
        if depth > p.max_depth:
            return decision(REFUSE, R_DEPTH, detail=f"depth {depth} exceeds max_depth {p.max_depth}")
        if usage["failures"] >= p.max_failures:
            return decision(REFUSE, R_FAILURES, detail=f"{usage['failures']} lens failures in this lineage")
        if usage["invocations"] + reserve_invocations > p.max_lens_invocations or usage["cost"] + reserve_cost > p.max_cost_units:
            return decision(REFUSE, R_BUDGET, {"requested_lens_invocations": reserve_invocations,
                                               "requested_cost_units": reserve_cost}, "budget would be exceeded")

        profiles = {rid: self._input_profile(rid) for rid in ids}
        refs = {
            "observation_roots": sorted({r for pr in profiles.values() for r in pr["observation_roots"]}),
            "commercial_records": sorted({r for pr in profiles.values() for r in pr["commercial"]}),
            "recycled_inputs": sorted(rid for rid, pr in profiles.items() if pr["recycled"]),
        }
        if parent is not None:
            ancestry = self._ancestry(state, parent)
            seen_roots = {r for a in ancestry for r in a["observation_roots"]}
            seen_origins = {o for a in ancestry for o in a["origins"]}
            new_roots = sorted(r for rid, pr in profiles.items() for r in pr["observation_roots"]
                               if r not in seen_roots)
            new_origins = sorted({o for pr in profiles.values() for o in pr["origins"]} - seen_origins)
            refs.update(new_observation_roots=new_roots, new_origins=new_origins,
                        ancestry=[a["cycle_id"] for a in ancestry])
            if not new_roots or not new_origins:
                return decision(REFUSE, R_NO_NEW_EVIDENCE, refs,
                                "a child cycle must add an observation root from a source origin its ancestry never used")

        needs = None
        if refs["commercial_records"]:
            needs = R_COMMERCIAL
        elif len(refs["recycled_inputs"]) == len(ids):
            needs = R_RECYCLED
        approval = None
        if needs is not None:
            approval = state["approvals"].get(request.approval_id) if request.approval_id else None
            if approval is None or approval["cycle_id"] != cycle_id or approval["reason_code"] != needs:
                return decision(NEEDS_HUMAN, needs, refs, "explicit human approval for this cycle and reason is required")
            refs["approval_id"] = approval["approval_id"]
            refs["approved_by"] = approval["approved_by"]

        spent = {**usage, "invocations": usage["invocations"] + reserve_invocations, "cost": usage["cost"] + reserve_cost}
        refs["_admission"] = {"profiles": profiles, "content_ids": sorted(set(content_ids)),
                              "reserve_invocations": reserve_invocations, "reserve_cost": reserve_cost}
        return decision(ADMIT, R_APPROVED if approval else R_ADMITTED, refs, spent=spent)

    def _public(self, d: CycleDecision, committed: bool) -> CycleDecision:
        refs = {k: v for k, v in d.evidence_refs.items() if not k.startswith("_")}
        return CycleDecision(**{**d.__dict__, "evidence_refs": refs, "committed": committed})

    def evaluate(self, request: CycleRequest) -> CycleDecision:
        """Propose a decision. Writes nothing; committed is always False."""
        try:
            return self._public(self._decide(self._state(), request), False)
        except envelope.LedgerIntegrityError as exc:
            return CycleDecision(REFUSE, R_LEDGER, detail=str(exc))

    def admit(self, request: CycleRequest) -> CycleDecision:
        """Decide and, on ADMIT, commit atomically under the ledger lock."""
        with self._lock():
            try:
                state = self._state()
                d = self._decide(state, request)
            except envelope.LedgerIntegrityError as exc:
                return CycleDecision(REFUSE, R_LEDGER, detail=str(exc))
            if d.decision != ADMIT:
                return self._public(d, False)
            adm = d.evidence_refs["_admission"]
            ancestry_roots = sorted({r for pr in adm["profiles"].values() for r in pr["observation_roots"]})
            ancestry_origins = sorted({o for pr in adm["profiles"].values() for o in pr["origins"]})
            self._append([{
                "entry": _ENTRY_ADMITTED, "cycle_id": d.cycle_id, "root_cycle_id": d.root_cycle_id,
                "parent_cycle_id": d.parent_cycle_id, "depth": d.depth, "purpose": request.purpose,
                "input_record_ids": list(d.input_record_ids), "input_content_ids": adm["content_ids"],
                "observation_roots": ancestry_roots, "origins": ancestry_origins,
                "reserved_lens_invocations": adm["reserve_invocations"], "reserved_cost_units": adm["reserve_cost"],
                "cost_per_lens_invocation": self.policy.cost_per_lens_invocation,
                "approval_id": d.evidence_refs.get("approval_id"), "policy_id": self.policy.policy_id,
            }])
            return self._public(d, True)

    def complete(self, cycle_id: str, lens_invocations: int, failures: int) -> dict:
        """Record a cycle's actual usage exactly once."""
        with self._lock():
            state = self._state()
            admitted = state["admitted"].get(cycle_id)
            if admitted is None:
                raise GovernorError(f"{cycle_id} was never admitted")
            if cycle_id in state["completed"]:
                raise GovernorError(f"{cycle_id} already reported its usage")
            if not (isinstance(lens_invocations, int) and isinstance(failures, int)
                    and 0 <= failures <= lens_invocations <= admitted["reserved_lens_invocations"]):
                raise GovernorError("usage must be within the reservation and failures within invocations")
            entry = {"entry": _ENTRY_COMPLETED, "cycle_id": cycle_id, "lens_invocations": lens_invocations,
                     "failures": failures, "cost_units": lens_invocations * admitted["cost_per_lens_invocation"]}
            self._append([entry])
            return entry

    def record_approval(self, cycle_id: str, reason_code: str, approved_by: str) -> str:
        """A human's explicit approval of one NEEDS_HUMAN reason for one cycle.
        Refused while any governed cycle is running in this governor."""
        if self._active_cycles:
            raise GovernorError("approvals cannot be recorded from inside a running cycle")
        if reason_code not in APPROVABLE_REASONS:
            raise GovernorError(f"only {APPROVABLE_REASONS} can be approved; REFUSE reasons cannot")
        if not isinstance(cycle_id, str) or not _CYCLE_ID.match(cycle_id):
            raise GovernorError("cycle_id is malformed")
        approved_by = cxp._validate_identifier(approved_by, "approved_by")
        if approved_by.startswith(("lens-", "synthetic-emitter", "coordinator")):
            raise GovernorError("approvals must come from a human operator id, not a cognitive component")
        identity = {"cycle_id": cycle_id, "reason_code": reason_code, "approved_by": approved_by}
        approval_id = cxp.digest_id("approval", identity)
        with self._lock():
            state = self._state()
            if approval_id not in state["approvals"]:
                self._append([{"entry": _ENTRY_APPROVAL, "approval_id": approval_id, **identity}])
        return approval_id

    @contextmanager
    def running(self):
        """Marks a governed cycle as in progress (blocks approvals meanwhile)."""
        self._active_cycles += 1
        try:
            yield
        finally:
            self._active_cycles -= 1

    def ledger_entries(self) -> tuple:
        return tuple(self._entries())
