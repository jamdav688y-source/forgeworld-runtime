"""Narrated, recordable demonstration (YouTube package, docs/omega/YOUTUBE_PACKAGE.md).

    python -m omega.showcase [--pause] [--model qwen2.5:1.5b]

Every number it prints is computed live; nothing is canned. Without Ollama,
act 4 says so and skips the model step.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import textwrap
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

PAUSE = False


def say(title, body=""):
    print("\n" + "=" * 72 + f"\n{title}\n" + "=" * 72)
    if body:
        print(textwrap.dedent(body).strip())
    if PAUSE:
        input("\n[enter] ")


def show(label, value):
    print(f"  {label:<38} {value}")


def main(argv=None):
    global PAUSE
    ap = argparse.ArgumentParser()
    ap.add_argument("--pause", action="store_true")
    ap.add_argument("--model", default="qwen2.5:1.5b")
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    a = ap.parse_args(argv)
    PAUSE = a.pause
    from omega import demo_e2e, sync
    from omega.bench import memory_bench
    from omega.relationship import RelationshipMemory

    say("ACT 1 - THE PROBLEM", """
        Assistants forget what a person already told you. Below is a conversation
        where Dana already gave her budget. A naive check, "never send the exact
        same text twice", is what most tools do.""")
    data, sha = memory_bench.load()
    base = memory_bench.score(data, memory_bench.baseline_exact(data))
    show("benchmark cases (frozen sha256)", f"{len(data['cases'])}  ({sha[:12]})")
    show("naive exact-match: repeats caught", f"{base['overall']['tp']} of {base['overall']['tp'] + base['overall']['fn']}")
    show("naive exact-match: reworded repeats", f"{base['by_kind']['paraphrase']['recall']:.0%} caught")

    say("ACT 2 - TWO DEVICES, PHONE OFFLINE", """
        The phone records the conversation with no network at all, keeps the raw
        SMS bytes, extracts the answer, and blocks a draft that re-asks it.
        Then the PC comes back, both sides authenticate, sync over TCP, and the
        PC rebuilds the same contact state.""")
    with tempfile.TemporaryDirectory() as d:
        r = demo_e2e.run(d)
        phone, pc = r.pop("_nodes")
        show("facts extracted offline", r["extracted_facts"])
        show("naive draft blocked because", r["naive_draft_blocked"])
        show("sync complete / PC integrity", f"{r['sync_complete']} / {r['pc_integrity']}")
        show("fact -> message -> raw SMS bytes", r["pc_provenance_chain"]["raw_artifact_matches"])
        show("same context digest on both", r["same_context"])

        say("ACT 3 - FAILURE CASES THE SYSTEM MUST REFUSE")
        show("agent authorizes without passphrase", r["forged_authorization"])
        show("wrong operator passphrase", r["wrong_passphrase"])
        show("task state after both attempts", r["after_forgery_attempts"])
        b = Path(d) / "x.fwbundle"
        sync.export_bundle(phone, pc.device_id, b)
        sync.import_bundle(pc, b)
        try:
            sync.import_bundle(pc, b)
            show("replayed offline bundle", "ACCEPTED (defect!)")
        except sync.SyncError as exc:
            show("replayed offline bundle", exc.code)
        rm = RelationshipMemory(pc)
        cid = rm.contacts()[0]
        para = "Hi Dana, how much were you planning to spend on this?"
        miss = [f["code"] for f in rm.check_draft(cid, para)]
        show("rules on an unseen paraphrase", miss or "nothing flagged  <- known weakness")

        say("ACT 4 - CORRECTION: A LOCAL MODEL AS AN ADVISOR, MEASURED")
        from omega.forge import OllamaClient
        client = OllamaClient(a.ollama, timeout=300)
        if client.available() and a.model in client.models():
            f = rm.check_draft(cid, para, semantic_checker=client.repeat_checker(a.model, "Dana"))
            show(f"rules + {a.model}", [(x["code"], x["severity"]) for x in f if x["code"] != "OPEN_OBLIGATION"])
            print("\n  Full benchmark (same 50 frozen cases), measured on this machine:")
            with tempfile.TemporaryDirectory() as d2:
                out = Path(d2) / "mb.json"
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()):
                    memory_bench.main(["--out", str(out), "--model", a.model, "--ollama", a.ollama])
                res = json.loads(out.read_text())
            for name in ("baseline_exact", "omega_rules", f"llm:{a.model}", f"rules_or_llm:{a.model}"):
                v = res["systems"][name]
                show(name, f"F1 {v['overall']['f1']:.2f}  paraphrase recall {v['by_kind']['paraphrase']['recall']:.2f}  "
                           f"false alarms {v['overall']['fp']}  median {v['latency_ms']['median']} ms")
            print("\n  Policy: rules BLOCK (few false alarms); the model only WARNS (more recall, more false alarms).")
        else:
            show("local model", f"not available at {a.ollama} ({a.model}); step skipped, rules still work")

        say("ACT 5 - VERIFIED OUTCOME")
        show("authorized reply sent", "")
        print(textwrap.indent(r["sent_reply"], "      | "))
        show("vectors equal / state digests equal", f"{r['vectors_equal']} / {r['state_digests_equal']}")
        show("both nodes verify every signature", r["final_integrity"])
        phone.close()
        pc.close()
    say("END", "Reproduce: python -m omega.proof run --device \"<your machine>\" --out proof.json")


if __name__ == "__main__":
    main()
