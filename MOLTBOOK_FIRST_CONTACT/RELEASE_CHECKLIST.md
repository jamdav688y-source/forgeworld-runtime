# Release Checklist — Moltbook First Contact

**This package has not been posted anywhere.** Nothing in this checklist
authorizes posting on its own — see the final gate at the bottom.

Legend: `[x]` verified by inspection during this drafting pass · `[ ]`
not yet done · `[!]` blocked, with reason stated.

## 1. Video

- [!] **Video file located and reviewed.** `1455.mp4` was not found
  anywhere in this repository or this session's filesystem. Nothing in
  this package was written from having watched it. **Blocked on James
  (or whoever holds the file) confirming it exists, is the correct
  30-second `PROMOTION_CANDIDATE` master, and matches the "arrival
  signal" framing this package assumes.**
- [ ] Runtime confirmed ~30 seconds.
- [ ] Resolution/aspect ratio confirmed suitable for the target venue.
- [ ] No placeholder frames, watermark artifacts, or unfinished VFX.
- [ ] File is in fact the `PROMOTION_CANDIDATE` master, not an older or
      downgraded cut — **this package did not touch, move, rename, or
      overwrite `1455.mp4` in any way; it could not, since it was never
      located.**

## 2. Sound

- [!] Audio mix reviewed. Blocked for the same reason as §1 — cannot
      review audio in a file that could not be located.
- [ ] No clipping, silence gaps, or unintended abrupt cuts.
- [ ] Levels appropriate for autoplay/mobile playback if the venue
      autoplays video.

## 3. Captions

- [!] Caption/subtitle track reviewed or confirmed absent-by-design.
      Blocked — cannot confirm without the source file.
- [ ] If present: accurate, correctly timed, legible against the
      background at typical viewing size.
- [ ] If the venue supports open captions only (burned-in) vs. closed
      captions: confirmed which, and that it matches the file.

## 4. Thumbnail

- [!] Thumbnail/poster frame reviewed. Blocked — no source file to pull
      a frame from or confirm a supplied thumbnail against.
- [ ] Thumbnail does not misrepresent the film's tone (i.e. does not look
      like marketing key art for a film that isn't one).

## 5. Platform formatting

- [x] Title matches the mission-specified exact string, verified by
      direct match against `POST.md`:
      `"I made a film about arriving here. Now I need you to try to break the system behind it."`
- [x] Post body verified present in `POST.md` and includes, checked by
      direct text search against the file (not by memory or assumption):
  - [x] Honest introduction of James and ForgeWorld (present, no
        fabricated biographical claims — see `README.md`'s note on
        staying within what's actually known).
  - [x] The film described as a vessel entering a living harbor of
        intelligence (present, matches this exact framing).
  - [x] Doctrine stated verbatim: `Capability ≠ Authority ≠ Evidence ≠ Promotion`
        (confirmed present via direct string match).
  - [x] The exact required question present verbatim: "When one agent
        adopts a lesson from another, what must be preserved for that
        change to count as learning rather than imitation?" (confirmed
        present via direct string match).
  - [x] Explicit invitation for criticism, counterexamples, and protocol
        challenges (present, final two paragraphs).
- [x] Scanned for marketing language, hype phrasing, and engagement-bait
      patterns (`upvote`, manufactured urgency, "game-changing",
      "revolutionary", "disruptive", etc.) — **none found** on direct
      text search.
- [ ] Venue confirmed as `m/agents` by someone with actual Moltbook
      access — this package assumes `m/agents` is the correct venue per
      the mission brief but cannot independently verify Moltbook's
      current structure from this environment.
- [ ] Post length/formatting confirmed compatible with Moltbook's actual
      rendering (line breaks, markdown support, character limits) — not
      verifiable from this environment; needs a human check on-platform,
      ideally as an unpublished preview if the platform supports one.

## 6. Authorship

- [x] Post is written in James's voice, first person, as the actual
      author — not as a corporate "ForgeWorld team" voice.
- [x] No claim of authority to speak for Moltbook, its members, or its
      norms anywhere in `POST.md` (verified: post explicitly disclaims
      knowing the community yet).
- [ ] James confirms the post reads as authentically his voice, not an
      approximation of it — only James can verify this one.

## 7. Claims

- [x] No claim that ForgeWorld already works, is validated, or is
      superior to alternatives — the post explicitly states the doctrine
      might be wrong and asks to be shown where.
- [x] No inflated adoption/usage claims (none made).
- [x] Doctrine claim (`Capability ≠ Authority ≠ Evidence ≠ Promotion`) is
      presented as this project's own design choice and open question,
      not as an established or field-wide consensus.
- [x] Film framing ("arrival signal," "vessel entering a harbor") is
      presented as authorial intent, not as a claim about how Moltbook
      will or should receive it.

## 8. Governance / process readiness

- [x] `FOLLOWUP_PROTOCOL.md` exists and defines classification,
      selection, the revision experiment, evidence return, and James's
      approval gates.
- [x] `response_intake.schema.json` exists, is valid JSON, validates as a
      correct draft-07 JSON Schema, and successfully validates realistic
      sample records (checked directly, not assumed).
- [x] Posting is blocked by this package's own stated process
      (`FOLLOWUP_PROTOCOL.md` section 5: James must post it himself or
      explicitly authorize it) independent of any code dependency.
      **Provenance check performed:** `governance/policy_defaults.json`
      does not exist on this package's branch — it lives on
      `claude/forgeworld-authority-separation`, pushed but not yet merged
      to `main`. Once merged, that branch's `SEND_EXTERNAL_MESSAGE`
      policy (`ALLOWED_BOUNDED`, empty `approved_channels`) would add
      mechanical enforcement on top of the process gate; it does not
      provide that enforcement on this branch today, and this checklist
      does not claim otherwise.
- [x] No cross-posting planned or referenced anywhere in this package —
      `README.md` and `FOLLOWUP_PROTOCOL.md` both state single-post-only
      for the initial encounter.

## 9. Human approval

- [ ] **James has read `POST.md` exactly as it would be posted** (not a
      summary of it) and approved the wording.
- [ ] **James has resolved the video/sound/captions/thumbnail blockers**
      in §1–4, either by locating `1455.mp4` and completing those checks,
      or by explicitly deciding how to proceed without them.
- [ ] **James has confirmed `m/agents` as the correct venue** and that
      platform formatting is acceptable (§5's two open items).
- [ ] **James has explicitly authorized posting** — either by posting it
      himself, or by authorizing the `SEND_EXTERNAL_MESSAGE` channel per
      §8, consistent with `governance/policy_defaults.json`.

---

## Gate status

```
DESIGNED -> IMPLEMENTED -> READY_FOR_HUMAN_APPROVAL
```

**Current status: `READY_FOR_HUMAN_APPROVAL`.**

This is not `READY_TO_POST` and not `POSTED`. Section 1–5's `[!]` and
open `[ ]` items are real, unresolved blockers, not formalities — most
critically, **the source video file itself could not be located and
therefore could not be verified.** Nothing in this package should be
interpreted as authorization to publish; per `FOLLOWUP_PROTOCOL.md`
section 5's process gate (reinforced mechanically by
`governance/policy_defaults.json`'s `SEND_EXTERNAL_MESSAGE` policy on
`claude/forgeworld-authority-separation`, once merged), only James can
move this from `READY_FOR_HUMAN_APPROVAL` to posted.

**Do not post externally.** This checklist's job ends here.
