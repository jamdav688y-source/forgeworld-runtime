"""FW-ADAPTIVE-CAPABILITY-SUBSTRATE-CONVERGENCE-001: the canonical object
model, memory architecture, differential cognition engine, capability
graph, workflow compiler, promotion gate, and reachability engine.

DISCOVERY (done before writing a line of this file -- see this mission's
final report for the full survey): the repository already has THREE
different, non-overlapping things that could be confused with what this
module builds, and none of them is duplicated here:

  - fabric.interface.CAPABILITIES / FabricCapabilityProvider: a registry
    of INVOKABLE code (content_read, echo_mock, physical_ping). Purely
    mechanical -- no lifecycle, no evidence, no promotion. This module's
    CapabilityRecord may name one of these in its own fabric_capability_id
    field when a demonstrated ability corresponds to a real invokable
    capability, but a CapabilityRecord is not a FabricCapabilityProvider
    and this module never re-registers or wraps fabric.CAPABILITIES.
  - capabilities/discover.py + router/mission_router.py: an older, already
    self-documented-as-separate system (see evidence_envelope/trajectory.py's
    own module docstring) that probes EXTERNAL TOOL reachability
    (binaries/env vars/network services) and routes a mission description
    to one, scored by its own decisions.jsonl ledger. Explicitly untouched
    here, exactly as trajectory.py already chose not to merge with it --
    a different question (which external tool should handle this?) than
    this module's (what has ForgeWorld itself demonstrably learned to do,
    and to what evidence tier?).
  - the RPG-flavored top-level directories (npc/, quests/, factions/,
    reputation/, world/, governance/, doctrine/, events/, consequences/,
    memory/, etc.): static narrative text and shell scripts with no
    reading/writing code anywhere in the repository (confirmed by grep
    before writing this module) -- not architecture, not reused.

What IS reused, directly, not reimplemented:
  - evidence_envelope.envelope: validate_mission_id(), _FileLock,
    _atomic_write_bytes(), _serialize_ledger(), LedgerIntegrityError,
    _canonical(), _now() -- the exact durable-ledger discipline
    fabric.interface's own PairingStore/LocalKeyStore/PeerIdentityStore
    already build on. Every new durable store in this module (CapabilityGraph,
    EvidenceLedger, EpisodicMemory, SemanticMemory, ProceduralMemory) is a
    JSONL ledger built from these same primitives, not a new persistence
    scheme.
  - evidence_envelope.trajectory: PROVENANCE_KINDS (OBSERVED, DERIVED,
    HUMAN_ASSERTED, SYSTEM_ASSERTED, UNVERIFIED_INTERPRETATION,
    AUTHORIZED_CONCLUSION) and the CONFIDENCE_* levels -- reused verbatim
    as the provenance/confidence vocabulary for SignalEvent, InferenceRecord,
    and ProblemHypothesis, rather than inventing a second taxonomy.
  - fabric.interface: AuthorityContext, authority_permits(),
    process_remote_capability_request(), CAP_* status constants,
    PeerIdentityStore/PairingStore/LocalKeyStore -- every executable
    workflow step in this module (execute_workflow_step()) calls the REAL
    fabric governance path, unmodified. Nothing here can execute a
    capability by itself.

GOVERNANCE INVARIANT (Section 11): no object in this module -- not
ObjectiveContract, not DifferentialCognitionEngine, not WorkflowCompiler,
not CapabilityGraph -- has a method that authorizes execution. Only
GovernanceEngine.decide() produces a GovernanceDecision, and only
execute_workflow_step() may call fabric's real process_remote_capability_request(),
and it refuses to do so without an APPROVED GovernanceDecision bound to
the exact WorkflowPlan being executed. Economic context, differential-
cognition consensus, and capability advertisements are never consulted by
that check (see this module's own negative-invariant tests).
"""
from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evidence_envelope import envelope  # noqa: E402

# evidence_envelope/trajectory.py is not package-import-friendly (it does
# `import envelope`, a flat import, internally -- see its own module, and
# evidence_envelope/tests/test_trajectory.py's identical workaround) --
# reused here exactly the way its own test suite already imports it,
# rather than duplicating its PROVENANCE_KINDS/CONFIDENCE_* vocabulary.
_EVIDENCE_ENVELOPE_DIR = _ROOT / "evidence_envelope"
if str(_EVIDENCE_ENVELOPE_DIR) not in sys.path:
    sys.path.insert(0, str(_EVIDENCE_ENVELOPE_DIR))
import trajectory as _trajectory  # noqa: E402

PROVENANCE_KINDS = _trajectory.PROVENANCE_KINDS
OBSERVED = _trajectory.OBSERVED
DERIVED = _trajectory.DERIVED
HUMAN_ASSERTED = _trajectory.HUMAN_ASSERTED
SYSTEM_ASSERTED = _trajectory.SYSTEM_ASSERTED
UNVERIFIED_INTERPRETATION = _trajectory.UNVERIFIED_INTERPRETATION
AUTHORIZED_CONCLUSION = _trajectory.AUTHORIZED_CONCLUSION
CONFIDENCE_VERIFIED = _trajectory.CONFIDENCE_VERIFIED
CONFIDENCE_PARTIAL = _trajectory.CONFIDENCE_PARTIAL
CONFIDENCE_UNVERIFIED = _trajectory.CONFIDENCE_UNVERIFIED
_CONFIDENCE_LEVELS = _trajectory._CONFIDENCE_LEVELS

from fabric import interface as fi  # noqa: E402

SCHEMA_VERSION = 1


def _new_id(prefix: str) -> str:
    return envelope.validate_mission_id(f"{prefix}-{uuid.uuid4().hex}")


def _now() -> str:
    return envelope._now()


class SubstrateError(Exception):
    """Base class for every error this module raises deliberately (never
    a caught-and-hidden bug)."""


class GovernanceError(SubstrateError):
    """Raised when code tries to execute without a valid, matching,
    APPROVED GovernanceDecision -- this is the enforcement point for
    Section 11's central invariant, not merely documentation of it."""


class PromotionPolicyError(SubstrateError):
    """Raised for a malformed promotion policy or an attempt to set a
    CapabilityGraph lifecycle state directly, bypassing CapabilityPromotionGate."""


# ---------------------------------------------------------------------------
# Section 3: canonical object model
# ---------------------------------------------------------------------------

SIGNAL_ORIGINS = (
    "human_conversation", "social_observation", "customer_interaction",
    "phone_input", "pc_observation", "system_telemetry", "workflow_result",
    "failure", "commercial_outcome",
)


@dataclass(frozen=True)
class SignalEvent:
    """An OBSERVATION. Not automatically a fact about a person, a problem,
    a buyer, or an opportunity -- see InferenceRecord for the next,
    separate, explicitly-derived step (Section 4)."""

    signal_id: str
    origin: str
    raw_content: str
    provenance: str  # one of PROVENANCE_KINDS -- almost always OBSERVED for a raw signal
    created_at: str = field(default_factory=_now)
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    schema_version: int = SCHEMA_VERSION
    record_type: str = "SIGNAL_EVENT"

    def __post_init__(self):
        envelope.validate_mission_id(self.signal_id)
        if self.origin not in SIGNAL_ORIGINS:
            raise SubstrateError(f"unknown signal origin {self.origin!r} (expected one of {SIGNAL_ORIGINS})")
        if self.provenance not in PROVENANCE_KINDS:
            raise SubstrateError(f"invalid provenance {self.provenance!r}")


@dataclass(frozen=True)
class InferenceRecord:
    """A DERIVED interpretation of one or more signals. Explicitly
    separate from SignalEvent (an inference is not itself an observation)
    and from ProblemHypothesis (an inference is not itself a bounded,
    testable problem statement)."""

    inference_id: str
    source_signal_ids: tuple
    statement: str
    provenance: str  # almost always DERIVED or UNVERIFIED_INTERPRETATION
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "INFERENCE_RECORD"

    def __post_init__(self):
        envelope.validate_mission_id(self.inference_id)
        if not self.source_signal_ids:
            raise SubstrateError("InferenceRecord must cite at least one source_signal_id")
        if self.provenance not in PROVENANCE_KINDS:
            raise SubstrateError(f"invalid provenance {self.provenance!r}")


COST_DIMENSIONS = (
    "TIME", "MONEY", "FAILURE_PROBABILITY", "UNCERTAINTY", "COGNITIVE_LOAD",
    "DELAY", "REWORK", "LOST_OPPORTUNITY", "COORDINATION_BURDEN",
)
HYPOTHESIS_PROPOSED = "PROPOSED"
HYPOTHESIS_ACCEPTED = "ACCEPTED"
HYPOTHESIS_REJECTED = "REJECTED"
_HYPOTHESIS_STATUSES = (HYPOTHESIS_PROPOSED, HYPOTHESIS_ACCEPTED, HYPOTHESIS_REJECTED)


@dataclass(frozen=True)
class ProblemHypothesis:
    hypothesis_id: str
    source_signal_ids: tuple
    description: str
    evidence_for: tuple = ()
    evidence_against: tuple = ()
    missing_evidence: tuple = ()
    confidence: str = CONFIDENCE_UNVERIFIED
    possible_cost_dimensions: tuple = ()
    status: str = HYPOTHESIS_PROPOSED
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "PROBLEM_HYPOTHESIS"

    def __post_init__(self):
        envelope.validate_mission_id(self.hypothesis_id)
        if not self.source_signal_ids:
            raise SubstrateError("ProblemHypothesis must cite at least one source_signal_id")
        if self.confidence not in _CONFIDENCE_LEVELS:
            raise SubstrateError(f"invalid confidence {self.confidence!r}")
        if self.status not in _HYPOTHESIS_STATUSES:
            raise SubstrateError(f"invalid status {self.status!r}")
        for dim in self.possible_cost_dimensions:
            if dim not in COST_DIMENSIONS:
                raise SubstrateError(f"unknown cost dimension {dim!r}")


REVERSIBLE = "REVERSIBLE"
PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
IRREVERSIBLE = "IRREVERSIBLE"
_REVERSIBILITY_LEVELS = (REVERSIBLE, PARTIALLY_REVERSIBLE, IRREVERSIBLE)


@dataclass(frozen=True)
class ObjectiveContract:
    """A bounded state-transition specification -- NOT a prompt. Nothing
    in this dataclass or elsewhere in this module can turn an
    ObjectiveContract into authorization; see GovernanceEngine."""

    objective_id: str
    desired_state: str
    current_state: str
    required_capability_ids: tuple = ()
    constraints: tuple = ()
    success_conditions: tuple = ()
    failure_conditions: tuple = ()
    authority_ceiling: tuple = ()  # capability_ids this objective may NEVER exceed, even if granted elsewhere
    evidence_required: tuple = ()
    reversibility: str = REVERSIBLE
    external_effects_allowed: bool = False
    economic_context: Optional[str] = None
    source_hypothesis_id: Optional[str] = None
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "OBJECTIVE_CONTRACT"

    def __post_init__(self):
        envelope.validate_mission_id(self.objective_id)
        if self.reversibility not in _REVERSIBILITY_LEVELS:
            raise SubstrateError(f"invalid reversibility {self.reversibility!r}")
        if not set(self.required_capability_ids) <= set(self.authority_ceiling) and self.authority_ceiling:
            raise SubstrateError(
                "required_capability_ids must be a subset of authority_ceiling when a ceiling is declared "
                "-- an objective must not require more than it is bounded to ask for"
            )


# ---------------------------------------------------------------------------
# Section 7: differential cognition
# ---------------------------------------------------------------------------

PERSPECTIVE_PRIMARY = "PRIMARY"
PERSPECTIVE_ADVERSARIAL = "ADVERSARIAL"
PERSPECTIVE_ALTERNATIVE = "ALTERNATIVE"
PERSPECTIVE_COMMERCIAL = "COMMERCIAL"
PERSPECTIVE_GOVERNANCE = "GOVERNANCE"


@dataclass(frozen=True)
class DifferentialCognitionRecord:
    record_id: str
    perspective_id: str
    objective_id: str
    claims: tuple = ()
    assumptions: tuple = ()
    evidence_used: tuple = ()
    uncertainties: tuple = ()
    proposed_actions: tuple = ()
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "DIFFERENTIAL_COGNITION_RECORD"


@dataclass(frozen=True)
class ContradictionMap:
    map_id: str
    objective_id: str
    perspective_record_ids: tuple
    agreement: tuple = ()
    disagreement: tuple = ()
    conflicting_assumptions: tuple = ()
    conflicting_evidence_interpretation: tuple = ()
    missing_evidence: tuple = ()
    resolvable_contradictions: tuple = ()
    legitimate_unresolved_uncertainty: tuple = ()
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "CONTRADICTION_MAP"


@dataclass(frozen=True)
class SynthesisRecord:
    """CONSENSUS != TRUTH: preserved_disagreement is never dropped, even
    when empty (an empty tuple here means the perspectives genuinely
    agreed on every proposed action this round, not that disagreement was
    discarded -- perspective_record_ids always names every contributor,
    so nothing is silently erased)."""

    record_id: str
    objective_id: str
    contradiction_map_id: str
    perspective_record_ids: tuple
    preserved_disagreement: tuple
    information_gain_summary: str
    recommended_next_step: str
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "SYNTHESIS_RECORD"


def primary_perspective(objective: ObjectiveContract, evidence: tuple, constraints: tuple) -> dict:
    return {
        "claims": (f"Objective {objective.objective_id} is achievable via its declared required capabilities.",),
        "assumptions": ("The declared required_capability_ids are the complete set needed.",),
        "evidence_used": tuple(evidence),
        "uncertainties": (),
        "proposed_actions": ("compile_workflow_and_execute",),
    }


def adversarial_perspective(objective: ObjectiveContract, evidence: tuple, constraints: tuple) -> dict:
    uncertainties = []
    if not objective.evidence_required:
        uncertainties.append("no evidence_required was declared -- success may be unfalsifiable")
    if objective.reversibility == IRREVERSIBLE:
        uncertainties.append("objective is IRREVERSIBLE -- a wrong action cannot be undone")
    return {
        "claims": (f"Objective {objective.objective_id} may be under-specified or riskier than assumed.",),
        "assumptions": ("The declared required_capability_ids may be incomplete or the ceiling too wide.",),
        "evidence_used": tuple(evidence),
        "uncertainties": tuple(uncertainties),
        "proposed_actions": ("compile_workflow_and_execute",) if not uncertainties else ("gather_more_evidence_before_executing",),
    }


def alternative_perspective(objective: ObjectiveContract, evidence: tuple, constraints: tuple) -> dict:
    return {
        "claims": (f"A different capability composition might reach {objective.desired_state} with less exposure.",),
        "assumptions": ("At least one alternative capability composition exists but is not yet named.",),
        "evidence_used": (),
        "uncertainties": ("the alternative composition itself is unproven",),
        "proposed_actions": ("explore_alternative_composition",),
    }


def commercial_perspective(objective: ObjectiveContract, evidence: tuple, constraints: tuple) -> dict:
    claims = []
    if objective.economic_context:
        claims.append(f"economic_context is declared: {objective.economic_context!r}")
    else:
        claims.append("no economic_context is declared -- commercial value of this objective is unknown")
    return {
        "claims": tuple(claims),
        "assumptions": ("commercial value, if any, does not itself grant execution authority",),
        "evidence_used": (),
        "uncertainties": () if objective.economic_context else ("commercial value is unmeasured",),
        "proposed_actions": ("compile_workflow_and_execute",),
    }


def governance_perspective(objective: ObjectiveContract, evidence: tuple, constraints: tuple) -> dict:
    uncertainties = []
    if not objective.authority_ceiling:
        uncertainties.append("no authority_ceiling declared -- nothing bounds what this objective may eventually request")
    return {
        "claims": (f"Execution must independently satisfy fabric governance regardless of this objective's own claims.",),
        "assumptions": ("A GovernanceDecision, not this perspective, will decide authorization.",),
        "evidence_used": (),
        "uncertainties": tuple(uncertainties),
        "proposed_actions": ("compile_workflow_and_execute",) if not uncertainties else ("declare_authority_ceiling_before_executing",),
    }


DEFAULT_PERSPECTIVES = {
    PERSPECTIVE_PRIMARY: primary_perspective,
    PERSPECTIVE_ADVERSARIAL: adversarial_perspective,
    PERSPECTIVE_ALTERNATIVE: alternative_perspective,
    PERSPECTIVE_COMMERCIAL: commercial_perspective,
    PERSPECTIVE_GOVERNANCE: governance_perspective,
}


class DifferentialCognitionEngine:
    """Provider-neutral by construction: every perspective is a plain
    Python callable taking (objective, evidence, constraints) -> dict.
    None of the DEFAULT_PERSPECTIVES calls any model, local or remote --
    this engine has no dependency on any specific provider, proprietary or
    otherwise, and perspectives are fully caller-configurable."""

    def __init__(self, perspectives: Optional[dict] = None):
        self.perspectives = dict(perspectives) if perspectives is not None else dict(DEFAULT_PERSPECTIVES)

    def run(self, objective: ObjectiveContract, evidence: tuple = (), constraints: tuple = ()):
        records = []
        for perspective_id, fn in self.perspectives.items():
            out = fn(objective, evidence, constraints)
            records.append(DifferentialCognitionRecord(
                record_id=_new_id("DIFFCOG"), perspective_id=perspective_id, objective_id=objective.objective_id,
                claims=tuple(out.get("claims", ())), assumptions=tuple(out.get("assumptions", ())),
                evidence_used=tuple(out.get("evidence_used", ())), uncertainties=tuple(out.get("uncertainties", ())),
                proposed_actions=tuple(out.get("proposed_actions", ())),
            ))
        records = tuple(records)
        contradiction_map = self._build_contradiction_map(objective, records)
        synthesis = self._build_synthesis(objective, contradiction_map, records)
        return records, contradiction_map, synthesis

    @staticmethod
    def _build_contradiction_map(objective: ObjectiveContract, records: tuple) -> ContradictionMap:
        action_sets = [set(r.proposed_actions) for r in records]
        agreement = set.intersection(*action_sets) if action_sets else set()
        all_actions = set.union(*action_sets) if action_sets else set()
        disagreement = all_actions - agreement

        evidence_cited = set()
        for r in records:
            evidence_cited.update(r.evidence_used)
        missing_evidence = tuple(e for e in objective.evidence_required if e not in evidence_cited)

        uncertainties = set()
        for r in records:
            uncertainties.update(r.uncertainties)

        return ContradictionMap(
            map_id=_new_id("CMAP"), objective_id=objective.objective_id,
            perspective_record_ids=tuple(r.record_id for r in records),
            agreement=tuple(sorted(agreement)), disagreement=tuple(sorted(disagreement)),
            missing_evidence=missing_evidence,
            legitimate_unresolved_uncertainty=tuple(sorted(uncertainties)),
        )

    @staticmethod
    def _build_synthesis(objective: ObjectiveContract, cmap: ContradictionMap, records: tuple) -> SynthesisRecord:
        if cmap.missing_evidence:
            next_step = f"gather missing evidence before execution: {', '.join(cmap.missing_evidence)}"
        elif cmap.legitimate_unresolved_uncertainty:
            next_step = "resolve or explicitly accept unresolved uncertainty before execution"
        else:
            next_step = "proceed to workflow compilation under governance"
        gain = (
            f"{len(records)} perspectives produced {len(cmap.agreement)} agreed action(s) and "
            f"{len(cmap.disagreement)} disagreed action(s); {len(cmap.legitimate_unresolved_uncertainty)} "
            "uncertainty statement(s) preserved rather than resolved by vote."
        )
        return SynthesisRecord(
            record_id=_new_id("SYNTH"), objective_id=objective.objective_id, contradiction_map_id=cmap.map_id,
            perspective_record_ids=cmap.perspective_record_ids,
            preserved_disagreement=cmap.disagreement,
            information_gain_summary=gain, recommended_next_step=next_step,
        )


# ---------------------------------------------------------------------------
# Section 8: Capability Graph (also serves as the CAPABILITY memory class,
# Section 18 -- one durable store, not two, for the same concept)
# ---------------------------------------------------------------------------

CAP_STATE_DISCOVERED = "DISCOVERED"
CAP_STATE_CANDIDATE = "CANDIDATE"
CAP_STATE_DEMONSTRATED = "DEMONSTRATED"
CAP_STATE_OPERATIONALLY_PROVEN = "OPERATIONALLY_PROVEN"
CAP_STATE_COMMERCIALLY_PROVEN = "COMMERCIALLY_PROVEN"
CAP_STATE_TRANSFER_PROVEN = "TRANSFER_PROVEN"
_CAP_LIFECYCLE_ORDER = (
    CAP_STATE_DISCOVERED, CAP_STATE_CANDIDATE, CAP_STATE_DEMONSTRATED,
    CAP_STATE_OPERATIONALLY_PROVEN, CAP_STATE_COMMERCIALLY_PROVEN, CAP_STATE_TRANSFER_PROVEN,
)
# "Available for workflow composition" means at least DEMONSTRATED --
# CANDIDATE/DISCOVERED capabilities exist as records but are not usable.
_AVAILABLE_FROM = _CAP_LIFECYCLE_ORDER.index(CAP_STATE_DEMONSTRATED)

EVIDENCE_DIMENSIONS = ("TECHNICAL", "GOVERNANCE", "OPERATIONAL", "COMMERCIAL", "TRANSFER")
DIM_NOT_EVIDENCED = "NOT_EVIDENCED"
DIM_PARTIAL = "PARTIAL"
DIM_EVIDENCED = "EVIDENCED"
_DIM_STATES = (DIM_NOT_EVIDENCED, DIM_PARTIAL, DIM_EVIDENCED)


class CapabilityGraph:
    """Durable, append-only (JSONL) lifecycle ledger for CapabilityRecord,
    reusing evidence_envelope.envelope's exact lock/atomic-write/ledger
    discipline fabric.interface's PairingStore/PeerIdentityStore already
    use. Lifecycle transitions are recorded by CapabilityPromotionGate's
    apply_promotion() ONLY -- register_discovered()/record_evidence()
    never advance lifecycle_state themselves."""

    def __init__(self, root: Path, lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "capability_graph.jsonl"
        self.lock_path = self.root / "capability_graph.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    def _read_all(self) -> list:
        if not self.ledger_path.exists():
            return []
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(
                        f"capability graph ledger {self.ledger_path} line {line_number} is not newline-terminated"
                    )
                line = raw_line.strip()
                if not line:
                    continue
                import json
                record = json.loads(line)
                if not isinstance(record, dict) or "capability_id" not in record or "lifecycle_state" not in record:
                    raise envelope.LedgerIntegrityError(
                        f"capability graph ledger {self.ledger_path} line {line_number} missing required field"
                    )
                records.append(record)
        return records

    def _append(self, record: dict) -> None:
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all()
            envelope._atomic_write_bytes(self.ledger_path, envelope._serialize_ledger(records + [record]))

    def _latest(self, capability_id: str) -> Optional[dict]:
        latest = None
        for r in self._read_all():
            if r["capability_id"] == capability_id:
                latest = r
        return latest

    def version(self) -> int:
        """Number of transitions ever recorded -- a monotonically
        increasing attribution handle so a ReachabilityDelta can name
        exactly which CapabilityGraph state produced it (Section 30)."""
        return len(self._read_all())

    def register_discovered(self, capability_id: str, *, display_name: str, description: str,
                             requires_capability_ids: tuple = (), fabric_capability_id: Optional[str] = None) -> None:
        capability_id = envelope.validate_mission_id(capability_id)
        if self._latest(capability_id) is not None:
            raise SubstrateError(f"capability_id {capability_id!r} is already registered")
        self._append({
            "capability_id": capability_id, "lifecycle_state": CAP_STATE_DISCOVERED,
            "display_name": display_name, "description": description,
            "requires_capability_ids": list(requires_capability_ids), "fabric_capability_id": fabric_capability_id,
            "evidence_dimensions": {d: DIM_NOT_EVIDENCED for d in EVIDENCE_DIMENSIONS},
            "created_at": _now(), "reason": None,
        })

    def record_evidence_dimension(self, capability_id: str, dimension: str, state: str) -> None:
        """Updates ONE evidence dimension's observed state. This never
        changes lifecycle_state -- only CapabilityPromotionGate.apply_promotion() does."""
        if dimension not in EVIDENCE_DIMENSIONS:
            raise SubstrateError(f"unknown evidence dimension {dimension!r}")
        if state not in _DIM_STATES:
            raise SubstrateError(f"unknown evidence dimension state {state!r}")
        current = self._latest(capability_id)
        if current is None:
            raise SubstrateError(f"cannot record evidence for unknown capability_id {capability_id!r}")
        new_dims = dict(current["evidence_dimensions"])
        new_dims[dimension] = state
        self._append({**current, "evidence_dimensions": new_dims, "created_at": _now(), "reason": f"evidence recorded: {dimension}={state}"})

    def _set_lifecycle_state(self, capability_id: str, new_state: str, reason: str) -> None:
        """PRIVATE: only CapabilityPromotionGate.apply_promotion() may
        call this (enforced by convention + the negative-invariant test
        that no other code path in this module calls it)."""
        current = self._latest(capability_id)
        if current is None:
            raise SubstrateError(f"cannot promote unknown capability_id {capability_id!r}")
        if new_state not in _CAP_LIFECYCLE_ORDER:
            raise SubstrateError(f"unknown lifecycle state {new_state!r}")
        self._append({**current, "lifecycle_state": new_state, "created_at": _now(), "reason": reason})

    def resolve_current(self, capability_id: str) -> Optional[dict]:
        return self._latest(capability_id)

    def is_available(self, capability_id: str) -> bool:
        record = self._latest(capability_id)
        if record is None:
            return False
        return _CAP_LIFECYCLE_ORDER.index(record["lifecycle_state"]) >= _AVAILABLE_FROM

    def dependencies_satisfied(self, capability_id: str) -> bool:
        record = self._latest(capability_id)
        if record is None:
            return False
        return all(self.is_available(dep) for dep in record["requires_capability_ids"])

    def list_all_current(self) -> tuple:
        seen = {}
        for r in self._read_all():
            seen[r["capability_id"]] = r
        return tuple(seen.values())


# ---------------------------------------------------------------------------
# Section 9: Workflow Compiler
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowPlan:
    plan_id: str
    objective_id: str
    required_capability_ids: tuple
    existing_capability_ids: tuple
    composable_capability_ids: tuple
    missing_capability_ids: tuple
    capability_gap_ids: tuple = ()
    approval_points: tuple = ()
    evidence_requirements: tuple = ()
    failure_escalation_paths: tuple = ("HALT_AND_REPORT",)
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "WORKFLOW_PLAN"

    @property
    def is_executable(self) -> bool:
        return not self.missing_capability_ids


GAP_OPEN = "OPEN"
GAP_IN_FOUNDRY = "IN_FOUNDRY"
GAP_RESOLVED = "RESOLVED"
GAP_ABANDONED = "ABANDONED"


@dataclass(frozen=True)
class CapabilityGapRecord:
    gap_id: str
    missing_capability_id: str
    objective_id: str
    smallest_bounded_experiment: str
    status: str = GAP_OPEN
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "CAPABILITY_GAP_RECORD"


class WorkflowCompiler:
    """Receives an ObjectiveContract + a CapabilityGraph snapshot +
    optional compositions, and produces a WorkflowPlan. Never
    hallucinates a missing capability into existence -- a required
    capability_id that is not available (and not satisfiable via a
    declared composition) becomes a CapabilityGapRecord, not a silent
    substitution."""

    def compile(self, objective: ObjectiveContract, capability_graph: CapabilityGraph,
                compositions: Optional[dict] = None) -> tuple:
        """Returns (WorkflowPlan, tuple[CapabilityGapRecord, ...])."""
        compositions = compositions or {}
        existing, composable, missing = [], [], []
        for capability_id in objective.required_capability_ids:
            if capability_graph.is_available(capability_id) and capability_graph.dependencies_satisfied(capability_id):
                existing.append(capability_id)
                continue
            composition = compositions.get(capability_id)
            if composition and all(
                capability_graph.is_available(c) and capability_graph.dependencies_satisfied(c) for c in composition
            ):
                composable.append(capability_id)
                continue
            missing.append(capability_id)

        gaps = tuple(
            CapabilityGapRecord(
                gap_id=_new_id("GAP"), missing_capability_id=capability_id, objective_id=objective.objective_id,
                smallest_bounded_experiment=f"probe whether a minimal harmless implementation of {capability_id!r} can be demonstrated",
            )
            for capability_id in missing
        )

        plan = WorkflowPlan(
            plan_id=_new_id("PLAN"), objective_id=objective.objective_id,
            required_capability_ids=tuple(objective.required_capability_ids),
            existing_capability_ids=tuple(existing), composable_capability_ids=tuple(composable),
            missing_capability_ids=tuple(missing), capability_gap_ids=tuple(g.gap_id for g in gaps),
            approval_points=("governance_decision",), evidence_requirements=tuple(objective.evidence_required),
        )
        return plan, gaps


# ---------------------------------------------------------------------------
# Section 10: Capability Foundry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    claim: str
    test_or_observation: str
    result: str
    provenance: str
    evidence_dimension: str
    source_execution_id: Optional[str] = None
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "EVIDENCE_RECORD"

    def __post_init__(self):
        envelope.validate_mission_id(self.evidence_id)
        if self.provenance not in PROVENANCE_KINDS:
            raise SubstrateError(f"invalid provenance {self.provenance!r}")
        if self.evidence_dimension not in EVIDENCE_DIMENSIONS:
            raise SubstrateError(f"invalid evidence dimension {self.evidence_dimension!r}")


class CapabilityFoundry:
    """GAP -> hypothesis -> smallest reversible probe -> evidence ->
    promotion CANDIDATE. Deliberately distinguishes TOOL CREATED from
    CAPABILITY DEMONSTRATED: run_probe() only ever advances a capability
    to CANDIDATE and records TECHNICAL evidence for a successful probe --
    reaching DEMONSTRATED or higher always goes through
    CapabilityPromotionGate, never automatically here."""

    def __init__(self, capability_graph: CapabilityGraph, evidence_ledger: "EvidenceLedger"):
        self.capability_graph = capability_graph
        self.evidence_ledger = evidence_ledger

    def run_probe(self, gap: CapabilityGapRecord, probe_fn, *, display_name: str, description: str) -> tuple:
        """probe_fn() -> (success: bool, observation: str). Returns
        (CapabilityGapRecord (updated), Optional[EvidenceRecord])."""
        if self.capability_graph.resolve_current(gap.missing_capability_id) is None:
            self.capability_graph.register_discovered(
                gap.missing_capability_id, display_name=display_name, description=description,
            )
        success, observation = probe_fn()
        if not success:
            return replace(gap, status=GAP_OPEN), None

        evidence = EvidenceRecord(
            evidence_id=_new_id("EVID"), claim=f"{gap.missing_capability_id} can be minimally demonstrated",
            test_or_observation=gap.smallest_bounded_experiment, result=observation,
            provenance=SYSTEM_ASSERTED, evidence_dimension="TECHNICAL",
        )
        self.evidence_ledger.write(evidence)
        self.capability_graph.record_evidence_dimension(gap.missing_capability_id, "TECHNICAL", DIM_EVIDENCED)
        return replace(gap, status=GAP_RESOLVED), evidence


class EvidenceLedger:
    """Durable JSONL ledger for EvidenceRecord (also the EVIDENCE memory
    class, Section 18 -- one store, not two)."""

    def __init__(self, root: Path, lock_timeout_seconds: float = 5.0):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.root / "evidence_ledger.jsonl"
        self.lock_path = self.root / "evidence_ledger.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    def write(self, evidence: EvidenceRecord) -> None:
        import json
        record = {
            "evidence_id": evidence.evidence_id, "claim": evidence.claim,
            "test_or_observation": evidence.test_or_observation, "result": evidence.result,
            "provenance": evidence.provenance, "evidence_dimension": evidence.evidence_dimension,
            "source_execution_id": evidence.source_execution_id, "created_at": evidence.created_at,
            "schema_version": evidence.schema_version, "record_type": evidence.record_type,
        }
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all_raw()
            envelope._atomic_write_bytes(self.ledger_path, envelope._serialize_ledger(records + [record]))
        del json

    def _read_all_raw(self) -> list:
        if not self.ledger_path.exists():
            return []
        import json
        records = []
        with open(self.ledger_path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(f"evidence ledger line {line_number} is not newline-terminated")
                line = raw_line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def list_all(self) -> tuple:
        return tuple(self._read_all_raw())

    def for_capability_claim(self, capability_id: str) -> tuple:
        return tuple(r for r in self._read_all_raw() if capability_id in r["claim"])


# ---------------------------------------------------------------------------
# Section 15: Capability Promotion Gate
# ---------------------------------------------------------------------------

PROMOTE = "PROMOTE"
HOLD = "HOLD"
REJECT = "REJECT"
NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
_PROMOTION_DECISIONS = (PROMOTE, HOLD, REJECT, NEEDS_MORE_EVIDENCE)

DEFAULT_PROMOTION_POLICY = {
    CAP_STATE_CANDIDATE: ("TECHNICAL",),
    CAP_STATE_DEMONSTRATED: ("TECHNICAL", "GOVERNANCE"),
    CAP_STATE_OPERATIONALLY_PROVEN: ("TECHNICAL", "GOVERNANCE", "OPERATIONAL"),
    CAP_STATE_COMMERCIALLY_PROVEN: ("TECHNICAL", "GOVERNANCE", "OPERATIONAL", "COMMERCIAL"),
    CAP_STATE_TRANSFER_PROVEN: ("TECHNICAL", "GOVERNANCE", "OPERATIONAL", "COMMERCIAL", "TRANSFER"),
}


@dataclass(frozen=True)
class CapabilityPromotionDecision:
    decision_id: str
    capability_id: str
    requested_lifecycle_state: str
    decision: str
    evaluated_evidence_dimensions: dict
    policy_name: str
    reason: str
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "CAPABILITY_PROMOTION_DECISION"

    def __post_init__(self):
        if self.decision not in _PROMOTION_DECISIONS:
            raise SubstrateError(f"invalid promotion decision {self.decision!r}")


class CapabilityPromotionGate:
    """A capability does not become reusable merely because code exists,
    one test ran, or a workflow mentioned it -- promotion requires the
    evidence dimensions the target lifecycle state's policy names to all
    be EVIDENCED. Policies are configurable per capability class (pass a
    different `policy` dict); apply_promotion() is the ONLY code in this
    module permitted to advance CapabilityGraph's lifecycle_state."""

    def __init__(self, policy: Optional[dict] = None, policy_name: str = "default"):
        self.policy = policy or DEFAULT_PROMOTION_POLICY
        self.policy_name = policy_name

    def evaluate(self, capability_record: dict, requested_lifecycle_state: str) -> CapabilityPromotionDecision:
        if requested_lifecycle_state not in _CAP_LIFECYCLE_ORDER:
            raise SubstrateError(f"unknown lifecycle state {requested_lifecycle_state!r}")
        current_index = _CAP_LIFECYCLE_ORDER.index(capability_record["lifecycle_state"])
        requested_index = _CAP_LIFECYCLE_ORDER.index(requested_lifecycle_state)
        if requested_index <= current_index:
            return CapabilityPromotionDecision(
                decision_id=_new_id("PROMO"), capability_id=capability_record["capability_id"],
                requested_lifecycle_state=requested_lifecycle_state, decision=REJECT,
                evaluated_evidence_dimensions=dict(capability_record["evidence_dimensions"]),
                policy_name=self.policy_name,
                reason=f"requested state {requested_lifecycle_state!r} is not forward of current {capability_record['lifecycle_state']!r}",
            )
        required_dims = self.policy.get(requested_lifecycle_state, ())
        dims = capability_record["evidence_dimensions"]
        missing = [d for d in required_dims if dims.get(d) != DIM_EVIDENCED]
        partial = [d for d in required_dims if dims.get(d) == DIM_PARTIAL]
        if missing and not partial:
            decision = NEEDS_MORE_EVIDENCE
            reason = f"missing evidence for dimension(s): {', '.join(missing)}"
        elif missing:
            decision = NEEDS_MORE_EVIDENCE
            reason = f"partial evidence only for dimension(s): {', '.join(partial)}; missing entirely: {', '.join(missing)}"
        else:
            decision = PROMOTE
            reason = f"all required dimensions EVIDENCED for {requested_lifecycle_state!r}: {', '.join(required_dims)}"
        return CapabilityPromotionDecision(
            decision_id=_new_id("PROMO"), capability_id=capability_record["capability_id"],
            requested_lifecycle_state=requested_lifecycle_state, decision=decision,
            evaluated_evidence_dimensions=dict(dims), policy_name=self.policy_name, reason=reason,
        )

    def apply_promotion(self, capability_graph: CapabilityGraph, decision: CapabilityPromotionDecision) -> bool:
        """Returns True iff the graph's lifecycle_state was actually
        advanced. HOLD/REJECT/NEEDS_MORE_EVIDENCE never touch the graph."""
        if decision.decision != PROMOTE:
            return False
        capability_graph._set_lifecycle_state(
            decision.capability_id, decision.requested_lifecycle_state,
            reason=f"promoted by {decision.decision_id}: {decision.reason}",
        )
        return True


# ---------------------------------------------------------------------------
# Section 16: Reachability Engine
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReachabilityDelta:
    delta_id: str
    trigger: str  # "capability_promoted" | "objective_arrived"
    trigger_ref_id: str
    capability_graph_version: int
    newly_reachable_objective_classes: tuple = ()
    newly_relevant_capabilities: tuple = ()
    dependency_basis: dict = field(default_factory=dict)  # objective_class -> tuple(capability_ids)
    evidence_basis: tuple = ()
    uncertainty: str = "deterministic graph reasoning only; no model inference applied"
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "REACHABILITY_DELTA"


class ReachabilityEngine:
    """Deterministic dependency-graph reasoning only -- no LLM required.
    objective_classes: dict[str, tuple[capability_id, ...]] mapping a
    named objective class to the capability_ids it requires (ALL must be
    available and dependency-satisfied for that class to be reachable)."""

    def __init__(self, capability_graph: CapabilityGraph, objective_classes: dict):
        self.capability_graph = capability_graph
        self.objective_classes = objective_classes

    def _currently_satisfied_classes(self) -> dict:
        satisfied = {}
        for class_name, required_ids in self.objective_classes.items():
            if all(self.capability_graph.is_available(cid) and self.capability_graph.dependencies_satisfied(cid) for cid in required_ids):
                satisfied[class_name] = tuple(required_ids)
        return satisfied

    def compute_delta_after_promotion(self, capability_id: str, previously_satisfied_classes: frozenset) -> ReachabilityDelta:
        now_satisfied = self._currently_satisfied_classes()
        newly_reachable = tuple(c for c in now_satisfied if c not in previously_satisfied_classes)
        return ReachabilityDelta(
            delta_id=_new_id("REACH"), trigger="capability_promoted", trigger_ref_id=capability_id,
            capability_graph_version=self.capability_graph.version(),
            newly_reachable_objective_classes=newly_reachable,
            newly_relevant_capabilities=(capability_id,),
            dependency_basis={c: now_satisfied[c] for c in newly_reachable},
            evidence_basis=tuple(f"capability_graph.is_available({cid})" for c in newly_reachable for cid in now_satisfied[c]),
        )

    def compute_relevant_capabilities_for_objective(self, objective: ObjectiveContract) -> ReachabilityDelta:
        relevant = tuple(
            cid for cid in objective.required_capability_ids
            if self.capability_graph.resolve_current(cid) is not None
        )
        return ReachabilityDelta(
            delta_id=_new_id("REACH"), trigger="objective_arrived", trigger_ref_id=objective.objective_id,
            capability_graph_version=self.capability_graph.version(),
            newly_relevant_capabilities=relevant,
        )


# ---------------------------------------------------------------------------
# Section 13/14: Outcome / commercial value model
# ---------------------------------------------------------------------------

OUTCOME_DIMENSIONS = ("technical_success", "operational_success", "customer_acceptance", "economic_result")
DIM_ACHIEVED = "ACHIEVED"
DIM_NOT_ACHIEVED = "NOT_ACHIEVED"
DIM_UNKNOWN = "UNKNOWN"
DIM_FAILURE = "FAILURE"
_OUTCOME_STATES = (DIM_ACHIEVED, DIM_NOT_ACHIEVED, DIM_UNKNOWN, DIM_FAILURE)


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    objective_id: str
    dimension_results: dict  # each of OUTCOME_DIMENSIONS -> one of _OUTCOME_STATES
    commercial_evidence_ids: tuple = ()
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "OUTCOME_RECORD"

    def __post_init__(self):
        envelope.validate_mission_id(self.outcome_id)
        for dim in OUTCOME_DIMENSIONS:
            if dim not in self.dimension_results:
                raise SubstrateError(f"OutcomeRecord missing required dimension {dim!r}")
            if self.dimension_results[dim] not in _OUTCOME_STATES:
                raise SubstrateError(f"invalid outcome state {self.dimension_results[dim]!r} for dimension {dim!r}")


# ---------------------------------------------------------------------------
# Section 11/12: Governance + Execution (the ONLY path to real fabric
# execution -- nothing else in this module may call fabric directly)
# ---------------------------------------------------------------------------

GOVERNANCE_APPROVED = "APPROVED"
GOVERNANCE_DENIED = "DENIED"
GOVERNANCE_NEEDS_HUMAN_APPROVAL = "NEEDS_HUMAN_APPROVAL"


@dataclass(frozen=True)
class GovernanceDecision:
    decision_id: str
    workflow_plan_id: str
    objective_id: str
    decision: str
    authority_actor_id: str
    reason: str
    created_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "GOVERNANCE_DECISION"


class GovernanceEngine:
    """External to every cognition/planning/capability object in this
    module by construction -- it is the only class whose job is to
    produce a GovernanceDecision, and it consults ONLY the WorkflowPlan
    and a real fabric.interface.AuthorityContext. It never reads
    economic_context, differential-cognition output, or capability
    advertisements -- Section 26/11's 'commercial value must NOT override
    governance' and 'model output != authority' are enforced by this
    method's signature never accepting those objects at all, not by a
    runtime check that could be routed around."""

    def decide(self, workflow_plan: WorkflowPlan, authority_context: fi.AuthorityContext) -> GovernanceDecision:
        if not workflow_plan.is_executable:
            return GovernanceDecision(
                decision_id=_new_id("GOV"), workflow_plan_id=workflow_plan.plan_id,
                objective_id=workflow_plan.objective_id, decision=GOVERNANCE_DENIED,
                authority_actor_id=authority_context.actor_id,
                reason=f"workflow plan has unresolved missing_capability_ids: {workflow_plan.missing_capability_ids}",
            )
        ungranted = [
            cid for cid in (workflow_plan.existing_capability_ids + workflow_plan.composable_capability_ids)
            if not fi.authority_permits(authority_context, cid)
        ]
        if ungranted:
            return GovernanceDecision(
                decision_id=_new_id("GOV"), workflow_plan_id=workflow_plan.plan_id,
                objective_id=workflow_plan.objective_id, decision=GOVERNANCE_DENIED,
                authority_actor_id=authority_context.actor_id,
                reason=f"authority_context does not grant required capability_id(s): {ungranted}",
            )
        return GovernanceDecision(
            decision_id=_new_id("GOV"), workflow_plan_id=workflow_plan.plan_id,
            objective_id=workflow_plan.objective_id, decision=GOVERNANCE_APPROVED,
            authority_actor_id=authority_context.actor_id,
            reason="workflow plan has no missing capabilities and authority_context grants every capability it uses",
        )


@dataclass(frozen=True)
class ExecutionRecord:
    execution_id: str
    workflow_plan_id: str
    governance_decision_id: str
    capability_id: str
    fabric_result_status: str
    fabric_receipt_id: Optional[str]
    started_at: str
    finished_at: str = field(default_factory=_now)
    schema_version: int = SCHEMA_VERSION
    record_type: str = "EXECUTION_RECORD"


def execute_workflow_step(workflow_plan: WorkflowPlan, governance_decision: GovernanceDecision,
                           capability_id: str, fabric_request: fi.RemoteCapabilityRequest,
                           transport, **fabric_kwargs) -> ExecutionRecord:
    """The ONLY function in this module that may call
    fabric.interface.process_remote_capability_request(). Refuses to run
    without an APPROVED GovernanceDecision bound to THIS EXACT
    WorkflowPlan (decision.workflow_plan_id must match) -- a
    GovernanceDecision for a different plan, or any non-APPROVED
    decision, raises GovernanceError instead of executing anything. This
    is the enforcement of Section 11, not merely its documentation."""
    if governance_decision.workflow_plan_id != workflow_plan.plan_id:
        raise GovernanceError(
            f"GovernanceDecision {governance_decision.decision_id} was made for workflow_plan_id "
            f"{governance_decision.workflow_plan_id!r}, not this plan's {workflow_plan.plan_id!r} -- refusing to execute"
        )
    if governance_decision.decision != GOVERNANCE_APPROVED:
        raise GovernanceError(
            f"GovernanceDecision {governance_decision.decision_id} is {governance_decision.decision!r}, not APPROVED -- refusing to execute"
        )
    if capability_id not in (workflow_plan.existing_capability_ids + workflow_plan.composable_capability_ids):
        raise GovernanceError(f"capability_id {capability_id!r} is not part of the approved workflow plan's usable capabilities")

    started_at = _now()
    result, receipt = fi.process_remote_capability_request(fabric_request, transport, **fabric_kwargs)
    return ExecutionRecord(
        execution_id=_new_id("EXEC"), workflow_plan_id=workflow_plan.plan_id,
        governance_decision_id=governance_decision.decision_id, capability_id=capability_id,
        fabric_result_status=result.status, fabric_receipt_id=receipt.receipt_id if receipt is not None else None,
        started_at=started_at,
    )


# ---------------------------------------------------------------------------
# Section 18: Memory architecture
# ---------------------------------------------------------------------------

class _AppendOnlyLedger:
    """Shared minimal ledger primitive for episodic/semantic/procedural
    memory -- same lock/atomic-write/JSONL discipline as CapabilityGraph/
    EvidenceLedger, factored out once these three needed the identical shape."""

    def __init__(self, path: Path, lock_path: Path, lock_timeout_seconds: float = 5.0):
        self.path = path
        self.lock_path = lock_path
        self.lock_timeout_seconds = lock_timeout_seconds

    def _read_all(self) -> list:
        if not self.path.exists():
            return []
        import json
        records = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line_number, raw_line in enumerate(f, start=1):
                if not raw_line.endswith("\n"):
                    raise envelope.LedgerIntegrityError(f"memory ledger {self.path} line {line_number} is not newline-terminated")
                line = raw_line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def append(self, record: dict) -> None:
        with envelope._FileLock(self.lock_path, timeout_seconds=self.lock_timeout_seconds):
            records = self._read_all()
            envelope._atomic_write_bytes(self.path, envelope._serialize_ledger(records + [record]))

    def list_all(self) -> tuple:
        return tuple(self._read_all())


MEMORY_PROMOTION_MIN_PROVENANCE = (OBSERVED, SYSTEM_ASSERTED, AUTHORIZED_CONCLUSION)


class MemoryPromotionError(SubstrateError):
    """Raised when a write to semantic/procedural memory is attempted
    without evidence meeting the minimum promotion policy."""


class MemoryStore:
    """Six memory classes (Section 18). EPISODIC accepts any well-formed
    record freely (raw observations). SEMANTIC and PROCEDURAL require at
    least one EvidenceRecord whose provenance is OBSERVED, SYSTEM_ASSERTED,
    or AUTHORIZED_CONCLUSION (never a bare UNVERIFIED_INTERPRETATION) --
    enforcing 'memory write != memory promotion' as an actual gate, not
    only a comment. CAPABILITY and EVIDENCE memory are CapabilityGraph and
    EvidenceLedger themselves (Section 8/12 already ARE those memory
    classes -- not duplicated here). TRUST_RELATIONSHIP memory is a
    read-only adapter over fabric.interface's own PairingStore/
    PeerIdentityStore -- never a separate copy of that state."""

    def __init__(self, root: Path, capability_graph: CapabilityGraph, evidence_ledger: EvidenceLedger,
                 pairing_store: Optional[fi.PairingStore] = None, peer_store: Optional[fi.PeerIdentityStore] = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.episodic = _AppendOnlyLedger(self.root / "episodic.jsonl", self.root / "episodic.lock")
        self._semantic = _AppendOnlyLedger(self.root / "semantic.jsonl", self.root / "semantic.lock")
        self._procedural = _AppendOnlyLedger(self.root / "procedural.jsonl", self.root / "procedural.lock")
        self.capability = capability_graph  # Section 18's CAPABILITY memory class
        self.evidence = evidence_ledger  # Section 18's EVIDENCE memory class
        self.pairing_store = pairing_store  # Section 18's TRUST_RELATIONSHIP memory class (view only)
        self.peer_store = peer_store

    def write_episodic(self, signal_or_inference) -> None:
        self.episodic.append(_to_plain_dict(signal_or_inference))

    def _evidence_supports_promotion(self, evidence_ids: tuple) -> bool:
        if not evidence_ids:
            return False
        all_evidence = {r["evidence_id"]: r for r in self.evidence.list_all()}
        for eid in evidence_ids:
            record = all_evidence.get(eid)
            if record is None or record["provenance"] not in MEMORY_PROMOTION_MIN_PROVENANCE:
                return False
        return True

    def promote_to_semantic(self, record: dict, evidence_ids: tuple) -> None:
        if not self._evidence_supports_promotion(evidence_ids):
            raise MemoryPromotionError(
                f"cannot promote to semantic memory: evidence_ids {evidence_ids!r} do not all resolve to "
                f"EvidenceRecords with provenance in {MEMORY_PROMOTION_MIN_PROVENANCE}"
            )
        self._semantic.append({**record, "promoted_from_evidence_ids": list(evidence_ids), "promoted_at": _now()})

    def promote_to_procedural(self, record: dict, evidence_ids: tuple) -> None:
        if not self._evidence_supports_promotion(evidence_ids):
            raise MemoryPromotionError(
                f"cannot promote to procedural memory: evidence_ids {evidence_ids!r} do not all resolve to "
                f"EvidenceRecords with provenance in {MEMORY_PROMOTION_MIN_PROVENANCE}"
            )
        self._procedural.append({**record, "promoted_from_evidence_ids": list(evidence_ids), "promoted_at": _now()})

    def list_semantic(self) -> tuple:
        return self._semantic.list_all()

    def list_procedural(self) -> tuple:
        return self._procedural.list_all()

    def trust_relationship_status(self, relationship_id: str, peer_id: Optional[str] = None) -> dict:
        """Reads (never copies) live status from the real pairing/peer
        stores -- TRUST_RELATIONSHIP memory is a view, not a duplicate."""
        if self.pairing_store is None:
            raise SubstrateError("no pairing_store configured on this MemoryStore")
        out = {"relationship_id": relationship_id, "status": self.pairing_store.status_of(relationship_id)}
        if peer_id is not None and self.peer_store is not None:
            out["peer_id"] = peer_id
            out["peer_status"] = self.peer_store.status_of(peer_id)
            out["bound"] = self.peer_store.is_relationship_bound_to_peer(peer_id, relationship_id)
        return out


def _to_plain_dict(obj) -> dict:
    """Converts any frozen dataclass in this module's object model into a
    plain JSON-safe dict for ledger storage, tuples->lists."""
    import dataclasses
    if dataclasses.is_dataclass(obj):
        d = dataclasses.asdict(obj)
    elif isinstance(obj, dict):
        d = dict(obj)
    else:
        raise SubstrateError(f"cannot convert {type(obj).__name__} to a ledger record")
    return d
