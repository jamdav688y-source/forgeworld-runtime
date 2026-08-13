# PRODUCT_SPEC.md — Next Right Move

**Role:** Product Architect
**Status:** Approved for implementation

## 1. What this is

Next Right Move is a private, single-session decision-clarification interface
for moments of mental overload. It helps a person separate observation from
interpretation, name an urge without acting on it, list real options, and
choose one small next step.

It is explicitly **not**: therapy, medical treatment, diagnosis, an AA
replacement, a sobriety scoring system, a crisis prediction system, or an
authority over the user. It never scores, classifies, or diagnoses the user.
It only reorganizes what the user already typed and reflects it back.

## 2. Core principle (hard constraint)

> Every interaction must leave the user with at least as much agency as they
> entered with.

This constraint is enforced by three implementation rules, checked in
`PRIVACY_AUDIT.md` and `TEST_REPORT.md`:

1. Every step is skippable. No field is required to proceed.
2. The app never tells the user what is true, what they should do, or what
   any input "means." It only relabels and redisplays their own words.
3. The user can leave at any time via `Clear session`, and doing so always
   succeeds, regardless of what screen they're on.

## 3. Acceptance criteria

- [x] Opens directly to "What's happening right now?" with no login, no
      name field, no account creation.
- [x] Seven linear steps, one meaningful question per screen:
      1. What happened? (FACT)
      2. What am I thinking or feeling? (STORY)
      3. What am I tempted to do? (URGE)
      4. What do I actually know? (fact-check against the story)
      5. What options do I have? (OPTION, multiple)
      6. Which option makes tomorrow easier? (COST)
      7. What is my next right move? (NEXT_MOVE)
- [x] Back / Skip / Next controls present on every step.
- [x] A summary screen shows everything entered, plainly labeled, with
      skipped fields marked "(skipped)" rather than hidden or guessed at.
- [x] "Run it again" perspective shift: asks what the user would tell a
      friend in the same situation, then shows it beside what they told
      themselves, without commentary or scoring.
- [x] Export produces a local `.txt` file via a user-initiated download;
      no network transmission.
- [x] Clear session wipes all stored data immediately and returns to the
      opening screen.
- [x] Works fully offline after first load (service worker + PWA manifest).
- [x] No account, telemetry, analytics, or remote calls anywhere in the code.

## 4. Non-goals (explicitly out of scope for v1)

- Multi-session history, streaks, or trends.
- Any scoring, risk level, or "how am I doing" metric.
- Push notifications or reminders.
- Multi-user, sharing, or sync features.
- Native app packaging (v1 targets the mobile browser / installed PWA only).
- Server-side or cloud AI processing of any kind.

Keeping these out of scope is a deliberate protection of the core principle:
anything that scores or predicts shifts authority from the user to the
software, which this product must not do.

## 5. State model

Internally, entries map to six neutral categories. These names are used only
in code and documentation — the UI never shows clinical or classification
language to the user.

| Internal name | UI question | Screen |
|---|---|---|
| FACT | What happened? | `fact` |
| STORY | What am I thinking or feeling? | `story` |
| URGE | What am I tempted to do? | `urge` |
| (knowledge check) | What do I actually know? | `knowledge` |
| OPTION (list) | What options do I have? | `options` |
| COST | Which option makes tomorrow easier? | `cost` |
| NEXT_MOVE | What is my next right move? | `nextmove` |

The software never infers a category from free text, never validates
"correctness" of an answer, and never blocks progress based on content.

## 6. Screen / state architecture

Linear step sequence, index-driven:

```
intro → fact → story → urge → knowledge → options → cost → nextmove → summary
                                                                   ↘ friend → compare → (back to summary)
```

`friend` and `compare` are reachable only from `summary`, via "Run it
again," and always return to `summary`.

## 7. Scope guardrails the architect protected against scope creep

- Rejected: emotion/sentiment tagging of user text (would introduce
  clinical inference).
- Rejected: "recommended" option highlighting (would remove user agency
  over the COST/NEXT_MOVE steps).
- Rejected: local history of past sessions (increases persisted data
  surface without a corresponding user need in v1; conflicts with the
  single-session privacy model).
- Rejected: any framework/build step — vanilla HTML/CSS/JS keeps the app
  runnable from Termux with a one-line static server and auditable in full
  by reading four small files.
