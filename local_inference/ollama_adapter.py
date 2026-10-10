"""Ollama adapter: ONE implementation of local_inference.interface's
LocalInferenceProvider Protocol. Ollama-specific code lives only here --
interface.py and run_inference() know nothing about it.

Reuses the existing capability registry rather than reimplementing a
second "is ollama on PATH" check: reachability_check() looks up the
`local_llm` entry already registered in capabilities/registry.json and
runs it through capabilities/discover.py's already-tested probe_one(),
so this adapter reports the identical UNREACHABLE/PATH_FOUND/
IDENTITY_VERIFIED/VERSION_UNSUPPORTED vocabulary discover.py already
uses everywhere else in this repository.

invoke() shells out to the local `ollama` binary via an injectable
`run_fn` (defaulting to subprocess.run) -- never a network call, never a
model download, never a long-lived service. Tests inject a fake run_fn
so this adapter's control flow (timeout / non-zero exit / success) is
fully exercised without Ollama installed and without touching a socket.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from capabilities import discover  # noqa: E402
from local_inference import interface  # noqa: E402

CAPABILITY_ID = "local_llm"


def _find_registered_check() -> Optional[dict]:
    """Look up local_llm's `check` block from the existing registry,
    rather than hardcoding a second copy of "command: ollama" here."""
    for cap in discover.load_registry():
        if cap["id"] == CAPABILITY_ID:
            return cap["check"]
    return None


class OllamaProvider:
    provider_id = "ollama"

    def __init__(self, run_fn: Callable[..., subprocess.CompletedProcess] = subprocess.run):
        self._run_fn = run_fn

    def reachability_check(self) -> dict:
        check = _find_registered_check()
        if check is None:
            return {
                "reachable": False,
                "confidence": 0.0,
                "evidence": f"capability {CAPABILITY_ID!r} is not registered in capabilities/registry.json",
                "evidence_level": None,
            }
        confidence, evidence, level = discover.probe_one(check)
        return {
            "reachable": confidence > 0.0,
            "confidence": confidence,
            "evidence": evidence,
            "evidence_level": level,
        }

    def invoke(self, request: "interface.InferenceRequest") -> "interface.InferenceResult":
        started_at = interface._now()
        start_perf = time.monotonic()

        try:
            completed = self._run_fn(
                ["ollama", "run", request.model, request.prompt],
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return self._result(
                request, interface.STATUS_TIMEOUT, None,
                f"ollama did not respond within {request.timeout_seconds}s",
                started_at, start_perf,
            )
        except OSError as exc:
            return self._result(
                request, interface.STATUS_UNREACHABLE, None,
                f"'ollama' failed to launch: {exc}",
                started_at, start_perf,
            )

        if completed.returncode != 0:
            output = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
            return self._result(
                request, interface.STATUS_PROVIDER_ERROR, None,
                f"ollama exited {completed.returncode}: {output[:500]!r}",
                started_at, start_perf,
            )

        return self._result(
            request, interface.STATUS_COMPLETED, completed.stdout, None,
            started_at, start_perf,
        )

    def _result(self, request, status, output_text, error_detail, started_at, start_perf):
        return interface.InferenceResult(
            request_id=request.request_id,
            status=status,
            provider=request.provider,
            model=request.model,
            locality=request.locality,
            output_text=output_text,
            error_detail=error_detail,
            started_at=started_at,
            completed_at=interface._now(),
            duration_seconds=round(time.monotonic() - start_perf, 6),
            reachability_evidence=None,
        )
