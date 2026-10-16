"""TEST-ONLY runner: python tests/harness/run_guarded.py <unittest names...>.
Refuses to run unless the audit guard is already installed in this process."""
import json
import sys
import unittest

import audit_guard

if audit_guard._GUARD is None:
    sys.stderr.write("refusing to run: audit guard not installed (set FW_GUARD=1 and PYTHONPATH)\n")
    sys.exit(97)
audit_guard._GUARD.log({"runner": sys.argv[1:]})
suite = unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
print("SUMMARY " + json.dumps({"run": result.testsRun, "failures": len(result.failures),
                               "errors": len(result.errors), "skipped": len(result.skipped)}))
sys.exit(0 if result.wasSuccessful() else 1)
