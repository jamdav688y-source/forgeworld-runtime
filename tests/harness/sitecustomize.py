"""TEST-ONLY. Loaded automatically by every Python process whose PYTHONPATH
includes tests/harness. When FW_GUARD=1 it installs the audit guard and, if
that fails for ANY reason, terminates the process with exit code 97 before
any test code -- or any side effect -- can run."""
import os

if os.environ.get("FW_GUARD") == "1":
    try:
        import audit_guard
        audit_guard.install("process")
    except BaseException as exc:  # noqa: BLE001 -- fail closed on anything
        try:
            os.write(2, f"FW AUDIT GUARD INSTALL FAILED: {exc!r}\n".encode())
        finally:
            os._exit(97)
