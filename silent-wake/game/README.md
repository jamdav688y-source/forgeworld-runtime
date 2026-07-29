# The Silent Wake — game project

Godot 4.3+ project. Open `project.godot` in the Godot editor to run.

## Current state (Milestone 1 of the vertical slice roadmap)

- `scenes/title/` — title screen: New Game / Continue / Options / Quit.
  - Continue is disabled until a save file exists at `user://silent_wake_save.json` (no save system exists yet, so it will always be disabled for now).
  - Options is wired but intentionally does nothing yet.
- `scenes/placeholder/ComingSoon.tscn` — temporary landing scene for New Game/Continue, since the ship's deck (Milestone 2) doesn't exist yet. Replace this scene's role once Milestone 2 lands.

Nothing beyond the title screen has been built. See `../PROJECT_ASSESSMENT.md` for the full roadmap.

**Verification done:** Godot 4.3-stable was downloaded and run headlessly against this project — `project.godot` parses, both `.tscn` files load without script/resource/signal errors, and each scene runs to a clean quit (exit code 0). That confirms the project is structurally sound.

**Not yet verified:** actual visual appearance and button click behavior — this container has no display, so nothing has been screenshotted or interactively clicked. Open it in the Godot editor locally to confirm the title screen looks and plays as intended before building Milestone 2 on top of it.
