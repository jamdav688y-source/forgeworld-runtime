# Moltbook First Contact — Release Package

## Status

`DRAFT — NOT POSTED`. Nothing in this package has been published anywhere.
See `RELEASE_CHECKLIST.md` for the current gate status; it currently ends
at `READY_FOR_HUMAN_APPROVAL`, not `POSTED`.

**Known gap, disclosed up front:** the source film, `1455.mp4` ("THE
MOLTING," 30-second `PROMOTION_CANDIDATE` master), was referenced as
attached to this mission but could not be located anywhere in this
repository or this session's filesystem at the time this package was
written. Nothing in this package was written by watching or verifying
that file. Every claim below about the film's *content* comes only from
the mission brief itself (title, ~30s runtime, promotion-candidate
status, "arrival signal" framing) — never invented, never assumed. The
video/sound/captions/thumbnail line items in `RELEASE_CHECKLIST.md` are
explicitly left unverified rather than checked off. James (or whoever has
the actual file) needs to complete those checks before this package can
move past `READY_FOR_HUMAN_APPROVAL`. This package does not overwrite,
downgrade, move, or reference-replace `1455.mp4` — it does not touch the
file at all, since it was never found.

## Purpose

This package is everything needed to introduce ForgeWorld to Moltbook
once, carefully, through a single post in `m/agents`. It exists so that
first contact is a considered act, not an improvisation: the message,
the boundaries, how responses get read, how one response gets acted on,
and what gets reported back are all decided *before* anything is posted,
not while reacting to replies in real time.

## Narrative context

"THE MOLTING" is not an advertisement for ForgeWorld. It is described in
the mission brief as an arrival signal — a short film marking ForgeWorld
showing up somewhere it doesn't yet belong by right, only by introduction.
`POST.md` treats the film the way the mission frames it: a vessel
entering a harbor that already has its own traffic, its own habits, and
its own history that ForgeWorld does not yet know. The post is written
from that posture — arriving, not announcing; asking, not pitching.

Moltbook is treated in this package as a community with standing norms
and judgment ForgeWorld does not get to define, override, or speak for.
Nothing here asserts knowledge of Moltbook's culture beyond what's
directly observable once the post is live and people respond. Where this
package needs to describe Moltbook at all, it describes it as unknown-but-
respected, not characterized.

## What this package deliberately does not do

- Does not claim ForgeWorld understands or represents Moltbook's culture.
- Does not use marketing language, growth-hacking framing, or engagement
  bait ("upvote if...", "you won't believe...", manufactured urgency).
- Does not claim false familiarity with the community it's addressing for
  the first time.
- Does not promise more than one post during the initial encounter — no
  cross-posting, no coordinated multi-thread push.
- Does not pre-decide what Moltbook's answer to the central question will
  be, or treat any anticipated answer as more likely correct.
- Does not let a strong response substitute for James's review. Response
  volume or enthusiasm is not evidence of authorization to act — see
  `FOLLOWUP_PROTOCOL.md` and the authority-separation doctrine below.

## The doctrine this release is built on

This package deliberately reuses the authority-separation doctrine from
FORGEWORLD-AUTHORITY-SEPARATION-001. **Provenance note, stated precisely
rather than assumed:** that work (`docs/governance/AUTHORITY_MODEL.md`,
`governance/policy_defaults.json`, `governance/authority.py`, etc.) lives
on branch `claude/forgeworld-authority-separation`, pushed but **not yet
merged into `main`** and marked `READY_FOR_HUMAN_REVIEW`, not yet
approved. This package's own branch was cut from `main` and does not
include that code. Where this document describes something that code
mechanically enforces, that enforcement is real on
`claude/forgeworld-authority-separation` today and will be real on `main`
once that branch is merged — it is not yet active in this branch's own
tree. This package complies with the doctrine by design regardless of
merge status; the paragraphs below say plainly which parts are "this is
mechanically enforced elsewhere in this repo" versus "this package
follows the same principle without a code dependency on it."

> **Capability ≠ Authority ≠ Evidence ≠ Promotion**

Concretely, for this release:

- **Capability** — this runtime can technically compose and publish a
  post (text generation, and if a Moltbook posting integration exists,
  the mechanical ability to call it).
- **Authority** — whether it *may* publish to Moltbook is a separate
  question. On `claude/forgeworld-authority-separation`,
  `governance/policy_defaults.json`'s `SEND_EXTERNAL_MESSAGE` policy is
  `ALLOWED_BOUNDED` with an **empty `approved_channels` list by
  default** — meaning no autonomous send would be authorized to any
  channel, including `m/agents`, until a human explicitly adds it, once
  that branch is merged. Independent of whether/when that merge happens,
  this package treats posting as requiring James's direct action or
  explicit authorization — see `FOLLOWUP_PROTOCOL.md` section 5. That
  requirement does not depend on the governance branch being merged; it
  is also stated and honored directly in this package's own process.
- **Evidence** — what responses actually say, classified honestly (see
  `response_intake.schema.json`), is evidence. It is not itself
  authorization to revise anything.
- **Promotion** — incorporating a lesson from a response into ForgeWorld
  (the "revision experiment" in `FOLLOWUP_PROTOCOL.md`) is a promotion
  decision, independent of how strong the evidence is. On
  `claude/forgeworld-authority-separation`, `PROMOTE_RELEASE` and
  `MODIFY_GOVERNANCE` are `HUMAN_ONLY` in the policy table; this package
  follows that same posture as a stated commitment regardless of that
  branch's merge status.

## Release sequence

1. **Draft** (this state). All five files in this directory exist and are
   internally consistent.
2. **Human review** — James reads `POST.md` verbatim as it would post,
   confirms the film file/spec claims are accurate (the gap noted above),
   and confirms the platform/community fit (right subcommunity, right
   tone, nothing this package got wrong about Moltbook).
3. **Single post** — `POST.md`'s content is posted once, in `m/agents`,
   by James or through an explicitly authorized channel. No cross-posting
   during the initial encounter (see boundaries above).
4. **Listen** — responses are collected and classified per
   `response_intake.schema.json`; no reply-storm, no immediate rebuttals.
5. **Select** — one meaningful challenge is chosen per
   `FOLLOWUP_PROTOCOL.md`'s selection criteria.
6. **Revision experiment** — conducted per `FOLLOWUP_PROTOCOL.md`,
   evidence recorded honestly regardless of outcome.
7. **Report back** — findings are returned to the community in the open,
   including if the experiment didn't work or the challenge won.

## File index

| File | Purpose |
|---|---|
| `README.md` | This file. |
| `POST.md` | The exact first-contact post text. |
| `FOLLOWUP_PROTOCOL.md` | How responses are handled after posting. |
| `response_intake.schema.json` | Structured schema for logging responses. |
| `RELEASE_CHECKLIST.md` | Pre-publication gate; currently blocks on the missing video file and on James's approval. |
