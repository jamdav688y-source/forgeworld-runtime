"""Mission requirement registry: declares what each mission needs before
the Capability Negotiation Engine will say it's safe to proceed.

A requirement is a specific capability id from capabilities/registry.json
-- not a vague tag -- so gap detection can point at exactly what's
missing instead of a generic "some capability in this category."
"""

MISSIONS = {
    "windows_desktop_deployment": {
        "objective": (
            "Deploy, install, and validate the Cinema Player on an actual "
            "Windows desktop machine, including a working double-clickable "
            "desktop shortcut."
        ),
        "required_capability_ids": [
            "windows_filesystem_execution",
            "windows_shell_execution",
            "remote_desktop_access",
        ],
        "notes": (
            "This is the mission that motivated building this engine: it was "
            "previously reported as blocked via ad-hoc reasoning (manually "
            "calling ListConnectors and explaining the gap in prose). This "
            "registry entry makes that requirement declarative and "
            "re-checkable instead of something that has to be re-derived "
            "by hand every time the mission comes up again."
        ),
    },
    "cinema_release_commit": {
        "objective": (
            "Build, test, and push a Cinema Player release to the "
            "forgeworld-runtime repository from this runtime."
        ),
        "required_capability_ids": ["git", "python", "github", "desktop_runtime"],
        "notes": "All four are expected to be satisfiable inside this container -- used as the negotiation engine's positive-path acceptance test.",
    },
    "capability_negotiation_selftest": {
        "objective": "Dedicated fixture mission for testing check_resume() -- not a real deployment mission.",
        "required_capability_ids": ["chatgpt"],
        "notes": (
            "chatgpt's check is `env: OPENAI_API_KEY`, which this container "
            "can genuinely set/unset, making it the one capability in this "
            "registry whose reachability can be flipped for real inside a "
            "test rather than only simulated."
        ),
    },
    "third_party_notification_workflow": {
        "objective": (
            "Notify an operator via a connected service (e.g. Slack or "
            "Gmail) when a long-running render or validation completes."
        ),
        "required_capability_ids": ["slack", "gmail"],
        "notes": (
            "Both resolve via live connector evidence when supplied by the "
            "calling agent, and fall back to UNKNOWN (not a false AVAILABLE "
            "or a false UNAVAILABLE) when run standalone without that "
            "evidence."
        ),
    },
}


def get_mission(mission_id: str) -> dict:
    if mission_id not in MISSIONS:
        raise KeyError(f"unknown mission '{mission_id}', known missions: {sorted(MISSIONS)}")
    return MISSIONS[mission_id]
