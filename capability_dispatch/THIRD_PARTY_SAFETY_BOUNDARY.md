# Third-Party Safety Boundary

This mission (FW-CAP-DISPATCH-004) does not install, clone, execute, or
grant authority to any third-party candidate. That is a structural claim,
not a policy statement:

```
$ grep -rn --include="*.py" --exclude-dir=__pycache__ "subprocess\|os\.system\|os\.popen\|shutil\.\|git clone\|pip install\|npm install\|urlretrieve\|urllib.request\|requests\.\|eval(\|exec(" capability_dispatch/src/
capability_dispatch/src/safety_boundary.py:6:subprocess, os.system, shutil.copytree-from-a-clone, git-clone tooling, or
```

The only match is this file's own docstring, describing what to grep for
-- not a real invocation. No function anywhere in `capability_dispatch/src/`
can install, clone, or execute anything.

## The 13 pre-installation requirements

Before any future candidate can be installed, `capability_dispatch/src/safety_boundary.py`
requires every one of these gates to be explicitly `True`:

1. `verified_canonical_identity`
2. `license_review`
3. `maintainer_and_maintenance_review`
4. `dependency_inspection`
5. `install_script_inspection`
6. `execution_surface_classification`
7. `credential_surface_classification`
8. `network_surface_classification`
9. `filesystem_and_shell_analysis`
10. `overlap_analysis`
11. `isolated_sandbox_benchmark`
12. `evidence_sufficiency_decision`
13. `explicit_installation_authority`

`installation_authorized(checklist)` returns `True` only when every gate
is present and `True` -- a missing key is treated as unsatisfied, never as
satisfied-by-omission. Star counts and community recommendations cannot
satisfy any of these gates; nothing in `capability_dispatch/src/` reads a
star count or popularity signal into a structured, comparable field at all
(see `ingest.py` -- source-packet notes about star counts stay in
`source_notes`, free text, never promoted).

This mission never constructs a checklist with any gate set to `True` for
a real candidate. `capability_dispatch/tests/test_safety_boundary.py`
asserts `installation_authorized()` returns `False` for the empty
checklist, for a checklist missing even one gate, and confirms via source
inspection that no installation-capable call exists anywhere in the
package.
