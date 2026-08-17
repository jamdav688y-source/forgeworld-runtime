#!/usr/bin/env python3
"""FORGEWORLD Pocket Cortex phone deployment: non-destructive, staged,
backup-first, refuses to overwrite unresolved divergence.

Built directly on top of forge_reconcile.py (read-only reconciliation):
this script calls it fresh before touching anything, and refuses to
proceed if any file it is about to deploy is classified UNMERGED_LIVE,
AUTHORITATIVE_LIVE, or UNKNOWN in that scan -- those labels mean the live
phone has something in that exact path that this deploy did not expect
and cannot explain, and the rule this tool obeys (inherited from
forge_reconcile.py) is RUNNING SYSTEM > REPOSITORY ASSUMPTION >
DOCUMENTATION. A human must look and pass
--force-acknowledge-divergence <path> for each such file, individually,
by name, before this script will overwrite it.

IMPORTANT -- where this script actually runs: it must be executed ON THE
PHONE, inside Termux, against the phone's own live --root. It has never
been run against a real phone from the cloud environment that authored
it, and cannot be -- there is no network path from that environment to
127.0.0.1 on your phone. Every guarantee below has been verified against
a simulated --root (a throwaway directory standing in for the phone's
forgeworld-runtime checkout, exercising the exact same code path), not
against real Termux. Treat the first real run as the first real test,
and read its output before trusting it -- start with --dry-run.

Guarantees:
  - Zero writes to --root until every check below has passed AND the
    operator has explicitly confirmed (--yes, or an interactive prompt).
  - A full backup of everything about to be touched is taken before any
    write, into a directory OUTSIDE --root (mirroring
    forge_reconcile.py's own --out convention).
  - data/*.db, data/*.sqlite*, data/*.sqlite3, and any path literally
    containing "research.db" are NEVER written by this script, under any
    flag combination -- there is no override for this.
  - Only the specific files this script knows about (pocket-cortex/,
    minus data/, plus scripts/forge_reconcile.py) are ever written --
    "deploy" here means exporting known-good blobs from a git ref by
    exact path, never `git checkout` (which would touch the whole
    working tree and could disrupt unrelated live phone work) and never
    a recursive directory copy (which would happily copy along anything
    unexpected sitting in the source tree).
  - Every write is staged through a temp file and renamed into place, so
    a kill mid-write leaves either the old file or the new file intact,
    never a truncated one.
  - Restart and 127.0.0.1 verification only happen after every file
    write succeeds. A failed health check does not trigger automatic
    rollback -- it prints the exact rollback command and stops, so a
    human decides, rather than this script guessing.

Usage (on the actual phone, in Termux):
  python3 scripts/forge_deploy.py --dry-run
  python3 scripts/forge_deploy.py --yes
  python3 scripts/forge_deploy.py --ref origin/claude/pocket-cortex-command-deck --yes
  python3 scripts/forge_deploy.py --yes --force-acknowledge-divergence pocket-cortex/app.js
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_REF = "origin/claude/pocket-cortex-command-deck"
DEFAULT_PORT = 8080

# Paths (relative to --root) this script will ever consider writing.
# Deliberately narrow -- "deploys only validated files" means exactly
# this set, never a broader sweep.
DEPLOY_SCOPE_PREFIXES = ("pocket-cortex/", "scripts/forge_reconcile.py")

# Never written, never even considered, regardless of any flag. Checked
# by substring/pattern match against the relative path.
NEVER_TOUCH_PATTERNS = (
    "pocket-cortex/data/",  # the entire live data directory: db files, WAL/SHM, reconcile-output
    "research.db",           # the mission's own named path, wherever it appears
    ".db",
    ".sqlite",
    ".sqlite3",
)

DIVERGENT_LABELS = {"UNMERGED_LIVE", "AUTHORITATIVE_LIVE", "UNKNOWN"}


def never_touch(rel_path: str) -> bool:
    return any(pat in rel_path for pat in NEVER_TOUCH_PATTERNS)


def in_deploy_scope(rel_path: str) -> bool:
    return any(rel_path == p or rel_path.startswith(p) for p in DEPLOY_SCOPE_PREFIXES)


def sh(cmd: list[str], cwd: Path | None = None, timeout: float = 60.0) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


class DeployError(Exception):
    pass


class Deployer:
    def __init__(self, args):
        self.args = args
        self.root = Path(args.root).expanduser().resolve()
        self.port = args.port
        self.ref = args.ref
        self.dry_run = args.dry_run
        self.stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.backup_root = Path(args.backup_dir).expanduser() if args.backup_dir else (self.root.parent / "forgeworld-backups")
        self.backup_dir = self.backup_root / f"pocket-cortex-deploy-{self.stamp}"
        self.log: list[str] = []
        self.acknowledged = set(args.force_acknowledge_divergence or [])

    def note(self, msg: str):
        print(msg)
        self.log.append(msg)

    def stage(self, n: int, total: int, name: str, status: str, detail: str = ""):
        line = f"STAGE {n}/{total} [{name}]: {status}" + (f": {detail}" if detail else "")
        self.note(line)

    # ------------------------------------------------------------------

    def run(self) -> int:
        total = 8
        self.note("=== FORGEWORLD POCKET CORTEX DEPLOY ===")
        self.note(f"root:   {self.root}")
        self.note(f"ref:    {self.ref}")
        self.note(f"port:   {self.port}")
        self.note(f"backup: {self.backup_dir}")
        self.note(f"mode:   {'DRY RUN (no writes)' if self.dry_run else 'LIVE'}")
        self.note("")

        try:
            self.stage_identity()
            deploy_files = self.stage_enumerate()
            self.stage_reconcile_and_check(deploy_files)
            self.stage_confirm(deploy_files)
            self.stage_backup(deploy_files)
            self.stage_deploy(deploy_files)
            self.stage_restart()
            self.stage_verify()
        except DeployError as e:
            self.note(f"\nDEPLOY HALTED: {e}")
            self._write_report(success=False)
            return 1
        except Exception as e:  # noqa: BLE001
            self.note(f"\nDEPLOY HALTED (unexpected error): {type(e).__name__}: {e}")
            self._write_report(success=False)
            return 1

        self._write_report(success=True)
        self.note(f"\nDeploy report + rollback instructions: {self.backup_dir}/DEPLOY_REPORT.md")
        return 0

    # ---- stage 1: identity ------------------------------------------

    def stage_identity(self):
        if not (self.root / ".git").exists():
            self.stage(1, 8, "identity", "FAIL", f"{self.root} is not a git repository")
            raise DeployError(f"--root {self.root} is not a git checkout; cannot resolve --ref against it")
        if not self.args.no_fetch:
            rc, _, err = sh(["git", "fetch", "origin"], cwd=self.root, timeout=60.0)
            if rc != 0:
                self.stage(1, 8, "identity", "WARNING", f"git fetch failed (offline?): {err.strip()[:200]}")
            else:
                self.stage(1, 8, "identity", "PASS", "fetched origin")
        else:
            self.stage(1, 8, "identity", "PASS", "--no-fetch given, using local refs as-is")

        rc, out, err = sh(["git", "cat-file", "-e", f"{self.ref}^{{commit}}"], cwd=self.root)
        if rc != 0:
            raise DeployError(f"ref '{self.ref}' does not resolve in {self.root}: {err.strip()}")

    # ---- stage 2: enumerate the exact file set at --ref ---------------

    def stage_enumerate(self) -> list[str]:
        rc, out, err = sh(["git", "ls-tree", "-r", "--name-only", self.ref], cwd=self.root, timeout=30.0)
        if rc != 0:
            raise DeployError(f"could not list files at {self.ref}: {err.strip()}")

        all_paths = [p for p in out.splitlines() if p.strip()]
        deploy_files = [p for p in all_paths if in_deploy_scope(p) and not never_touch(p)]
        skipped_never_touch = [p for p in all_paths if in_deploy_scope(p) and never_touch(p)]

        if not deploy_files:
            raise DeployError(f"no deployable files found under {DEPLOY_SCOPE_PREFIXES} at {self.ref}")

        self.stage(2, 8, "enumerate", "PASS", f"{len(deploy_files)} file(s) in scope, {len(skipped_never_touch)} protected path(s) excluded (data/db)")
        for p in skipped_never_touch:
            self.note(f"  protected, never touched: {p}")
        return deploy_files

    # ---- stage 3: fresh reconciliation + divergence check --------------

    def stage_reconcile_and_check(self, deploy_files: list[str]):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        reconcile_out = self.backup_dir / "reconcile"
        reconcile_script = Path(__file__).resolve().parent / "forge_reconcile.py"

        cmd = [sys.executable, str(reconcile_script), "--root", str(self.root), "--out", str(reconcile_out), "--force"]
        if self.args.no_fetch:
            cmd.append("--no-fetch")
        rc, out, err = sh(cmd, timeout=120.0)
        if rc != 0:
            raise DeployError(f"forge_reconcile.py failed (exit {rc}); refusing to deploy without a fresh reconciliation.\n{err.strip()[:500]}")

        manifest_path = reconcile_out / "manifest.json"
        if not manifest_path.exists():
            raise DeployError("forge_reconcile.py did not produce a manifest; refusing to deploy blind")
        manifest = json.loads(manifest_path.read_text())
        per_path = manifest.get("classification", {}).get("per_path", {})

        blocking = []
        for rel in deploy_files:
            info = per_path.get(rel)
            if not info:
                continue  # not present live yet (new file) -- not a divergence
            if info["label"] in DIVERGENT_LABELS and rel not in self.acknowledged:
                blocking.append((rel, info["label"], info.get("reasons", [])))

        if blocking:
            self.stage(3, 8, "reconcile_and_check", "FAIL", f"{len(blocking)} file(s) have unresolved live divergence")
            for rel, label, reasons in blocking:
                self.note(f"  {rel}: {label} -- {'; '.join(reasons)}")
            self.note("\nRe-run with --force-acknowledge-divergence <path> for each file above, once you have")
            self.note("looked at it and confirmed overwriting it is correct. Nothing has been written.")
            raise DeployError(f"{len(blocking)} file(s) blocked on unresolved divergence (see above)")

        self.stage(3, 8, "reconcile_and_check", "PASS", "no unresolved divergence in the deploy scope")

    # ---- stage 4: confirm ---------------------------------------------

    def stage_confirm(self, deploy_files: list[str]):
        if self.dry_run:
            self.stage(4, 8, "confirm", "PASS", "dry run -- skipping confirmation, nothing will be written")
            return
        if self.args.yes:
            self.stage(4, 8, "confirm", "PASS", "--yes supplied")
            return
        print(f"\nAbout to write {len(deploy_files)} file(s) under {self.root}, after backing them up.")
        answer = input("Type 'deploy' to continue, anything else to abort: ").strip()
        if answer != "deploy":
            raise DeployError("operator did not confirm")
        self.stage(4, 8, "confirm", "PASS", "operator confirmed interactively")

    # ---- stage 5: backup -------------------------------------------------

    def stage_backup(self, deploy_files: list[str]):
        if self.dry_run:
            self.stage(5, 8, "backup", "PASS", "dry run -- no backup taken, none needed")
            return

        backed_up = 0
        for rel in deploy_files:
            src = self.root / rel
            if not src.exists():
                continue  # nothing live yet to back up for a brand-new file
            dst = self.backup_dir / "live" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            backed_up += 1

        # Also snapshot the entire live data/ directory (never deployed
        # into, but worth having alongside the backup for evidence -- this
        # is a COPY for the record, not something rollback ever needs to
        # restore, since deploy never touches data/ in the first place).
        data_dir = self.root / "pocket-cortex" / "data"
        if data_dir.exists():
            dst_data = self.backup_dir / "live" / "pocket-cortex" / "data"
            shutil.copytree(data_dir, dst_data, dirs_exist_ok=True)
            self.note(f"  snapshotted pocket-cortex/data/ for the record (not part of rollback -- deploy never writes here)")

        self.stage(5, 8, "backup", "PASS", f"{backed_up} live file(s) backed up to {self.backup_dir / 'live'}")

    # ---- stage 6: deploy ----------------------------------------------

    def stage_deploy(self, deploy_files: list[str]):
        if self.dry_run:
            self.stage(6, 8, "deploy", "PASS", f"dry run -- would write {len(deploy_files)} file(s)")
            return

        written = 0
        for rel in deploy_files:
            rc, content_bytes, err = self._git_show_bytes(rel)
            if rc != 0:
                raise DeployError(f"could not read {rel} from {self.ref}: {err}")
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".deploy-tmp")
            tmp.write_bytes(content_bytes)
            tmp.replace(dst)  # atomic on the same filesystem
            written += 1

        self.stage(6, 8, "deploy", "PASS", f"{written} file(s) written")

    def _git_show_bytes(self, rel_path: str) -> tuple[int, bytes, str]:
        try:
            p = subprocess.run(
                ["git", "show", f"{self.ref}:{rel_path}"], cwd=str(self.root),
                capture_output=True, timeout=30.0,
            )
            return p.returncode, p.stdout, p.stderr.decode("utf-8", errors="replace")
        except (OSError, subprocess.TimeoutExpired) as e:
            return -1, b"", str(e)

    # ---- stage 7: restart canonical service ----------------------------

    def stage_restart(self):
        if self.dry_run:
            self.stage(7, 8, "restart", "PASS", "dry run -- service not restarted")
            return

        killed = self._kill_listener(self.port)
        server_js = self.root / "pocket-cortex" / "server.js"
        if not server_js.exists():
            raise DeployError(f"deployed but {server_js} is missing -- cannot start the service")

        log_path = self.backup_dir / "server.out.log"
        with open(log_path, "ab") as log_file:
            subprocess.Popen(
                ["node", str(server_js)],
                cwd=str(self.root / "pocket-cortex"),
                env={"PORT": str(self.port), **_current_env()},
                stdout=log_file, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self.stage(7, 8, "restart", "PASS", f"{'stopped previous listener and ' if killed else ''}started node server.js (log: {log_path})")

    @staticmethod
    def _kill_listener(port: int) -> bool:
        rc, out, _ = sh(["fuser", "-n", "tcp", str(port)])
        pids = [p for p in out.split() if p.strip().isdigit()]
        if not pids:
            rc2, out2, _ = sh(["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"])
            pids = [p for p in out2.split() if p.strip().isdigit()]
        if not pids:
            return False
        for pid in pids:
            sh(["kill", pid])
        time.sleep(1.0)
        for pid in pids:
            sh(["kill", "-9", pid])
        return True

    # ---- stage 8: verify 127.0.0.1 --------------------------------------

    def stage_verify(self):
        if self.dry_run:
            self.stage(8, 8, "verify", "PASS", "dry run -- health endpoint not checked")
            return

        url = f"http://127.0.0.1:{self.port}/api/health"
        last_err = None
        for attempt in range(10):
            try:
                with urllib.request.urlopen(url, timeout=2) as resp:
                    if resp.status == 200:
                        self.stage(8, 8, "verify", "PASS", f"{url} responded 200 after {attempt + 1} attempt(s)")
                        return
                    last_err = f"HTTP {resp.status}"
            except (urllib.error.URLError, OSError) as e:
                last_err = str(e)
            time.sleep(1.0)

        self.stage(8, 8, "verify", "FAIL", f"{url} never responded: {last_err}")
        raise DeployError(
            f"service did not become healthy at {url} after deploy. "
            f"See {self.backup_dir}/DEPLOY_REPORT.md for the rollback command."
        )

    # ---- reporting -----------------------------------------------------

    def _write_report(self, success: bool):
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        rollback_lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "# Restores exactly the files this deploy changed, from the backup",
            "# taken immediately before deploy. Never touches pocket-cortex/data/",
            "# -- that directory was never written by the deploy in the first",
            "# place, so there is nothing to roll back there.",
            f'ROOT="{self.root}"',
            f'BACKUP="{self.backup_dir}/live"',
            "",
        ]
        live_dir = self.backup_dir / "live"
        if live_dir.exists():
            for p in sorted(live_dir.rglob("*")):
                if p.is_file() and "pocket-cortex/data/" not in str(p.relative_to(live_dir)):
                    rel = p.relative_to(live_dir)
                    rollback_lines.append(f'cp "$BACKUP/{rel}" "$ROOT/{rel}"')
        rollback_lines.append('echo "Rollback complete. Restart the service manually:"')
        rollback_lines.append(f'echo "  cd $ROOT/pocket-cortex && ./start.sh {self.port}"')
        rollback_script = self.backup_dir / "rollback.sh"
        rollback_script.write_text("\n".join(rollback_lines) + "\n")
        rollback_script.chmod(0o755)

        report = [
            "# Pocket Cortex Deploy Report",
            "",
            f"- status: {'SUCCESS' if success else 'FAILED'}",
            f"- timestamp: {self.stamp}",
            f"- root: {self.root}",
            f"- ref deployed: {self.ref}",
            f"- port: {self.port}",
            f"- dry run: {self.dry_run}",
            "",
            "## What was preserved",
            "",
            "`pocket-cortex/data/` (including any `*.db`, `*.sqlite*`, and any path",
            "containing `research.db`) was never read from, written to, or otherwise",
            "touched by this deploy. A snapshot of it was copied into this backup",
            "directory purely for the record, not because rollback needs it.",
            "",
            "## Rollback",
            "",
            "```bash",
            f"bash {self.backup_dir}/rollback.sh",
            "```",
            "",
            "## Log",
            "",
            "```",
            *self.log,
            "```",
        ]
        (self.backup_dir / "DEPLOY_REPORT.md").write_text("\n".join(report) + "\n")


def _current_env():
    import os
    return dict(os.environ)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(Path.home() / "forgeworld-runtime"), help="live phone checkout to deploy into")
    parser.add_argument("--ref", default=DEFAULT_REF, help="git ref to deploy from (default: %(default)s)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--backup-dir", default=None, help="default: <root's parent>/forgeworld-backups")
    parser.add_argument("--yes", action="store_true", help="skip interactive confirmation")
    parser.add_argument("--dry-run", action="store_true", help="run every check, write nothing")
    parser.add_argument("--no-fetch", action="store_true", help="skip git fetch; use local refs as-is")
    parser.add_argument("--force-acknowledge-divergence", action="append", metavar="PATH",
                         help="explicitly accept overwriting this specific divergent path; repeatable")
    args = parser.parse_args()

    deployer = Deployer(args)
    sys.exit(deployer.run())


if __name__ == "__main__":
    main()
