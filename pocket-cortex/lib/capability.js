// Capability checks -- deliberately separate from governance.js's
// authority checks, so the distinction the whole mission is built on is
// structural in the code, not just described in a comment:
//
//   CAPABILITY ANSWERS: "can this technically happen right now?"
//   AUTHORITY ANSWERS:  "is it permitted to happen right now?"
//
// A capability that checks true and an authority that checks DENIED
// (or vice versa -- MODIFY_CAPABILITY_POLICY is always technically
// capable, since it's just editing a running process's own source, but
// never authorized through any code path) are both valid, expected
// outcomes. Neither implies the other.

import { existsSync } from "node:fs";
import { execFileSync } from "node:child_process";

function commandExists(cmd) {
  try {
    execFileSync(process.platform === "win32" ? "where" : "which", [cmd], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

/**
 * repoRoot: absolute path to the forgeworld-runtime checkout this server
 * is running from, so capability checks for RUN_RECONCILE_SCAN /
 * TRIGGER_PHONE_DEPLOY look for the actual sibling scripts rather than
 * assuming a fixed layout.
 */
export function checkCapability(name, repoRoot) {
  switch (name) {
    case "CREATE_MISSION":
    case "UPDATE_ROUTE":
    case "RECORD_EVIDENCE":
    case "RECORD_EXECUTION_ATTEMPT":
    case "EXPORT_MISSION_DATA":
    case "MODIFY_CAPABILITY_POLICY":
      // Built into this running process -- always technically reachable,
      // mirroring capabilities/registry.json's "self" check type.
      return { available: true, evidence: "capability is this running process itself" };

    case "RUN_RECONCILE_SCAN": {
      const hasPython = commandExists("python3");
      const scriptPath = repoRoot ? `${repoRoot}/scripts/forge_reconcile.py` : null;
      const hasScript = scriptPath ? existsSync(scriptPath) : false;
      return {
        available: hasPython && hasScript,
        evidence: `python3 on PATH: ${hasPython}; forge_reconcile.py present: ${hasScript}`,
      };
    }

    case "TRIGGER_PHONE_DEPLOY": {
      const hasPython = commandExists("python3");
      const scriptPath = repoRoot ? `${repoRoot}/scripts/forge_deploy.py` : null;
      const hasScript = scriptPath ? existsSync(scriptPath) : false;
      return {
        available: hasPython && hasScript,
        evidence: `python3 on PATH: ${hasPython}; forge_deploy.py present: ${hasScript}`,
      };
    }

    default:
      return { available: false, evidence: `unknown capability '${name}' -- not probed, not assumed available` };
  }
}
