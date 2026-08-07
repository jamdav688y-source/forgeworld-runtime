#!/usr/bin/env python3
"""ForgeWorld Context Integrity Gate.

Verifies that the runtime is actually looking at the codebase a repair,
diagnostics, refactoring, patch-generation, validation, or release task
assumes it is looking at -- before any of those workflows are allowed to
modify anything.

This exists because of a real incident: a repair task was handed a
traceback describing a file (validate_search.py) and an API
(init_db/insert_particle/get_db_connection) that turned out not to exist
anywhere in the repository actually being worked on. Nothing was broken;
the task and the codebase simply weren't describing the same reality.
That should be caught mechanically, in one second, before any reasoning
about "how to fix" begins.

Five phases, each producing PASS / WARNING / CONTEXT_MISMATCH / BLOCKED:

  1. Repository Identity   -- root, branch, commit, working tree, remote
  2. Workspace Integrity   -- expected files/dirs, interpreter, venv, tools
  3. API Integrity         -- do the imports in the code actually resolve,
                               read live off the repository (AST), not off
                               a hand-maintained manifest
  4. Context Consistency   -- do the specific files/imports a task claims
                               exist actually exist
  5. Repair Authorization  -- PASS/WARNING from 1-4 => proceed; anything
                               else => stop, do not fabricate a fix

Severity order (most severe wins when combining phase results):
  BLOCKED > CONTEXT_MISMATCH > WARNING > PASS

Exit code is 0 when authorized_for_repair is true, 1 otherwise, so this
can gate a shell pipeline with a plain `&&`.

Scope note (v1): local-module resolution for API Integrity only looks at
modules that live directly inside --project (flat files, or one-level
packages with __init__.py). Imports that depend on runtime sys.path
tricks (e.g. a sibling directory inserted at runtime) are treated as
external and only checked for resolvability in the current interpreter,
not statically cross-referenced -- reported as WARNING, not
CONTEXT_MISMATCH, since that limitation is in the checker, not the code.

Examples
--------
Before touching a file a task claims exists:
    forge_context_gate.py --project forgeworld-mobile-research \\
        --target-file validate_search.py \\
        --assert-import "from database import init_db, insert_particle"

General pre-flight for a whole project:
    forge_context_gate.py --project forgeworld-mobile-research \\
        --scan-whole-project --require-file database.py --require-file app.py
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SEVERITY = {"PASS": 0, "WARNING": 1, "CONTEXT_MISMATCH": 2, "BLOCKED": 3}
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".pytest_cache", ".mypy_cache"}
ASSERT_IMPORT_RE = re.compile(r"^from\s+(?P<module>[\w.]+)\s+import\s+(?P<names>.+)$")


def worse(a: str, b: str) -> str:
    return a if SEVERITY[a] >= SEVERITY[b] else b


# ---------------------------------------------------------------- git ----

def run_git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def find_repo_root(start: Path) -> Path:
    # Path.resolve() works lexically even when `start` doesn't exist, so walking
    # .parents here still finds the real repo root for a not-yet-created project path.
    p = start.resolve()
    for parent in [p, *p.parents]:
        if (parent / ".git").exists():
            return parent
    return p


# ---------------------------------------------------- python source ----

def discover_python_files(project_root: Path) -> list[Path]:
    if not project_root.is_dir():
        return []
    files = []
    for p in project_root.rglob("*.py"):
        rel_parts = p.relative_to(project_root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        files.append(p)
    return sorted(files)


def local_module_map(project_root: Path, python_files: list[Path]) -> dict[str, Path]:
    """Map importable local module name -> source file, for modules directly
    under project_root (flat files, or one-level packages via __init__.py)."""
    mapping: dict[str, Path] = {}
    for p in python_files:
        rel = p.relative_to(project_root)
        if len(rel.parts) == 1:
            mapping[rel.stem] = p
        elif len(rel.parts) == 2 and rel.parts[1] == "__init__.py":
            mapping[rel.parts[0]] = p
    return mapping


def parse_module(path: Path) -> tuple[ast.Module | None, str | None]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        return None, f"Could not read {path}: {e}"
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return None, f"SyntaxError in {path}: {e}"
    return tree, None


def module_exported_names(path: Path) -> tuple[set[str] | None, str | None]:
    """Names available to `from <this module> import X`, read live off the AST."""
    tree, err = parse_module(path)
    if tree is None:
        return None, err
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names, None


def collect_imports(path: Path) -> tuple[list[dict], str | None]:
    tree, err = parse_module(path)
    if tree is None:
        return [], err
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append({
                "kind": "from",
                "raw_module": node.module,
                "level": node.level,
                "names": [(a.name, a.asname) for a in node.names],
                "lineno": node.lineno,
            })
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append({
                    "kind": "import",
                    "raw_module": alias.name,
                    "level": 0,
                    "names": [],
                    "lineno": node.lineno,
                })
    return imports, None


def detect_cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    visited: set[str] = set()
    stack: set[str] = set()
    path: list[str] = []
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        visited.add(node)
        stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, ()):
            if neighbor not in visited:
                dfs(neighbor)
            elif neighbor in stack:
                idx = path.index(neighbor)
                cycles.append(path[idx:] + [neighbor])
        stack.discard(node)
        path.pop()

    for n in list(graph):
        if n not in visited:
            dfs(n)
    return cycles


# --------------------------------------------------------------- phases ----

def phase_repository_identity(repo_root: Path, project_root: Path) -> tuple[str, list[str], dict]:
    findings: list[str] = []
    status = "PASS"

    branch = run_git(["branch", "--show-current"], repo_root)
    commit = run_git(["rev-parse", "HEAD"], repo_root)
    remote = run_git(["remote", "get-url", "origin"], repo_root)
    porcelain = run_git(["status", "--porcelain"], repo_root)

    if commit is None:
        status = "BLOCKED"
        findings.append("Unable to read git identity: not a git repository, or git is unavailable.")

    working_tree_clean = (porcelain == "") if porcelain is not None else None
    changes = porcelain.splitlines() if porcelain else []
    if working_tree_clean is False:
        status = worse(status, "WARNING")
        findings.append(f"Working tree is dirty ({len(changes)} changed path(s)).")

    if remote is None and commit is not None:
        status = worse(status, "WARNING")
        findings.append("No 'origin' remote configured.")

    label = None
    readme = project_root / "README.md"
    if readme.is_file():
        try:
            first_line = readme.read_text(encoding="utf-8").splitlines()[0]
            label = first_line.lstrip("#").strip() or None
        except (OSError, IndexError):
            label = None

    data = {
        "root": str(repo_root),
        "branch": branch,
        "commit": commit,
        "remote_origin": remote,
        "working_tree_clean": working_tree_clean,
        "working_tree_changes": changes,
        "project_label": label,
    }
    return status, findings, data


def phase_workspace_integrity(
    project_root: Path, require_files: list[str], require_dirs: list[str], require_tools: list[str]
) -> tuple[str, list[str], dict]:
    findings: list[str] = []
    status = "PASS"

    if not project_root.is_dir():
        return "BLOCKED", [f"Project root does not exist: {project_root}"], {
            "project_root": str(project_root),
            "python_version": sys.version.split()[0],
            "virtual_env": None,
            "missing_files": require_files,
            "missing_directories": require_dirs,
            "missing_tools": [],
        }

    missing_files = [rel for rel in require_files if not (project_root / rel).is_file()]
    if missing_files:
        status = worse(status, "CONTEXT_MISMATCH")
        findings.append(f"Missing required file(s): {', '.join(missing_files)}")

    missing_dirs = [rel for rel in require_dirs if not (project_root / rel).is_dir()]
    if missing_dirs:
        status = worse(status, "CONTEXT_MISMATCH")
        findings.append(f"Missing required directory(ies): {', '.join(missing_dirs)}")

    missing_tools = [t for t in require_tools if shutil.which(t) is None]
    if missing_tools:
        status = worse(status, "BLOCKED")
        findings.append(f"Missing required tool(s) on PATH: {', '.join(missing_tools)}")

    venv = sys.prefix if sys.prefix != sys.base_prefix else os.environ.get("VIRTUAL_ENV")
    if venv is None:
        findings.append("No active Python virtual environment detected (informational only).")

    data = {
        "project_root": str(project_root),
        "python_version": sys.version.split()[0],
        "virtual_env": venv,
        "missing_files": missing_files,
        "missing_directories": missing_dirs,
        "missing_tools": missing_tools,
    }
    return status, findings, data


def phase_api_integrity(
    project_root: Path, target_files: list[str], scan_whole_project: bool, mod_map: dict[str, Path]
) -> tuple[str, list[str], dict]:
    findings: list[str] = []
    status = "PASS"
    module_reports: dict[str, dict] = {}

    full_py_files = discover_python_files(project_root)

    if target_files and not scan_whole_project:
        seed_files = [project_root / t for t in target_files if t.endswith(".py")]
        to_check: list[Path] = []
        seen: set[Path] = set()
        queue = list(seed_files)
        while queue:
            f = queue.pop()
            if f in seen:
                continue
            seen.add(f)
            if not f.exists():
                continue
            to_check.append(f)
            imports, _ = collect_imports(f)
            for imp in imports:
                top = (imp["raw_module"] or "").split(".")[0]
                if top in mod_map and mod_map[top] not in seen:
                    queue.append(mod_map[top])
        files_to_check = to_check
    else:
        files_to_check = full_py_files

    import_graph: dict[str, set[str]] = {}

    for f in files_to_check:
        rel = str(f.relative_to(project_root))
        report = {
            "file": rel,
            "compiles": False,
            "syntax_error": None,
            "unresolved_local_imports": [],
            "unresolved_external_imports": [],
        }

        try:
            py_compile.compile(str(f), doraise=True)
            report["compiles"] = True
        except py_compile.PyCompileError as e:
            report["syntax_error"] = str(e)
            status = worse(status, "CONTEXT_MISMATCH")
            findings.append(f"{rel}: fails to compile -- {e}")
            module_reports[rel] = report
            continue

        imports, err = collect_imports(f)
        if err:
            status = worse(status, "CONTEXT_MISMATCH")
            findings.append(err)
            module_reports[rel] = report
            continue

        rel_path = f.relative_to(project_root)
        mod_key = rel_path.stem if len(rel_path.parts) == 1 else None
        local_deps: set[str] = set()

        for imp in imports:
            module = imp["raw_module"]
            if imp["level"] and imp["level"] > 0:
                continue  # relative imports out of v1 scope
            if module is None:
                continue
            top = module.split(".")[0]

            if imp["kind"] == "import":
                if top in mod_map:
                    local_deps.add(top)
                elif importlib.util.find_spec(top) is None and top not in sys.stdlib_module_names:
                    report["unresolved_external_imports"].append(top)
                    status = worse(status, "WARNING")
                    findings.append(f"{rel}: import '{top}' not resolvable in this environment.")
                continue

            # kind == "from"
            if top in mod_map:
                local_deps.add(top)
                exported, exp_err = module_exported_names(mod_map[top])
                if exp_err:
                    status = worse(status, "CONTEXT_MISMATCH")
                    findings.append(exp_err)
                    continue
                for name, _asname in imp["names"]:
                    if name == "*":
                        continue
                    if name not in exported:
                        status = worse(status, "CONTEXT_MISMATCH")
                        available = ", ".join(sorted(exported)) or "none"
                        findings.append(
                            f"{rel}: 'from {module} import {name}' -- '{name}' not found in "
                            f"{mod_map[top].name} (available: {available})"
                        )
                        report["unresolved_local_imports"].append({"module": module, "name": name})
            else:
                try:
                    spec_found = importlib.util.find_spec(module) is not None
                except (ImportError, ModuleNotFoundError, ValueError):
                    spec_found = False
                if not spec_found and top not in sys.stdlib_module_names:
                    report["unresolved_external_imports"].append(module)
                    status = worse(status, "WARNING")
                    findings.append(f"{rel}: external import '{module}' not resolvable in this environment (not installed?).")

        if mod_key:
            import_graph[mod_key] = local_deps

        module_reports[rel] = report

    cycles = detect_cycles(import_graph)
    if cycles:
        status = worse(status, "WARNING")
        for c in cycles:
            findings.append(f"Circular import detected: {' -> '.join(c)}")

    data = {
        "files_checked": [str(f.relative_to(project_root)) for f in files_to_check],
        "modules": module_reports,
        "circular_imports": cycles,
    }
    return status, findings, data


def phase_context_consistency(
    project_root: Path, target_files: list[str], assert_imports: list[str], mod_map: dict[str, Path]
) -> tuple[str, list[str], dict]:
    findings: list[str] = []
    status = "PASS"

    missing_targets = [t for t in target_files if not (project_root / t).exists()]
    if missing_targets:
        status = "CONTEXT_MISMATCH"
        findings.append(f"Target file(s) do not exist in this repository: {', '.join(missing_targets)}")

    checked = 0
    for assertion in assert_imports:
        m = ASSERT_IMPORT_RE.match(assertion.strip())
        if not m:
            status = worse(status, "WARNING")
            findings.append(f"Could not parse --assert-import value: {assertion!r} (expected \"from MODULE import NAME[, NAME...]\")")
            continue
        module, names_raw = m.group("module"), m.group("names")
        names = [n.strip() for n in names_raw.split(",") if n.strip()]
        top = module.split(".")[0]

        if top not in mod_map:
            findings.append(f"Assertion '{assertion.strip()}': '{module}' is not a local module in this project; not statically verified.")
            continue

        exported, exp_err = module_exported_names(mod_map[top])
        if exp_err:
            status = "CONTEXT_MISMATCH"
            findings.append(exp_err)
            continue

        for name in names:
            checked += 1
            if name not in exported:
                status = "CONTEXT_MISMATCH"
                available = ", ".join(sorted(exported)) or "none"
                findings.append(
                    f"Assertion failed: 'from {module} import {name}' -- '{name}' is not exported by "
                    f"{mod_map[top].name} (available: {available})."
                )

    data = {
        "target_files_checked": target_files,
        "missing_target_files": missing_targets,
        "assertions_checked": checked,
    }
    return status, findings, data


def phase_repair_authorization(overall_status: str) -> tuple[bool, list[str]]:
    authorized = overall_status in ("PASS", "WARNING")
    if authorized:
        findings = ["Context verified. Repair/modification may proceed."]
    else:
        findings = [f"Context NOT verified ({overall_status}). Do not modify code. "
                    "Resolve the findings above -- do not fabricate replacement functions, "
                    "compatibility wrappers, or missing files to work around them."]
    return authorized, findings


# ----------------------------------------------------------------- cli ----

def print_summary(report: dict) -> None:
    bar = "=" * 64
    print(bar)
    print("FORGEWORLD CONTEXT INTEGRITY GATE")
    print(bar)
    print(f"Project:      {report['project']}")
    print(f"Repository:   {report['repository']}")
    print(f"Branch:       {report['branch']}")
    print(f"Commit:       {report['commit']}")
    wtc = report["working_tree_clean"]
    print(f"Working tree: {'clean' if wtc else 'DIRTY' if wtc is False else 'unknown'}")
    print()
    for name, phase in report["phases"].items():
        label = name.replace("_", " ").upper()
        print(f"[{phase['status']:<16}] {label}")
        for msg in phase["findings"]:
            print(f"    - {msg}")
    print()
    print("-" * 64)
    print(f"OVERALL STATUS:         {report['status']}")
    print(f"AUTHORIZED FOR REPAIR:  {'YES' if report['authorized_for_repair'] else 'NO'}")
    print(bar)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify repository/workspace/API context before any repair, diagnostics, "
                    "refactoring, patch-generation, validation, or release workflow runs.",
    )
    parser.add_argument("--project", default=".", help="Path to the project/workspace to verify (default: current directory).")
    parser.add_argument("--target-file", action="append", default=[], help="File the upcoming task is about, relative to --project. Repeatable.")
    parser.add_argument("--assert-import", action="append", default=[], dest="assert_imports",
                        help='Import the task assumes is valid, e.g. "from database import Database". Repeatable.')
    parser.add_argument("--require-file", action="append", default=[], help="Workspace file that must exist, relative to --project. Repeatable.")
    parser.add_argument("--require-dir", action="append", default=[], help="Workspace directory that must exist, relative to --project. Repeatable.")
    parser.add_argument("--require-tool", action="append", default=[], help="Executable that must be on PATH. Repeatable.")
    parser.add_argument("--scan-whole-project", action="store_true",
                        help="Run API integrity over every .py file under --project instead of just --target-file and its local import closure.")
    parser.add_argument("--json", action="store_true", help="Print the JSON report to stdout.")
    parser.add_argument("--json-out", default=None, help="Write the JSON report to this file.")
    parser.add_argument("--quiet", action="store_true", help="Suppress the human-readable summary.")
    args = parser.parse_args()

    project_root = Path(args.project).resolve()
    repo_root = find_repo_root(project_root)

    all_findings: list[dict] = []
    phases: dict[str, dict] = {}
    overall = "PASS"

    def record(name: str, status: str, findings: list[str], data: dict) -> None:
        nonlocal overall
        phases[name] = {"status": status, "findings": findings, **data}
        overall = worse(overall, status)
        for msg in findings:
            all_findings.append({"phase": name, "status": status, "message": msg})

    s, f, d = phase_repository_identity(repo_root, project_root)
    record("repository_identity", s, f, d)
    repo_data = d

    s, f, d = phase_workspace_integrity(project_root, args.require_file, args.require_dir, args.require_tool)
    record("workspace_integrity", s, f, d)

    full_py_files = discover_python_files(project_root)
    mod_map = local_module_map(project_root, full_py_files)

    s, f, d = phase_api_integrity(project_root, args.target_file, args.scan_whole_project, mod_map)
    record("api_integrity", s, f, d)

    s, f, d = phase_context_consistency(project_root, args.target_file, args.assert_imports, mod_map)
    record("context_consistency", s, f, d)

    # This phase is a summary derived from the four above -- it never introduces new
    # findings of its own, so it's deliberately excluded from the warnings/errors
    # aggregation below (status/authorized_for_repair already carry its meaning).
    authorized, auth_findings = phase_repair_authorization(overall)
    phases["repair_authorization"] = {"status": overall, "findings": auth_findings, "authorized": authorized}

    report = {
        "status": overall,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project": str(project_root),
        "repository": repo_data["root"],
        "branch": repo_data["branch"],
        "commit": repo_data["commit"],
        "remote_origin": repo_data["remote_origin"],
        "working_tree_clean": repo_data["working_tree_clean"],
        "context_verified": overall not in ("CONTEXT_MISMATCH", "BLOCKED"),
        "api_verified": phases["api_integrity"]["status"] not in ("CONTEXT_MISMATCH", "BLOCKED"),
        "workspace_verified": phases["workspace_integrity"]["status"] not in ("CONTEXT_MISMATCH", "BLOCKED"),
        "authorized_for_repair": authorized,
        "warnings": [x["message"] for x in all_findings if x["status"] == "WARNING"],
        "errors": [x["message"] for x in all_findings if x["status"] in ("CONTEXT_MISMATCH", "BLOCKED")],
        "phases": phases,
    }

    if not args.quiet:
        print_summary(report)

    if args.json:
        print(json.dumps(report, indent=2))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    sys.exit(0 if authorized else 1)


if __name__ == "__main__":
    main()
