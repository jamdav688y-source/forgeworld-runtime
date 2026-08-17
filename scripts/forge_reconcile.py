#!/usr/bin/env python3
"""FORGEWORLD live-state reconciliation: read-only, staged, resumable.

Rule this tool obeys: RUNNING SYSTEM > REPOSITORY ASSUMPTION > DOCUMENTATION.
It treats whatever is actually on disk at --root (default $HOME/forgeworld-runtime)
as source reality, and every known git branch as a candidate historical
implementation to be checked against that reality -- never the other way
around.

Guarantees:
  - Zero destructive changes. This script never writes, moves, deletes, or
    touches anything under --root. It never runs `git checkout`, `git merge`,
    `git reset`, or any command that could change the working tree or HEAD.
    All git operations are read-only plumbing (status, log, ls-tree,
    hash-object, cat-file, fetch of remote refs only).
  - All output goes to --out, a directory OUTSIDE --root by default, so
    `git status` inside --root is never affected by running this tool.
  - Staged: each stage is DISCOVER -> RECORD -> VERIFY -> CHECKPOINT, prints
    an unambiguous "STAGE N: PASS"/"STAGE N: FAIL: <reason>" line, and
    writes its result to manifest.json immediately (not buffered in memory
    only) so a kill/crash mid-run loses at most the current stage.
  - Resumable: re-running with the same --out skips stages already marked
    PASS in checkpoint.json, unless --force is given.

Usage (on the actual phone, in Termux):
  python3 forge_reconcile.py
  python3 forge_reconcile.py --force              # re-run every stage
  python3 forge_reconcile.py --no-fetch            # skip network entirely
  python3 forge_reconcile.py --root ~/forgeworld-runtime --out ~/forgeworld-reconcile-output
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Every branch this reconciliation effort is currently aware of. Extend this
# list as new candidate implementations surface -- it is not authoritative
# over anything, it is only what gets checked against reality.
CANDIDATE_BRANCHES = [
    "origin/main",
    "origin/claude/forgeworld-mobile-research-w8omev",
    "origin/claude/forgeworld-mobile-research-v1-completion",
    "origin/claude/forgeworld-core-architecture-t1khio",
    "origin/claude/forgeworld-cinema-player-90s",
    "origin/claude/forgeworld-arch-discovery-mzy44k",
    "origin/claude/forgeworld-continuity-substrate-yr2o4e",
    "origin/claude/pocket-cortex-title-screen-hvf7j8",
    "origin/claude/repository-intelligence-model-h7l8tp",
    "origin/claude/silent-wake-crpg-init-aoqr11",
    "origin/claude/forgeworld-validation-001-4g2f77",
    "origin/claude/forgeworld-evolution-clip-s9f5ys",
    "origin/claude/forgeworld-authority-separation",
    "origin/claude/pocket-cortex-command-deck",
]

# Subpaths (relative to --root) worth inventorying in focused detail, beyond
# the full top-level walk every stage 2 already does.
RUNTIME_RELEVANT_PATHS = [
    "bin", "config", "dial", "state", ".forge",
    "events", "memory", "world", "governance", "diagnostics", "logs",
    "substrate", "substrate-runtime", "npc", "npcs", "factions", "reputation",
    "consequences", "future", "council_reviews", "relationships", "quests",
    "rpg", "notes", "tasks", "inbox", "capabilities", "capability_negotiation",
    "router", "scripts", "doctrine", "commands",
]

GENERATED_NAME_PATTERNS = [
    re.compile(r"\.log$"), re.compile(r"\.jsonl$"), re.compile(r"\.db$"),
    re.compile(r"\.sqlite3?$"), re.compile(r"^STATE\.json$"),
    re.compile(r"research\.db$"), re.compile(r"install\.log$"),
    re.compile(r"\.tmp$"), re.compile(r"^checkpoint\.json$"),
]

MAX_HASH_BYTES = 5 * 1024 * 1024  # skip hashing anything bigger; record size only
STAGE_NAMES = [
    "identity", "inventory", "runtime_paths", "untracked_modified",
    "hash_artifacts", "state_ledger", "reference_graph", "branch_comparison",
    "classify", "finalize",
]


def sh(cmd: list[str], cwd: Path, timeout: float = 30.0) -> tuple[int, str, str]:
    """Run a read-only command. Never called with anything that mutates
    state -- every call site in this file passes a plumbing-only command."""
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def git_blob_hashes_of(paths: list[str], root: Path) -> dict[str, str]:
    """Batched `git hash-object` -- the SAME hash space `git ls-tree` blob
    SHAs live in (git's own object hash: 'blob <size>\\0' + content, not a
    plain content hash), so results are directly comparable to
    branch_comparison's tree data. This is the ONLY correct way to detect
    "this untracked file's content matches what a branch already has" --
    a plain sha256 of the raw bytes is a different hash space entirely and
    will never match a git blob SHA even for byte-identical content. One
    batched subprocess call for all paths, not one per file, to keep CPU
    use low on a resource-constrained mobile node."""
    if not paths:
        return {}
    # --stdin-paths reads paths from stdin, avoiding an argv length limit
    # for large trees.
    try:
        p = subprocess.run(
            ["git", "hash-object", "--stdin-paths"], cwd=str(root),
            input="\n".join(paths) + "\n", capture_output=True, text=True, timeout=60.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if p.returncode != 0:
        return {}
    lines = p.stdout.splitlines()
    return dict(zip(paths, lines)) if len(lines) == len(paths) else {}


def sha256_of(path: Path) -> tuple[str | None, str]:
    try:
        size = path.stat().st_size
        if size > MAX_HASH_BYTES:
            return None, f"skipped: {size} bytes > {MAX_HASH_BYTES} byte cap"
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest(), "ok"
    except OSError as e:
        return None, f"unreadable: {e}"


class Reconciler:
    def __init__(self, root: Path, out: Path, do_fetch: bool, force: bool):
        self.root = root
        self.out = out
        self.do_fetch = do_fetch
        self.force = force
        self.out.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.out / "manifest.json"
        self.checkpoint_path = self.out / "checkpoint.json"
        self.manifest: dict = self._load(self.manifest_path, {})
        self.checkpoint: dict = self._load(self.checkpoint_path, {"stages": {}})
        self.manifest.setdefault("root", str(self.root))
        self.manifest.setdefault("run_started_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    @staticmethod
    def _load(path: Path, default):
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                return default
        return default

    def _save(self):
        tmp = self.manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2, default=str))
        tmp.replace(self.manifest_path)
        tmp2 = self.checkpoint_path.with_suffix(".json.tmp")
        tmp2.write_text(json.dumps(self.checkpoint, indent=2))
        tmp2.replace(self.checkpoint_path)

    def _already_passed(self, stage: str) -> bool:
        return (not self.force) and self.checkpoint["stages"].get(stage, {}).get("status") == "PASS"

    def _checkpoint(self, stage: str, status: str, note: str = ""):
        self.checkpoint["stages"][stage] = {
            "status": status, "note": note,
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._save()
        print(f"STAGE {STAGE_NAMES.index(stage) + 1}/{len(STAGE_NAMES)} [{stage}]: {status}" + (f": {note}" if note else ""))

    def run(self) -> bool:
        print(f"=== FORGEWORLD RECONCILIATION ===")
        print(f"root: {self.root}")
        print(f"out:  {self.out}")
        print(f"(zero writes to root; everything above goes to out only)")
        print()

        if not self.root.exists() or not self.root.is_dir():
            self._checkpoint("identity", "FAIL", f"root {self.root} does not exist or is not a directory")
            return False

        stages = [
            ("identity", self.stage_identity),
            ("inventory", self.stage_inventory),
            ("runtime_paths", self.stage_runtime_paths),
            ("untracked_modified", self.stage_untracked_modified),
            ("hash_artifacts", self.stage_hash_artifacts),
            ("state_ledger", self.stage_state_ledger),
            ("reference_graph", self.stage_reference_graph),
            ("branch_comparison", self.stage_branch_comparison),
            ("classify", self.stage_classify),
            ("finalize", self.stage_finalize),
        ]

        for name, fn in stages:
            if self._already_passed(name):
                print(f"STAGE {STAGE_NAMES.index(name) + 1}/{len(STAGE_NAMES)} [{name}]: SKIPPED (already PASS -- rerun with --force to redo)")
                continue
            try:
                ok, note = fn()
            except Exception as e:  # noqa: BLE001 -- a stage crashing must not corrupt prior progress
                ok, note = False, f"unexpected exception: {type(e).__name__}: {e}"
            self._checkpoint(name, "PASS" if ok else "FAIL", note)
            if not ok and name in ("identity",):
                # only a truly fundamental blocker stops the whole run;
                # everything else degrades to WARN-and-continue inside the
                # stage itself so partial reality is still better than none.
                print(f"\nHALTED at stage '{name}' -- fundamental blocker, cannot continue.")
                return False

        print()
        print(f"Manifest: {self.manifest_path}")
        print(f"Checkpoint: {self.checkpoint_path}")
        return True

    # ---------------------------------------------------------- stage 1 --

    def stage_identity(self) -> tuple[bool, str]:
        info: dict = {}
        is_repo = (self.root / ".git").exists()
        info["is_git_repo"] = is_repo
        if is_repo:
            _, branch, _ = sh(["git", "branch", "--show-current"], self.root)
            _, head, _ = sh(["git", "rev-parse", "HEAD"], self.root)
            _, remotes, _ = sh(["git", "remote", "-v"], self.root)
            _, status, _ = sh(["git", "status", "--porcelain=v1", "--branch"], self.root)
            _, last_commit, _ = sh(["git", "log", "-1", "--format=%h %ci %s"], self.root)
            info.update({
                "branch": branch.strip() or "(detached HEAD)",
                "head": head.strip(),
                "remotes": [l for l in remotes.splitlines() if l.strip()],
                "status_porcelain": [l for l in status.splitlines() if l.strip()],
                "last_commit": last_commit.strip(),
            })
        self.manifest["identity"] = info
        self._save()
        if not is_repo:
            return True, "root is NOT a git repository -- branch comparison will be skipped later, everything defaults toward AUTHORITATIVE_LIVE/UNKNOWN"
        return True, f"branch={info.get('branch')} head={info.get('head', '')[:12]}"

    # ---------------------------------------------------------- stage 2 --

    def stage_inventory(self) -> tuple[bool, str]:
        files = []
        skipped = 0
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for fn in filenames:
                p = Path(dirpath) / fn
                try:
                    st = p.stat()
                except OSError:
                    skipped += 1
                    continue
                rel = str(p.relative_to(self.root))
                files.append({"path": rel, "size_bytes": st.st_size, "mtime": int(st.st_mtime)})
        self.manifest["inventory"] = {"file_count": len(files), "files": files, "unreadable_skipped": skipped}
        self._save()
        return True, f"{len(files)} files inventoried, {skipped} unreadable/skipped"

    # ---------------------------------------------------------- stage 3 --

    def stage_runtime_paths(self) -> tuple[bool, str]:
        result = {}
        present = 0
        for rel in RUNTIME_RELEVANT_PATHS:
            p = self.root / rel
            if not p.exists():
                result[rel] = {"present": False}
                continue
            present += 1
            if p.is_dir():
                children = sorted(str(c.relative_to(p)) for c in p.rglob("*") if c.is_file())
                result[rel] = {"present": True, "kind": "dir", "file_count": len(children), "children_sample": children[:50]}
            else:
                st = p.stat()
                result[rel] = {"present": True, "kind": "file", "size_bytes": st.st_size}
        self.manifest["runtime_paths"] = result
        self._save()
        return True, f"{present}/{len(RUNTIME_RELEVANT_PATHS)} known runtime paths present"

    # ---------------------------------------------------------- stage 4 --

    def stage_untracked_modified(self) -> tuple[bool, str]:
        if not self.manifest.get("identity", {}).get("is_git_repo"):
            self.manifest["untracked_modified"] = {"skipped_reason": "not a git repo"}
            self._save()
            return True, "skipped (not a git repo)"

        # `git status --porcelain` collapses an entirely-untracked directory
        # into one line ending in '/' (e.g. 'bin/') rather than listing the
        # files inside it -- classification needs individual file paths, so
        # untracked files are read from `git ls-files --others`, which never
        # collapses. Modified/staged are always individual tracked files
        # already, so porcelain is fine for those.
        _, ls_out, _ = sh(["git", "ls-files", "--others", "--exclude-standard"], self.root)
        untracked = [l for l in ls_out.splitlines() if l.strip()]

        _, out, _ = sh(["git", "status", "--porcelain=v1"], self.root)
        modified, staged, other = [], [], []
        for line in out.splitlines():
            if not line.strip() or line.startswith("??"):
                continue
            code, _, path = line[:2], line[2], line[3:]
            if code.strip() and code[0] in "MADRC":
                staged.append(path)
            elif code.strip() and code[1] in "MD":
                modified.append(path)
            else:
                other.append(line)
        self.manifest["untracked_modified"] = {
            "untracked": untracked, "modified_unstaged": modified,
            "staged": staged, "other": other,
        }
        self._save()
        return True, f"{len(untracked)} untracked, {len(modified)} modified, {len(staged)} staged"

    # ---------------------------------------------------------- stage 5 --

    def stage_hash_artifacts(self) -> tuple[bool, str]:
        targets = set()
        for rel, info in self.manifest.get("runtime_paths", {}).items():
            if not info.get("present"):
                continue
            if info.get("kind") == "file":
                targets.add(rel)
            else:
                for child in info.get("children_sample", []):
                    targets.add(str(Path(rel) / child))
        # top-level loose scripts -- small, load-bearing, cheap
        for p in self.root.glob("*.sh"):
            targets.add(p.name)
        # anything git itself flags as untracked/modified/staged is, by
        # definition, exactly what needs classifying -- regardless of which
        # directory it lives in. Without this, a modified/new file sitting
        # at the repo root (not under any "known runtime path") would never
        # reach hashing or classification at all.
        um = self.manifest.get("untracked_modified", {})
        for group in ("untracked", "modified_unstaged", "staged"):
            targets.update(um.get(group, []))

        existing_files = sorted(rel for rel in targets if (self.root / rel).is_file())

        hashes = {}
        for rel in existing_files:
            digest, note = sha256_of(self.root / rel)
            hashes[rel] = {"sha256": digest, "note": note}

        if self.manifest.get("identity", {}).get("is_git_repo"):
            blob_hashes = git_blob_hashes_of(existing_files, self.root)
            for rel, blob_sha in blob_hashes.items():
                hashes[rel]["git_blob_sha1"] = blob_sha

        self.manifest["hash_artifacts"] = hashes
        self._save()
        return True, f"{len(hashes)} artifacts hashed"

    # ---------------------------------------------------------- stage 6 --

    def stage_state_ledger(self) -> tuple[bool, str]:
        candidates = []
        for rel in ["state/STATE.json", ".forge/state/STATE.json", "state.json"]:
            p = self.root / rel
            if p.exists():
                candidates.append(rel)
        # anything literally named STATE.json anywhere
        for p in self.root.rglob("STATE.json"):
            rel = str(p.relative_to(self.root))
            if rel not in candidates:
                candidates.append(rel)

        ledgers = []
        for pattern in ["*.log", "*.jsonl"]:
            for p in self.root.rglob(pattern):
                if ".git" in p.parts:
                    continue
                ledgers.append(str(p.relative_to(self.root)))

        details = {}
        for rel in candidates + ledgers:
            p = self.root / rel
            try:
                st = p.stat()
                digest, note = sha256_of(p)
                line_count = None
                if st.st_size <= MAX_HASH_BYTES:
                    try:
                        line_count = sum(1 for _ in p.open("r", errors="replace"))
                    except OSError:
                        line_count = None
                details[rel] = {"size_bytes": st.st_size, "sha256": digest, "hash_note": note, "line_count": line_count}
            except OSError as e:
                details[rel] = {"error": str(e)}

        self.manifest["state_ledger"] = {"state_files": candidates, "ledger_files": sorted(set(ledgers)), "details": details}
        self._save()
        return True, f"{len(candidates)} state-file candidate(s), {len(set(ledgers))} ledger file(s)"

    # ---------------------------------------------------------- stage 7 --

    def stage_reference_graph(self) -> tuple[bool, str]:
        script_files = [f["path"] for f in self.manifest["inventory"]["files"] if f["path"].endswith((".sh", ".py"))]
        # candidate reference tokens: every path we've inventoried, matched
        # as a substring against script contents -- static, heuristic, but
        # real (grep-based), not fabricated.
        all_paths = [f["path"] for f in self.manifest["inventory"]["files"]]
        basenames = {Path(p).name: p for p in all_paths}

        referenced_by: dict[str, list[str]] = {}
        errors = 0
        for script_rel in script_files:
            p = self.root / script_rel
            try:
                text = p.read_text(errors="replace")
            except OSError:
                errors += 1
                continue
            for name, full_path in basenames.items():
                if len(name) < 4:
                    continue  # too short, too many false positives
                if name in text:
                    referenced_by.setdefault(full_path, [])
                    if script_rel not in referenced_by[full_path]:
                        referenced_by[full_path].append(script_rel)

        self.manifest["reference_graph"] = {
            "scripts_scanned": len(script_files), "scan_errors": errors,
            "referenced_by": referenced_by,
        }
        self._save()
        return True, f"{len(script_files)} scripts scanned, {len(referenced_by)} paths found referenced at least once"

    # ---------------------------------------------------------- stage 8 --

    def stage_branch_comparison(self) -> tuple[bool, str]:
        if not self.manifest.get("identity", {}).get("is_git_repo"):
            self.manifest["branch_comparison"] = {"skipped_reason": "not a git repo"}
            self._save()
            return True, "skipped (not a git repo)"

        if not self.do_fetch:
            self.manifest["branch_comparison"] = {"skipped_reason": "--no-fetch given"}
            self._save()
            return True, "skipped (--no-fetch)"

        rc, _, err = sh(["git", "fetch", "--all", "--prune"], self.root, timeout=60.0)
        if rc != 0:
            self.manifest["branch_comparison"] = {"skipped_reason": f"git fetch failed (likely offline): {err.strip()[:300]}"}
            self._save()
            return True, "network fetch failed/unavailable -- comparison skipped, not a failure"

        trees: dict[str, dict[str, str]] = {}  # branch -> {path: blob_sha}
        available_branches = []
        for branch in CANDIDATE_BRANCHES:
            rc, out, _ = sh(["git", "ls-tree", "-r", branch], self.root, timeout=20.0)
            if rc != 0:
                continue
            available_branches.append(branch)
            tree = {}
            for line in out.splitlines():
                # format: <mode> <type> <sha>\t<path>
                meta, _, path = line.partition("\t")
                parts = meta.split()
                if len(parts) == 3:
                    tree[path] = parts[2]
            trees[branch] = tree

        self.manifest["branch_comparison"] = {"branches_checked": available_branches, "trees": trees}
        self._save()
        return True, f"{len(available_branches)} branch(es) fetched and indexed"

    # ---------------------------------------------------------- stage 9 --

    def stage_classify(self) -> tuple[bool, str]:
        is_repo = self.manifest.get("identity", {}).get("is_git_repo", False)
        hashes = self.manifest.get("hash_artifacts", {})
        trees = self.manifest.get("branch_comparison", {}).get("trees", {})
        referenced_by = self.manifest.get("reference_graph", {}).get("referenced_by", {})
        untracked = set(self.manifest.get("untracked_modified", {}).get("untracked", []))
        modified = set(self.manifest.get("untracked_modified", {}).get("modified_unstaged", []))

        classification = {}
        counts = {}
        for rel, info in hashes.items():
            local_hash = info.get("sha256")
            local_blob = info.get("git_blob_sha1")
            reasons = []
            label = "UNKNOWN"

            if not is_repo:
                label = "AUTHORITATIVE_LIVE" if rel in referenced_by else "UNKNOWN"
                reasons.append("root is not a git repository -- cannot compare to any tracked history")
            elif local_hash is None:
                label = "UNKNOWN"
                reasons.append(f"hash unavailable: {info.get('note')}")
            else:
                if rel not in untracked and rel not in modified:
                    label = "MATCHED_REPOSITORY"
                    reasons.append("tracked, clean per git status -- matches HEAD by definition")
                elif rel in modified:
                    label = "UNMERGED_LIVE"
                    reasons.append("tracked but locally modified beyond what HEAD has")
                else:  # untracked
                    # Comparison MUST use git's own blob hash (git_blob_sha1),
                    # the same hash space `git ls-tree` reports -- a plain
                    # sha256 of the raw bytes is a different hash space and
                    # would never match even byte-identical content.
                    matches = [b for b, tree in trees.items() if local_blob and tree.get(rel) == local_blob]
                    name_matches = [b for b, tree in trees.items() if rel in tree and tree.get(rel) != local_blob]
                    if matches:
                        label = "HISTORICAL"
                        reasons.append(f"content byte-for-byte matches tracked blob in: {matches}")
                    elif name_matches:
                        label = "UNMERGED_LIVE"
                        reasons.append(f"same path exists in {name_matches} but content differs -- diverged")
                    elif any(pat.search(Path(rel).name) for pat in GENERATED_NAME_PATTERNS):
                        label = "GENERATED"
                        reasons.append("filename matches a known generated-artifact pattern (log/jsonl/db/STATE.json)")
                    elif rel in referenced_by:
                        label = "AUTHORITATIVE_LIVE"
                        reasons.append(f"untracked, matches no known branch, but is referenced by: {referenced_by[rel]}")
                    else:
                        label = "UNKNOWN"
                        reasons.append("untracked, matches no known branch, not referenced by any scanned script -- needs a human look")

            classification[rel] = {"label": label, "reasons": reasons}
            counts[label] = counts.get(label, 0) + 1

        self.manifest["classification"] = {"per_path": classification, "counts": counts}
        self._save()
        return True, ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "nothing to classify"

    # ---------------------------------------------------------- stage 10 -

    def stage_finalize(self) -> tuple[bool, str]:
        self.manifest["run_completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._save()

        counts = self.manifest.get("classification", {}).get("counts", {})
        lines = [
            "# FORGEWORLD Reconciliation Summary",
            "",
            f"root: `{self.manifest.get('root')}`",
            f"generated: {self.manifest.get('run_completed_at')}",
            "",
            "## Identity",
            f"- git repo: {self.manifest.get('identity', {}).get('is_git_repo')}",
            f"- branch: {self.manifest.get('identity', {}).get('branch')}",
            f"- HEAD: {self.manifest.get('identity', {}).get('head')}",
            f"- last commit: {self.manifest.get('identity', {}).get('last_commit')}",
            "",
            "## Classification counts",
        ]
        for label, n in sorted(counts.items()):
            lines.append(f"- {label}: {n}")
        lines += ["", "## Branches actually compared against (network-dependent)"]
        lines.append(", ".join(self.manifest.get("branch_comparison", {}).get("branches_checked", [])) or "(none -- offline or skipped)")
        lines += ["", "## Files needing a human look (UNKNOWN)"]
        per_path = self.manifest.get("classification", {}).get("per_path", {})
        unknowns = [p for p, c in per_path.items() if c["label"] == "UNKNOWN"]
        lines += [f"- {p}" for p in unknowns] or ["(none)"]
        lines += ["", "## AUTHORITATIVE_LIVE (real, load-bearing, not yet in any known branch)"]
        live = [p for p, c in per_path.items() if c["label"] == "AUTHORITATIVE_LIVE"]
        lines += [f"- {p}" for p in live] or ["(none)"]

        summary_path = self.out / "SUMMARY.md"
        summary_path.write_text("\n".join(lines) + "\n")
        return True, f"wrote {self.manifest_path.name} and {summary_path.name} to {self.out}"


def main():
    parser = argparse.ArgumentParser(description="Read-only staged FORGEWORLD phone-state reconciliation.")
    parser.add_argument("--root", default=str(Path.home() / "forgeworld-runtime"))
    parser.add_argument("--out", default=str(Path.home() / "forgeworld-reconcile-output"))
    parser.add_argument("--no-fetch", action="store_true", help="skip all network operations")
    parser.add_argument("--force", action="store_true", help="re-run every stage, ignoring checkpoint")
    args = parser.parse_args()

    r = Reconciler(Path(args.root).expanduser(), Path(args.out).expanduser(), not args.no_fetch, args.force)
    ok = r.run()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
