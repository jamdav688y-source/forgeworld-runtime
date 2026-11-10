"""The node store: one SQLite database per device (Stages B, C, E).

Append-only by construction:
  * `events` rows can never be DELETEd (trigger) and their header, signature,
    identity and order can never be UPDATEd (trigger). The only permitted
    row change is the payload column: WITHHELD -> PRESENT (backfill, hash
    checked in code) or -> PURGED (authorized deletion / retention).
  * `receipts` rows can never be updated or deleted (trigger).
  * Corrections are new events (header.corrects), never rewrites.

Original source artifacts live in `artifacts` (content addressed, raw bytes),
separate from derived text (events, FTS index).

Durability: WAL + synchronous=FULL; every material transition is one
BEGIN IMMEDIATE ... COMMIT transaction, so a killed process leaves either the
whole transition or none of it (test_recovery proves this by os._exit inside
a transaction).
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from omega import policy, receipts
from omega.canonical import canonical, digest, sha256_hex
from omega.events import Event, EventError, build_header, event_id_for, from_envelope, validate
from omega.identity import DeviceIdentity, b64d, b64e, verify

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  local_order INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT UNIQUE NOT NULL,
  device_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  ts TEXT NOT NULL,
  privacy TEXT NOT NULL,
  header TEXT NOT NULL,
  signature TEXT NOT NULL,
  payload TEXT,
  payload_state TEXT NOT NULL CHECK(payload_state IN ('PRESENT','WITHHELD','PURGED')),
  origin TEXT NOT NULL CHECK(origin IN ('LOCAL','IMPORTED')),
  imported_from TEXT,
  UNIQUE(device_id, seq));
CREATE INDEX IF NOT EXISTS events_type ON events(event_type);
CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_immutable BEFORE UPDATE ON events
WHEN NEW.event_id IS NOT OLD.event_id OR NEW.header IS NOT OLD.header
  OR NEW.signature IS NOT OLD.signature OR NEW.device_id IS NOT OLD.device_id
  OR NEW.seq IS NOT OLD.seq OR NEW.origin IS NOT OLD.origin
  OR NEW.local_order IS NOT OLD.local_order OR NEW.event_type IS NOT OLD.event_type
  OR NEW.ts IS NOT OLD.ts OR NEW.privacy IS NOT OLD.privacy
  OR NEW.imported_from IS NOT OLD.imported_from
  OR NOT ((OLD.payload_state = 'WITHHELD' AND NEW.payload_state = 'PRESENT')
       OR (NEW.payload_state = 'PURGED' AND NEW.payload IS NULL))
BEGIN SELECT RAISE(ABORT, 'event history is immutable'); END;
CREATE TABLE IF NOT EXISTS edges(child TEXT NOT NULL, parent TEXT NOT NULL, kind TEXT NOT NULL,
  PRIMARY KEY(child, parent, kind));
CREATE INDEX IF NOT EXISTS edges_parent ON edges(parent);
CREATE TABLE IF NOT EXISTS links(event_id TEXT NOT NULL, entity TEXT NOT NULL, PRIMARY KEY(entity, event_id));
CREATE TABLE IF NOT EXISTS artifacts(sha256 TEXT PRIMARY KEY, media_type TEXT NOT NULL, size INTEGER NOT NULL,
  data BLOB, state TEXT NOT NULL CHECK(state IN ('PRESENT','PURGED')));
CREATE TABLE IF NOT EXISTS receipts(idx INTEGER PRIMARY KEY, receipt_id TEXT UNIQUE NOT NULL,
  body TEXT NOT NULL, signature TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are append-only'); END;
CREATE TABLE IF NOT EXISTS conflicts(conflict_id TEXT PRIMARY KEY, kind TEXT NOT NULL, key TEXT NOT NULL,
  detail TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS peers(device_id TEXT PRIMARY KEY, label TEXT NOT NULL, sign_pub TEXT NOT NULL,
  kx_pub TEXT NOT NULL, max_privacy TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
  last_vector TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS seen_nonces(nonce TEXT PRIMARY KEY, peer TEXT NOT NULL, context TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS local_exec(task_id TEXT PRIMARY KEY, state TEXT NOT NULL, lease_until INTEGER,
  attempts INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS quarantine(id INTEGER PRIMARY KEY AUTOINCREMENT, peer TEXT, reason TEXT NOT NULL,
  envelope TEXT NOT NULL);
"""

FTS_SQL = "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(event_id UNINDEXED, body)"
FTS_FALLBACK_SQL = "CREATE TABLE IF NOT EXISTS fts(event_id TEXT, body TEXT)"

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class StoreError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ImportResult:
    code: str                 # IMPORTED | DUPLICATE | BACKFILLED | REJECTED | EQUIVOCATION | GAP
    event_id: Optional[str]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.code in ("IMPORTED", "DUPLICATE", "BACKFILLED")


def utc_ts(t: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if t is None else t))


def _fault(point: str):
    """Test-only crash injection: OMEGA_FAULT=<point> kills the process
    without cleanup (as a power loss or `kill -9` would)."""
    if os.environ.get("OMEGA_FAULT") == point:
        os._exit(91)


def actor_kind_of(actor: str) -> str:
    kind = actor.split(":", 1)[0].upper()
    if kind not in policy.ACTOR_KINDS or ":" not in actor:
        raise StoreError("ACTOR_INVALID", f"actor must be '<human|model|tool|system>:<name>', got {actor!r}")
    return kind


class Node:
    """A device's local substrate. Fully usable with no network and no peer."""

    def __init__(self, path: Path, identity: DeviceIdentity, conn: sqlite3.Connection, info: dict):
        self.path = Path(path)
        self.identity = identity
        self.device_id = identity.device_id
        self.conn = conn
        self.info = info
        self.lock = threading.RLock()
        self.clock = utc_ts
        self.fts5 = info.get("fts5", True)

    # ------------------------------------------------------------------ open
    @classmethod
    def init(cls, path, label: str, profile: str = "pocket", clone_identity_from=None) -> "Node":
        """Create a new node. clone_identity_from is for determinism tests and
        disaster recovery only: it copies an existing identity directory."""
        path = Path(path)
        if (path / "node.json").exists():
            raise StoreError("NODE_EXISTS", f"{path} already holds a node; refusing to overwrite")
        path.mkdir(parents=True, exist_ok=True)
        if clone_identity_from is not None:
            import shutil
            shutil.copytree(Path(clone_identity_from), path / "identity")
            identity = DeviceIdentity.load(path / "identity")
        else:
            identity = DeviceIdentity.create(path / "identity")
        info = {"label": label, "profile": profile, "device_id": identity.device_id,
                "schema": "fw.omega.node/1"}
        conn = cls._connect(path)
        try:
            conn.execute(FTS_SQL)
            info["fts5"] = True
        except sqlite3.OperationalError:
            conn.execute(FTS_FALLBACK_SQL)
            info["fts5"] = False
        conn.execute("INSERT OR REPLACE INTO meta VALUES('device_id', ?)", (identity.device_id,))
        conn.execute("INSERT OR REPLACE INTO meta VALUES('sign_pub', ?)", (b64e(identity.sign_pub),))
        tmp = path / "node.json.tmp"
        tmp.write_text(json.dumps(info, indent=2, sort_keys=True))
        os.replace(tmp, path / "node.json")
        return cls(path, identity, conn, info)

    @classmethod
    def open(cls, path) -> "Node":
        path = Path(path)
        info = json.loads((path / "node.json").read_text())
        identity = DeviceIdentity.load(path / "identity")
        if identity.device_id != info["device_id"]:
            raise StoreError("IDENTITY_MISMATCH", "identity keys do not match node.json")
        conn = cls._connect(path)
        stored = conn.execute("SELECT value FROM meta WHERE key='device_id'").fetchone()
        if not stored or stored[0] != identity.device_id:
            raise StoreError("IDENTITY_MISMATCH", "database belongs to another device")
        return cls(path, identity, conn, info)

    @staticmethod
    def _connect(path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path / "node.db"), isolation_level=None, check_same_thread=False,
                               timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.executescript(SCHEMA_SQL)
        return conn

    def close(self):
        with self.lock:
            self.conn.close()

    # ------------------------------------------------------------- tx helper
    class _Tx:
        def __init__(self, node):
            self.node = node

        def __enter__(self):
            self.node.lock.acquire()
            self.node.conn.execute("BEGIN IMMEDIATE")
            return self.node.conn

        def __exit__(self, et, ev, tb):
            try:
                if et is None:
                    self.node.conn.execute("COMMIT")
                else:
                    self.node.conn.execute("ROLLBACK")
            finally:
                self.node.lock.release()
            return False

    def tx(self):
        return Node._Tx(self)

    # --------------------------------------------------------------- queries
    def pubkey_for(self, device_id: str) -> Optional[bytes]:
        if device_id == self.device_id:
            return self.identity.sign_pub
        row = self.conn.execute("SELECT sign_pub FROM peers WHERE device_id=?", (device_id,)).fetchone()
        return b64d(row[0]) if row else None

    def peer(self, device_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT device_id,label,sign_pub,kx_pub,max_privacy,revoked,last_vector "
                                "FROM peers WHERE device_id=?", (device_id,)).fetchone()
        if not row:
            return None
        return {"device_id": row[0], "label": row[1], "sign_pub": b64d(row[2]), "kx_pub": b64d(row[3]),
                "max_privacy": row[4], "revoked": bool(row[5]), "last_vector": json.loads(row[6])}

    def peers(self) -> list:
        return [self.peer(r[0]) for r in self.conn.execute("SELECT device_id FROM peers ORDER BY device_id")]

    def vector(self) -> dict:
        return {d: s for d, s in self.conn.execute(
            "SELECT device_id, MAX(seq) FROM events GROUP BY device_id ORDER BY device_id")}

    def state_digest(self) -> str:
        purged = [r[0] for r in self.conn.execute(
            "SELECT event_id FROM events WHERE payload_state='PURGED' ORDER BY event_id")]
        return "st_" + digest("state", {"vector": self.vector(), "purged": purged})

    def _row_to_event(self, row) -> Event:
        header, sig, payload = json.loads(row[0]), row[1], row[2]
        return Event(header=header, signature=sig, payload=json.loads(payload) if payload is not None else None)

    def get(self, event_id: str) -> Optional[Event]:
        row = self.conn.execute("SELECT header, signature, payload FROM events WHERE event_id=?",
                                (event_id,)).fetchone()
        return self._row_to_event(row) if row else None

    def payload_state(self, event_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT payload_state FROM events WHERE event_id=?", (event_id,)).fetchone()
        return row[0] if row else None

    def origin_of(self, event_id: str) -> Optional[str]:
        row = self.conn.execute("SELECT origin FROM events WHERE event_id=?", (event_id,)).fetchone()
        return row[0] if row else None

    def events(self, event_type: Optional[str] = None, entity: Optional[str] = None) -> list:
        """Events in local order, optionally filtered by type and/or linked entity."""
        sql = "SELECT e.header, e.signature, e.payload FROM events e"
        args, where = [], []
        if entity is not None:
            sql += " JOIN links l ON l.event_id = e.event_id"
            where.append("l.entity = ?")
            args.append(entity)
        if event_type is not None:
            where.append("e.event_type = ?")
            args.append(event_type)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY e.local_order"
        return [self._row_to_event(r) for r in self.conn.execute(sql, args)]

    def ancestors(self, event_id: str) -> set:
        seen, stack = set(), [event_id]
        while stack:
            cur = stack.pop()
            for (p,) in self.conn.execute("SELECT parent FROM edges WHERE child=?", (cur,)):
                if p not in seen:
                    seen.add(p)
                    stack.append(p)
        return seen

    def search(self, query: str, entity: Optional[str] = None, limit: int = 20) -> list:
        """Offline full-text search over derived text. Purged payloads are not
        indexed. Returns event ids (best match first)."""
        terms = [t for t in "".join(c if c.isalnum() else " " for c in query.lower()).split() if t]
        if not terms:
            return []
        if self.fts5:
            q = " ".join(f'"{t}"' for t in terms)
            rows = self.conn.execute("SELECT event_id FROM fts WHERE fts MATCH ? ORDER BY rank LIMIT ?",
                                     (q, limit * 5)).fetchall()
        else:
            sql = "SELECT event_id FROM fts WHERE " + " AND ".join("lower(body) LIKE ?" for _ in terms)
            rows = self.conn.execute(sql, [f"%{t}%" for t in terms]).fetchall()
        ids = [r[0] for r in rows]
        if entity is not None:
            allowed = {r[0] for r in self.conn.execute("SELECT event_id FROM links WHERE entity=?", (entity,))}
            ids = [i for i in ids if i in allowed]
        return ids[:limit]

    # ------------------------------------------------------------- artifacts
    def put_artifact(self, conn, data: bytes, media_type: str) -> str:
        if len(data) > MAX_ARTIFACT_BYTES:
            raise StoreError("ARTIFACT_TOO_LARGE", f"{len(data)} bytes")
        sha = sha256_hex(data)
        conn.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?, 'PRESENT')", (sha, media_type, len(data), data))
        return sha

    def artifact(self, sha: str) -> Optional[bytes]:
        row = self.conn.execute("SELECT data FROM artifacts WHERE sha256=? AND state='PRESENT'", (sha,)).fetchone()
        return bytes(row[0]) if row else None

    def has_artifact(self, sha: str) -> bool:
        return self.conn.execute("SELECT 1 FROM artifacts WHERE sha256=?", (sha,)).fetchone() is not None

    def import_artifact(self, sha: str, data: bytes, media_type: str) -> bool:
        if sha256_hex(data) != sha:
            return False
        with self.tx() as conn:
            row = conn.execute("SELECT state FROM artifacts WHERE sha256=?", (sha,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO artifacts VALUES(?,?,?,?, 'PRESENT')", (sha, media_type, len(data), data))
        return True

    # ---------------------------------------------------------------- append
    def append(self, event_type: str, payload: dict, *, actor: str, links: Iterable[str] = (),
               privacy: str = "PRIVATE", provenance: Iterable[dict] = (), parents: Iterable[str] = (),
               artifacts: Iterable[str] = (), verification: str = "UNVERIFIED",
               supersedes: Optional[str] = None, corrects: Optional[str] = None,
               artifact_data: Optional[list] = None, receipt: bool = True) -> Event:
        """Create, sign and commit one local event (one transaction).
        artifact_data: optional [(bytes, media_type)] stored as original sources
        and added to header.artifacts."""
        kind = actor_kind_of(actor)
        parents = set(parents)
        if supersedes:
            parents.add(supersedes)
        if corrects:
            parents.add(corrects)
        if event_type == "DELETION_AUTHORIZED":
            parents.add(payload.get("target_event", ""))
        with self.tx() as conn:
            arts = set(artifacts)
            for data, mt in artifact_data or ():
                arts.add(self.put_artifact(conn, data, mt))
            for a in arts:
                if not self.has_artifact(a):
                    raise StoreError("ARTIFACT_UNKNOWN", a)
            for p in parents:
                if not conn.execute("SELECT 1 FROM events WHERE event_id=?", (p,)).fetchone():
                    raise StoreError("PARENT_UNKNOWN", p)
            before = self.state_digest()
            row = conn.execute("SELECT seq, event_id FROM events WHERE device_id=? ORDER BY seq DESC LIMIT 1",
                               (self.device_id,)).fetchone()
            seq, prev = (row[0] + 1, row[1]) if row else (1, None)
            header = build_header(event_type=event_type, device_id=self.device_id, actor_id=actor,
                                  actor_kind=kind, seq=seq, prev=prev, ts=self.clock(), payload=payload,
                                  parents=parents, artifacts=arts, provenance=list(provenance),
                                  links=links, privacy=privacy, verification=verification,
                                  supersedes=supersedes, corrects=corrects)
            try:
                validate(header, payload)
            except EventError as exc:
                raise StoreError(exc.code, exc.detail)
            self._semantic_checks(conn, header, payload)
            eid = event_id_for(header)
            ev = Event(header=header, signature=self.identity.sign(eid.encode("ascii")), payload=payload)
            self._insert(conn, ev, "LOCAL", None)
            _fault("append:after_insert")
            self._apply_effects(conn, ev)
            if receipt:
                receipts.issue(self, conn, "EVENT_APPENDED", [eid], before, self.state_digest(),
                               {"event_type": event_type, "seq": seq})
            return ev

    def _semantic_checks(self, conn, header, payload):
        et = header["event_type"]
        if et == "TASK_AUTHORIZED":
            row = conn.execute("SELECT header, payload FROM events WHERE event_id=?",
                               (payload["task_event"],)).fetchone()
            if not row or json.loads(row[0])["event_type"] != "TASK_QUEUED" \
                    or row[1] is None or json.loads(row[1])["task_id"] != payload["task_id"]:
                raise StoreError("TASK_UNKNOWN", payload["task_id"])
        if et == "DELETION_AUTHORIZED":
            if not conn.execute("SELECT 1 FROM events WHERE event_id=?", (payload["target_event"],)).fetchone():
                raise StoreError("PARENT_UNKNOWN", payload["target_event"])

    def _insert(self, conn, ev: Event, origin: str, from_peer: Optional[str]):
        h = ev.header
        eid = event_id_for(h)
        local_only = h["privacy"] == policy.DEVICE_LOCAL and origin == "IMPORTED"
        payload = None if (ev.payload is None or local_only) else ev.payload
        conn.execute(
            "INSERT INTO events(event_id, device_id, seq, event_type, ts, privacy, header, signature, payload,"
            " payload_state, origin, imported_from) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, h["device_id"], h["seq"], h["event_type"], h["ts"], h["privacy"],
             canonical(h).decode("utf-8"), ev.signature,
             canonical(payload).decode("utf-8") if payload is not None else None,
             "PRESENT" if payload is not None else "WITHHELD", origin, from_peer))
        edges = [(h["prev"], "prev")] if h["prev"] else []
        edges += [(p, "parent") for p in h["parents"]]
        edges += [(h[k], k) for k in ("supersedes", "corrects") if h[k]]
        for parent, kind in edges:
            conn.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?)", (eid, parent, kind))
        for ent in h["links"]:
            conn.execute("INSERT OR IGNORE INTO links VALUES(?,?)", (eid, ent))
        if payload is not None:
            self._index(conn, eid, h, payload)

    def _index(self, conn, eid, header, payload):
        texts = [str(v) for k, v in sorted(payload.items())
                 if isinstance(v, str) and k in ("text", "value", "display_name", "summary", "name",
                                                  "attribute", "opinion", "hypothesis", "locator")]
        texts += [a for a in payload.get("aliases", []) if isinstance(a, str)] if isinstance(payload.get("aliases"), list) else []
        if texts:
            conn.execute("INSERT INTO fts(event_id, body) VALUES(?,?)", (eid, "\n".join(texts)))

    def _apply_effects(self, conn, ev: Event):
        et, p = ev.header["event_type"], ev.payload
        if p is None:
            return
        if et == "DELETION_AUTHORIZED":
            self._purge(conn, p["target_event"])
        elif et == "ACCESS_REVOKED" and ev.header["device_id"] == self.device_id:
            conn.execute("UPDATE peers SET revoked=1 WHERE device_id=?", (p["peer_device_id"],))

    def _purge(self, conn, target: str):
        row = conn.execute("SELECT header FROM events WHERE event_id=?", (target,)).fetchone()
        if not row:
            return
        conn.execute("UPDATE events SET payload=NULL, payload_state='PURGED' WHERE event_id=?", (target,))
        conn.execute("DELETE FROM fts WHERE event_id=?", (target,))
        for sha in json.loads(row[0])["artifacts"]:
            still_used = conn.execute(
                "SELECT COUNT(*) FROM events WHERE payload_state!='PURGED' AND event_id!=? AND header LIKE ?",
                (target, f"%{sha}%")).fetchone()[0]
            if not still_used:
                conn.execute("UPDATE artifacts SET data=NULL, state='PURGED' WHERE sha256=?", (sha,))

    # ---------------------------------------------------------------- import
    def import_event(self, env: dict, from_peer: Optional[str] = None) -> ImportResult:
        """Verify and import one foreign event. Idempotent; never rewrites."""
        try:
            ev = from_envelope(env)
            validate(ev.header, ev.payload)
        except EventError as exc:
            self._quarantine(from_peer, exc.code, env)
            return ImportResult("REJECTED", None, exc.code)
        h = ev.header
        eid = event_id_for(h)
        pub = self.pubkey_for(h["device_id"])
        if pub is None:
            self._quarantine(from_peer, "UNKNOWN_DEVICE", env)
            return ImportResult("REJECTED", eid, "UNKNOWN_DEVICE")
        peer = self.peer(h["device_id"])
        if peer and peer["revoked"]:
            return ImportResult("REJECTED", eid, "DEVICE_REVOKED")
        if not verify(pub, ev.signature, eid.encode("ascii")):
            self._quarantine(from_peer, "SIGNATURE_INVALID", env)
            return ImportResult("REJECTED", eid, "SIGNATURE_INVALID")
        with self.tx() as conn:
            row = conn.execute("SELECT payload_state FROM events WHERE event_id=?", (eid,)).fetchone()
            if row:
                if row[0] == "WITHHELD" and ev.payload is not None and h["privacy"] != policy.DEVICE_LOCAL:
                    conn.execute("UPDATE events SET payload=?, payload_state='PRESENT' WHERE event_id=?",
                                 (canonical(ev.payload).decode("utf-8"), eid))
                    self._index(conn, eid, h, ev.payload)
                    return ImportResult("BACKFILLED", eid)
                return ImportResult("DUPLICATE", eid)
            clash = conn.execute("SELECT event_id FROM events WHERE device_id=? AND seq=?",
                                 (h["device_id"], h["seq"])).fetchone()
            if clash:
                cid = "cf_" + digest("conflict", ["EQUIVOCATION", h["device_id"], h["seq"], sorted([clash[0], eid])])
                conn.execute("INSERT OR IGNORE INTO conflicts VALUES(?,?,?,?,?)",
                             (cid, "EQUIVOCATION", f"{h['device_id']}#{h['seq']}",
                              json.dumps({"stored": clash[0], "offered": eid, "from": from_peer}), "OPEN"))
                conn.execute("INSERT INTO quarantine(peer, reason, envelope) VALUES(?,?,?)",
                             (from_peer, "EQUIVOCATION", json.dumps(env)))
                return ImportResult("EQUIVOCATION", eid, clash[0])
            have = conn.execute("SELECT MAX(seq) FROM events WHERE device_id=?", (h["device_id"],)).fetchone()[0] or 0
            if h["seq"] != have + 1:
                return ImportResult("GAP", eid, f"have {have}, offered {h['seq']}")
            if h["prev"] is not None:
                prev = conn.execute("SELECT event_id FROM events WHERE device_id=? AND seq=?",
                                    (h["device_id"], h["seq"] - 1)).fetchone()
                if not prev or prev[0] != h["prev"]:
                    return ImportResult("REJECTED", eid, "CHAIN_BROKEN")
            for p in h["parents"] + [h[k] for k in ("supersedes", "corrects") if h[k]]:
                if not conn.execute("SELECT 1 FROM events WHERE event_id=?", (p,)).fetchone():
                    return ImportResult("GAP", eid, f"missing parent {p}")
            self._insert(conn, ev, "IMPORTED", from_peer)
            _fault("import:after_insert")
            if ev.payload is not None and h["privacy"] != policy.DEVICE_LOCAL:
                self._apply_effects(conn, ev)
            return ImportResult("IMPORTED", eid)

    def _quarantine(self, peer, reason, env):
        with self.tx() as conn:
            conn.execute("INSERT INTO quarantine(peer, reason, envelope) VALUES(?,?,?)",
                         (peer, reason, json.dumps(env, default=str)[:100000]))

    def events_for_peer(self, peer_vector: dict, max_privacy: str, limit: int = 200) -> list:
        """Envelopes the peer lacks, in this node's local (causal) order.
        Payloads above the peer's clearance are withheld; headers always go,
        so per-device chains stay contiguous and verifiable."""
        out = []
        for row in self.conn.execute(
                "SELECT header, signature, payload, device_id, seq, privacy FROM events ORDER BY local_order"):
            if row[4] <= peer_vector.get(row[3], 0):
                continue
            include = row[2] is not None and policy.privacy_allows(row[5], max_privacy)
            out.append({"header": json.loads(row[0]), "signature": row[1],
                        "payload": json.loads(row[2]) if include else None})
            if len(out) >= limit:
                break
        return out

    def withheld_backfill_for_peer(self, peer_withheld: list, max_privacy: str) -> list:
        out = []
        for eid in peer_withheld:
            row = self.conn.execute("SELECT header, signature, payload, privacy FROM events WHERE event_id=?",
                                    (eid,)).fetchone()
            if row and row[2] is not None and policy.privacy_allows(row[3], max_privacy):
                out.append({"header": json.loads(row[0]), "signature": row[1], "payload": json.loads(row[2])})
        return out

    def withheld_ids(self) -> list:
        return [r[0] for r in self.conn.execute(
            "SELECT event_id FROM events WHERE payload_state='WITHHELD' AND privacy!='DEVICE_LOCAL' "
            "ORDER BY local_order")]

    # --------------------------------------------------------------- peers
    def add_peer(self, offer: dict, my_offer: dict, sas_entered: str, *, actor: str,
                 max_privacy: str = "PRIVATE") -> Event:
        """Record a human-confirmed pairing. sas_entered must equal the SAS the
        operator saw on BOTH devices."""
        from omega.identity import short_auth_string, PairingError
        if my_offer["device_id"] != self.device_id:
            raise PairingError("my_offer was not produced by this device")
        if offer["device_id"] == self.device_id:
            raise PairingError("cannot pair with self")
        if sas_entered != short_auth_string(offer, my_offer):
            raise PairingError("short authentication string mismatch: pairing refused")
        if actor_kind_of(actor) != "HUMAN":
            raise PairingError("pairing requires a human")
        with self.tx() as conn:
            conn.execute("INSERT OR REPLACE INTO peers(device_id,label,sign_pub,kx_pub,max_privacy,revoked) "
                         "VALUES(?,?,?,?,?,0)", (offer["device_id"], offer["label"], offer["sign_pub"],
                                                  offer["kx_pub"], max_privacy))
        return self.append("PEER_PAIRED", {"peer_device_id": offer["device_id"], "label": offer["label"],
                                           "max_privacy": max_privacy},
                           actor=actor, privacy=policy.DEVICE_LOCAL)

    def revoke_peer(self, device_id: str, *, actor: str, reason: str = "operator revoked") -> Event:
        return self.append("ACCESS_REVOKED", {"peer_device_id": device_id, "reason": reason},
                           actor=actor, privacy=policy.DEVICE_LOCAL)

    def set_peer_vector(self, device_id: str, vector: dict):
        with self.tx() as conn:
            conn.execute("UPDATE peers SET last_vector=? WHERE device_id=?", (json.dumps(vector, sort_keys=True), device_id))

    def remember_nonce(self, nonce: str, peer: str, context: str) -> bool:
        """False if this nonce was seen before (replay)."""
        with self.tx() as conn:
            if conn.execute("SELECT 1 FROM seen_nonces WHERE nonce=?", (nonce,)).fetchone():
                return False
            conn.execute("INSERT INTO seen_nonces VALUES(?,?,?)", (nonce, peer, context))
            return True

    # ----------------------------------------------------------- deletion
    def authorize_deletion(self, target_event: str, reason: str, *, actor: str) -> Event:
        return self.append("DELETION_AUTHORIZED", {"target_event": target_event, "reason": reason},
                           actor=actor, privacy="INTERNAL")

    def apply_retention(self, now: Optional[float] = None) -> list:
        """Purge payloads older than human-authorized RETENTION_POLICY limits.
        Deterministic: every node holding the same policy purges the same set."""
        now = time.time() if now is None else now
        purged = []
        policies = [e for e in self.events("RETENTION_POLICY") if e.payload]
        with self.tx() as conn:
            before = self.state_digest()
            for pol in policies:
                cutoff = utc_ts(now - pol.payload["max_age_days"] * 86400)
                for (eid,) in conn.execute(
                        "SELECT event_id FROM events WHERE event_type=? AND ts < ? AND payload_state!='PURGED' "
                        "ORDER BY local_order", (pol.payload["event_type"], cutoff)).fetchall():
                    self._purge(conn, eid)
                    purged.append(eid)
            if purged:
                receipts.issue(self, conn, "RETENTION_PURGE", purged, before, self.state_digest(),
                               {"policies": [event_id_for(p.header) for p in policies]})
        return purged

    # ------------------------------------------------------------ integrity
    def verify_integrity(self) -> dict:
        """Recompute every event id, signature, payload hash, per-device chain
        and the receipt chain. Returns {"ok": bool, "problems": [...]}."""
        from omega.events import payload_hash
        problems, last = [], {}
        for row in self.conn.execute("SELECT event_id, header, signature, payload, payload_state, device_id, seq "
                                     "FROM events ORDER BY device_id, seq"):
            eid, header = row[0], json.loads(row[1])
            if event_id_for(header) != eid:
                problems.append(("EVENT_ID_MISMATCH", eid))
            pub = self.pubkey_for(row[5])
            if pub is None or not verify(pub, row[2], eid.encode("ascii")):
                problems.append(("SIGNATURE_INVALID", eid))
            if row[3] is not None and payload_hash(json.loads(row[3])) != header["payload_hash"]:
                problems.append(("PAYLOAD_HASH_MISMATCH", eid))
            prev_seq, prev_id = last.get(row[5], (0, None))
            if row[6] != prev_seq + 1 or header["prev"] != prev_id:
                problems.append(("CHAIN_BROKEN", eid))
            last[row[5]] = (row[6], eid)
        problems += receipts.verify_chain(self)
        qc = self.conn.execute("PRAGMA integrity_check").fetchone()[0]
        if qc != "ok":
            problems.append(("SQLITE_INTEGRITY", qc))
        return {"ok": not problems, "problems": problems, "events": sum(s for s in self.vector().values()),
                "state_digest": self.state_digest()}

    def backup(self, dest: Path) -> Path:
        """Consistent online backup (SQLite backup API) for rollback."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            target = sqlite3.connect(str(dest))
            self.conn.backup(target)
            target.close()
        return dest
