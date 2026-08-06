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
    "android_mobile_deployment": {
        "objective": (
            "Configure a new Android phone as a ForgeWorld mobile substrate: "
            "capture/index/retrieve local research, support Cinema review, "
            "and hand off mission packages to the Windows runtime -- without "
            "reproducing the full Windows ForgeWorld runtime on the phone."
        ),
        "required_capability_ids": [
            "android_filesystem_access",
            "termux_shell_execution",
            "screenshot_ingestion",
            "local_research_index",
            "cinema_review",
            "camera_capture",
            "connector_authentication",
        ],
        "delegate_to_windows_ids": [
            "desktop_shortcut_creation",
            "cinema_render_1080p_24fps",
        ],
        "notes": (
            "android_filesystem_access/termux_shell_execution resolve via the "
            "'termux' probe (TERMUX_VERSION/PREFIX env markers), which "
            "correctly reads UNAVAILABLE outside Termux -- including from "
            "this Linux container, which is neither the phone nor Windows. "
            "There is no way to fabricate a phone-side AVAILABLE reading "
            "from here; on-device negotiation must be run by the Termux "
            "process itself. camera_capture and connector_authentication "
            "are 'manual' checks (operator confirmation only, by design -- "
            "see the project's connector policy). Cross-platform mismatches "
            "(windows_shell_execution, windows_filesystem_execution) are "
            "demonstrated by the separate windows_desktop_deployment "
            "mission, not duplicated here -- this mission's job is the "
            "phone side only, per the project's own rule that the phone is "
            "not a reduced Windows workstation. NOTE on delegate_to_windows_ids: "
            "cinema_render_1080p_24fps is delegated here as a MOBILE POLICY "
            "decision (phones shouldn't attempt heavy rendering locally), "
            "not because it's a hard Windows-platform requirement -- the "
            "Cinema Player's actual 1080p/24fps master was rendered "
            "successfully on a Linux container in this same repository "
            "(see cinema/cinema_player_90s/), so registering it in "
            "capabilities/registry.json as a Windows-only 'platform' check "
            "would be factually wrong. Delegation here is real, but the "
            "reason is 'don't run this on a battery-powered phone,' not "
            "'this cannot run outside Windows.'"
        ),
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
