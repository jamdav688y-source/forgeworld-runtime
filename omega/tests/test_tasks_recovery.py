"""Unauthorized command refusal (12) and recovery after process termination (13)."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from omega.store import Node
from omega.tasks import Executor, TaskQueue
from omega.tests.conftest import HUMAN, run_pipe_sync

ROOT = Path(__file__).resolve().parent.parent.parent


def make_queue(node, calls):
    return TaskQueue(node, {
        "send_message": Executor(lambda a: calls.append(("send", a)) or "sent", external=True),
        "reindex": Executor(lambda a: calls.append(("reindex", a)) or "done", external=False),
        "sneaky": Executor(lambda a: calls.append(("sneaky", a)) or "posted", external=True),
    })


def test_external_task_needs_local_human_authorization(phone):
    calls = []
    q = make_queue(phone, calls)
    t_ext = q.queue("send_message", {"to": "dana", "text": "hi"}, actor="model:assistant", external_effect=True)
    t_int = q.queue("reindex", {}, actor="system:scheduler", external_effect=False)
    t_lie = q.queue("sneaky", {}, actor="model:assistant", external_effect=False)  # executor is external: stricter wins
    t_unknown = q.queue("wire_money", {"amount": 1}, actor="model:assistant", external_effect=True)
    out = dict(q.run_once())
    assert out[t_ext] == "AWAITING_AUTHORIZATION" and out[t_lie] == "AWAITING_AUTHORIZATION"
    assert out[t_int] == "SUCCEEDED" and out[t_unknown] == "REFUSED_UNKNOWN_ACTION"
    assert calls == [("reindex", {})]
    q.authorize(t_ext, actor=HUMAN)
    out = dict(q.run_once())
    assert out[t_ext] == "SUCCEEDED" and calls[-1][0] == "send"
    assert q.run_once() == [(t_lie, "AWAITING_AUTHORIZATION")]  # nothing re-runs


def test_model_cannot_authorize(phone):
    q = make_queue(phone, [])
    t = q.queue("send_message", {}, actor="model:assistant", external_effect=True)
    import pytest
    from omega.store import StoreError
    with pytest.raises(StoreError) as e:
        q.authorize(t, actor="model:assistant")
    assert e.value.code == "ACTOR_NOT_PERMITTED"


def test_sync_never_executes_and_remote_authorization_does_not_count(paired):
    phone, pc = paired
    calls_pc, calls_phone = [], []
    qp, qc = make_queue(phone, calls_phone), make_queue(pc, calls_pc)
    t = qp.queue("send_message", {"to": "dana"}, actor=HUMAN, external_effect=True)
    qp.authorize(t, actor=HUMAN)   # authorized on the PHONE
    run_pipe_sync(phone, pc)
    assert calls_pc == [] and calls_phone == []          # sync itself ran nothing
    assert dict(qc.run_once())[t] == "AWAITING_AUTHORIZATION"  # phone's authorization is not the PC's
    assert calls_pc == []
    assert dict(qp.run_once())[t] == "SUCCEEDED"


def test_internal_task_interrupted_is_requeued_external_needs_review(phone):
    calls = []
    q = make_queue(phone, calls)
    ti = q.queue("reindex", {}, actor=HUMAN, external_effect=False)
    te = q.queue("send_message", {}, actor=HUMAN, external_effect=True)
    q.authorize(te, actor=HUMAN)
    with phone.tx() as conn:   # simulate a crash while both were RUNNING with expired leases
        q._set_state(conn, ti, "RUNNING", lease=1, bump=True)
        q._set_state(conn, te, "RUNNING", lease=1, bump=True)
    changed = dict(q.recover(now=10))
    assert changed == {ti: "PENDING", te: "NEEDS_REVIEW"}
    out = dict(q.run_once())
    assert out == {ti: "SUCCEEDED"}       # the external one is never retried automatically
    assert calls == [("reindex", {})]


CHILD = textwrap.dedent("""
    import sys
    sys.path.insert(0, {root!r})
    from omega.store import Node
    n = Node.open({home!r})
    for i in range(3):
        n.append("NOTE_RECORDED", {{"text": f"before crash {{i}}"}}, actor="human:operator")
    n.append("NOTE_RECORDED", {{"text": "this one dies mid-transaction"}}, actor="human:operator")
""")


def test_recovery_after_process_killed_mid_transaction(phone):
    home = str(phone.path)
    before = phone.vector().get(phone.device_id, 0)
    phone.close()
    env = dict(os.environ, OMEGA_FAULT="append:after_insert")
    # fault fires on the first append -> nothing from the child commits
    r = subprocess.run([sys.executable, "-c", CHILD.format(root=str(ROOT), home=home)], env=env)
    assert r.returncode == 91
    n = Node.open(home)
    assert n.vector().get(n.device_id, 0) == before
    assert n.verify_integrity()["ok"]
    # normal run afterwards continues the chain with no gap
    env.pop("OMEGA_FAULT")
    r = subprocess.run([sys.executable, "-c", CHILD.format(root=str(ROOT), home=home)], env=env)
    assert r.returncode == 0
    n.close()
    n = Node.open(home)
    assert n.vector()[n.device_id] == before + 4
    integ = n.verify_integrity()
    assert integ["ok"], integ["problems"]
    n.close()


IMPORT_CHILD = textwrap.dedent("""
    import sys, json
    sys.path.insert(0, {root!r})
    from omega.store import Node
    n = Node.open({home!r})
    for env in json.load(open({envs!r})):
        n.import_event(env, "peer")
""")


def test_recovery_after_kill_during_import(paired, tmp_path):
    phone, pc = paired
    for i in range(4):
        phone.append("NOTE_RECORDED", {"text": f"n{i}"}, actor=HUMAN)
    import json
    envs = phone.events_for_peer(pc.vector(), "PRIVATE")
    (tmp_path / "envs.json").write_text(json.dumps(envs))
    home = str(pc.path)
    pc.close()
    env = dict(os.environ, OMEGA_FAULT="import:after_insert")
    r = subprocess.run([sys.executable, "-c", IMPORT_CHILD.format(root=str(ROOT), home=home, envs=str(tmp_path / "envs.json"))],
                       env=env)
    assert r.returncode == 91
    pc2 = Node.open(home)
    assert phone.device_id not in pc2.vector() or pc2.vector()[phone.device_id] <= 1
    assert pc2.verify_integrity()["ok"]
    ri, rr = run_pipe_sync(phone, pc2)
    assert ri.complete and pc2.vector() == phone.vector()
    pc2.close()


def test_restore_from_backup_then_resync_recovers_own_events(paired, tmp_path):
    """RECOVERY_AND_ROLLBACK.md: a node restored from an older backup gets its
    own later events back from the peer (they are signed, so they verify)."""
    import shutil
    phone, pc = paired
    phone.append("NOTE_RECORDED", {"text": "before backup"}, actor=HUMAN)
    phone.backup(tmp_path / "phone-backup.db")
    late = phone.append("NOTE_RECORDED", {"text": "after backup, synced"}, actor=HUMAN)
    run_pipe_sync(phone, pc)
    home, want = phone.path, phone.vector()
    phone.close()
    for suffix in ("", "-wal", "-shm"):
        p = home / f"node.db{suffix}"
        if p.exists():
            p.unlink()
    shutil.copy(tmp_path / "phone-backup.db", home / "node.db")
    restored = Node.open(home)
    assert restored.get(late.event_id) is None
    assert restored.verify_integrity()["ok"]
    ri, rr = run_pipe_sync(restored, pc)
    assert ri.complete and restored.vector() == want
    assert restored.get(late.event_id).payload == {"text": "after backup, synced"}
    assert restored.verify_integrity()["ok"]
    restored.close()
