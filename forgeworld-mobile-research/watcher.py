"""Bounded scanning modes.

Three modes exist:
  MANUAL SCAN     -- default, runs only when explicitly started (see indexer.scan)
  BOUNDED POLLING -- runs only while the app process is alive, disabled by default
  SCHEDULED SCAN   -- optional future Termux:API integration, disabled by default,
                      not implemented in this cycle

This module never starts a permanently running background watcher and
never requires Termux:API for core operation. Bounded polling uses
`watchdog` only to detect new files while the poller is explicitly
enabled; it still funnels through indexer.scan()'s bounded/idempotent
pipeline rather than reacting to every filesystem event directly.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from config import Settings, SourceLocation
from database import Database
from indexer import scan as run_scan


class BoundedPoller:
    """Optional, explicitly-enabled polling loop. Stops cleanly and never
    survives past `stop()` or process exit -- there is no daemon watcher
    running unless this object is running and was started on purpose."""

    def __init__(
        self,
        db: Database,
        settings: Settings,
        sources_provider,
        project_root: Path,
    ):
        self.db = db
        self.settings = settings
        self.sources_provider = sources_provider
        self.project_root = project_root
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if not self.settings.bounded_polling_enabled:
            raise RuntimeError("bounded polling is disabled in settings.json")
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def _loop(self) -> None:
        interval = max(30, int(self.settings.bounded_polling_interval_seconds))
        while not self._stop_event.is_set():
            try:
                sources: list[SourceLocation] = self.sources_provider()
                run_scan(self.db, self.settings, sources, self.project_root, batch_limit=self.settings.max_normal_batch)
            except Exception as exc:  # noqa: BLE001 - keep polling alive across transient errors
                self.db.record_event(None, "POLL_ERROR", str(exc))
            self._stop_event.wait(interval)
