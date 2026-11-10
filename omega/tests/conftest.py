import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from omega.identity import parse_offer, short_auth_string  # noqa: E402
from omega.store import Node  # noqa: E402

HUMAN = "human:operator"


def fixed_clock(start=1793534400):  # 2026-11-01T00:00:00Z
    counter = itertools.count()

    def clock():
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start + next(counter)))
    return clock


def make_node(path, label, profile="pocket", **kw):
    n = Node.init(path, label, profile, **kw)
    n.clock = fixed_clock()
    return n


def pair(a, b, max_privacy="PRIVATE"):
    oa, ob = parse_offer(a.identity.pairing_offer(a.info["label"])), parse_offer(b.identity.pairing_offer(b.info["label"]))
    sas = short_auth_string(oa, ob)
    a.add_peer(ob, oa, sas, actor=HUMAN, max_privacy=max_privacy)
    b.add_peer(oa, ob, sas, actor=HUMAN, max_privacy=max_privacy)


@pytest.fixture
def phone(tmp_path):
    n = make_node(tmp_path / "phone", "pocket-phone", "pocket")
    yield n
    n.close()


@pytest.fixture
def pc(tmp_path):
    n = make_node(tmp_path / "pc", "forge-pc", "forge")
    yield n
    n.close()


@pytest.fixture
def paired(phone, pc):
    pair(phone, pc)
    return phone, pc


def run_pipe_sync(initiator, responder, fault_after=None, fault_side="initiator"):
    import threading
    from omega import sync
    ca, cb = sync.PipeChannel.pair()
    ca.timeout = cb.timeout = 5
    if fault_after is not None:
        if fault_side == "initiator":
            ca = sync.FaultyChannel(ca, fault_after)
        else:
            cb = sync.FaultyChannel(cb, fault_after)
    out = {}

    def resp():
        try:
            out["r"] = sync.sync_over(responder, cb, "responder")
        except Exception as exc:  # handshake-level failures
            out["r"] = exc
    t = threading.Thread(target=resp)
    t.start()
    try:
        ri = sync.sync_over(initiator, ca, "initiator")
    except Exception as exc:
        ri = exc
        ca.close()
    t.join(15)
    return ri, out.get("r")
