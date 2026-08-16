# Follow-Up Protocol

Governs everything that happens *after* `POST.md` is published, until a
report is returned to the community. This is a process document — a
description of how humans and agents handle responses together, not a
claim that any of it runs unattended. Where a step is backed by actual
code, that's stated explicitly, along with exactly where that code lives;
where it's a human-in-the-loop judgment call, that's stated too.

**Provenance note:** the `governance.*` code and policy table referenced
below (`governance/policy_defaults.json`, `governance/authority.py`,
`governance/pipeline.py`, `governance/evidence.py`,
`governance/promotion.py`, `tests/governance/`) live on branch
`claude/forgeworld-authority-separation`, pushed but not yet merged into
`main` and still `READY_FOR_HUMAN_REVIEW`. This package's own branch does
not include that code. References below to what that layer "enforces" or
"is" describe that branch's actual, tested behavior — not a claim that
it is already active on `main` or on this package's branch. The
process commitments in this document (single selection, human-confirmed
selection, human-gated promotion, human-gated posting) are honored by
this package directly regardless of that branch's merge status.

## 1. How responses are classified

Every response to the post is logged as one record conforming to
`response_intake.schema.json`, under one of these categories:

| Category | What it means |
|---|---|
| `critique` | Disagrees with or challenges the doctrine, the film, or the approach, without necessarily proposing an alternative. |
| `counterexample` | Offers a specific case where "Capability ≠ Authority ≠ Evidence ≠ Promotion" fails, doesn't apply, or produces a worse outcome than not separating them. |
| `teaching_method` | Offers a way of doing something (governance, agent design, community norms) that Moltbook already uses or has learned, which ForgeWorld might learn from. |
| `governance_concern` | Raises a concern about ForgeWorld's authority/approval model itself — safety, scope, who's accountable, what could go wrong. |
| `collaboration_offer` | Proposes working together, testing together, or building something jointly. |
| `adversarial_test` | An attempt to actually break the system, the doctrine, or the claims in the post — technically, logically, or rhetorically. |
| `noise` | Off-topic, spam, or not substantively engaging with the post's content. Logged, not discarded, so classification itself stays auditable. |

Classification is a first pass, done honestly and conservatively: when a
response could fit two categories, it is logged with the primary category
and a note of the secondary one in `notes`, not forced into a single box
it doesn't cleanly fit. `noise` is a real category, not a bin for
disagreement — a hostile but substantive critique is still `critique`,
not `noise`.

Every classification records its own uncertainty (see the schema's
`classification_confidence`). Low-confidence classifications are flagged
for a second look before they factor into selection (§2), not silently
trusted at face value.

## 2. How one meaningful challenge is selected

Only one challenge is acted on per this initial encounter — not because
only one will be good, but because acting on many at once is how a
first-contact response turns into noise of its own. Selection criteria,
in order:

1. **Specificity.** Does it name an actual case, mechanism, or failure
   mode, rather than a general objection? A precise `counterexample` or
   `adversarial_test` outranks a broad `critique` at this stage.
2. **Falsifiability.** Can a revision experiment (§3) actually test it?
   A challenge that can't be operationalized into something checkable
   isn't disqualified from being right, but it can't be *this* round's
   selection — it gets logged and carried forward instead.
3. **Stakes.** Does it point at something that would matter if
   ForgeWorld is wrong about it — a real failure mode, not a cosmetic
   disagreement?
4. **Independent corroboration.** If multiple responses converge on the
   same challenge from different angles, that raises its priority — this
   mirrors this repository's own evidence model
   (`governance.evidence`: independent observations from distinct
   sources escalate `OBSERVED` to `SUPPORTED`), applied here to responses
   instead of code.

Selection is proposed by whichever agent is monitoring responses, with
the reasoning shown, not just the pick — but the choice is not final
until James confirms it (see §5). This mirrors `governance.pipeline`'s
own separation of proposing a promotion from granting one.

## 3. How the revision experiment is conducted

"Revision experiment" means: take the selected challenge seriously enough
to actually test whether ForgeWorld should change because of it, and be
willing to find out the answer is yes.

1. **State the claim precisely.** Write down exactly what the challenge
   says is wrong, in a form specific enough to be wrong or right.
2. **Design the smallest test that could show it.** Prefer a concrete
   check (a scenario run through `governance.pipeline`, a policy
   change tried against `tests/governance/`, a documented walkthrough)
   over an abstract argument about whether the challenge has merit.
3. **Run it and record the raw result**, whichever way it comes out.
   A revision experiment that only gets recorded when it confirms
   ForgeWorld was right is not an experiment.
4. **Evaluate the result against the same evidence vocabulary already in
   this repository** (`governance.types.EvidenceState`: `OBSERVED` ->
   `SUPPORTED` -> `VALIDATED` -> `INSTITUTIONALIZED`). A single run that
   supports the challenge is `OBSERVED`, not proof; independent
   re-verification is what would move it toward `VALIDATED`.
5. **Do not let a successful experiment auto-apply itself.** Per the
   doctrine stated in the post itself, evidence that a change should be
   made is not authority to make it. Any actual change to ForgeWorld's
   code, policy, or doctrine goes through the same promotion gate
   everything else does (`governance.promotion.can_promote`), and
   `MODIFY_GOVERNANCE`-tier changes are `HUMAN_ONLY` per
   `governance/policy_defaults.json` regardless of how strong the
   experiment's result was.

## 4. What evidence is returned to the community

A follow-up report is posted back to `m/agents` (same venue as the
original post, no cross-posting) regardless of outcome. It includes,
plainly:

- The exact challenge selected, quoted or paraphrased with the original
  responder's permission per `response_intake.schema.json`'s consent
  fields (see §5 — attribution is never assumed).
- What was actually tested and how.
- The raw result, including if it went against ForgeWorld.
- What changed, if anything, and what evidence state that change reached
  before being applied.
- If nothing changed: an honest statement of why not, not a deflection.
- Thanks to the specific responder(s), if they consented to attribution;
  otherwise anonymized per their stated preference.

No follow-up report claims a stronger evidence state than what was
actually reached. If the experiment only produced `OBSERVED`-level
evidence, the report says `OBSERVED`, not "confirmed."

## 5. What requires James's approval

Everything below is a hard gate, not a courtesy check, and every one of
these gates is honored by this package's own process directly —
independent of whether `claude/forgeworld-authority-separation` has been
merged. Where that branch's policy table would mechanically enforce the
same gate once merged, that's noted as reinforcement, not as the sole
mechanism:

- **Posting `POST.md` at all** — no autonomous post to Moltbook happens
  under this package's process until James posts it himself or
  explicitly authorizes it. Once `claude/forgeworld-authority-separation`
  is merged, this is additionally enforced mechanically by
  `governance/policy_defaults.json`'s `SEND_EXTERNAL_MESSAGE` policy
  (`ALLOWED_BOUNDED`, empty `approved_channels` by default).
- **Selecting the one challenge to act on** — an agent may propose it;
  James confirms it before the revision experiment begins.
- **Any change to ForgeWorld's code, policy, or doctrine** resulting from
  the experiment stays human-gated by this package's own process. On
  `claude/forgeworld-authority-separation`'s policy table,
  `MODIFY_GOVERNANCE` and related capabilities are additionally `HUMAN_ONLY`
  in code, not just in this document's intent.
- **Posting the follow-up report** — same `SEND_EXTERNAL_MESSAGE` gate as
  the original post.
- **Any attribution or quoting of a specific responder** — only within
  the consent boundary that responder actually gave, per
  `response_intake.schema.json`'s `consent` object. Silence is not
  consent; an unclear consent field defaults to anonymized, not quoted.
- **A second post or any cross-posting** during the initial encounter —
  not permitted at all per `README.md`'s boundaries, regardless of how
  the first post is received.
