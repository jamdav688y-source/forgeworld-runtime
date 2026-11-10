# YouTube Demonstration Package (target 6:30, range 5–8 min)

**Working title:** *My AI forgot what my client told me. So I built one that can't — and tested where it still fails.*

**Publication gate:** nothing in this package is published or uploaded by Claude. Recording,
editing and publishing are the owner's decisions and need the owner's explicit approval.

**Honesty rules for the edit:**
1. Every shot of the phone and the Windows PC must be **real footage of the owner's devices**,
   recorded while running PHYSICAL_PROOF_PROTOCOL.md. Until that run exists, scenes 4–5 cannot be
   filmed as "physical": use the cloud-container recording with a lower-third caption **"cloud
   development container — not my phone/PC"**.
2. Show the failures (scene 6) at the same length as the successes.
3. Every number on screen comes from a file in `docs/omega/` (cite it in the description).
4. Use only the fictional contact "Dana Reyes" and test numbers (`+1555…`, `+1000…`). Never show a
   real person's messages.
5. The "agents" are deterministic rule checkers, plus a local model used as a measured advisor. Do
   not describe them as autonomous AI agents.

## Recording sequence (shot list)

| # | Time | Picture | Source command / asset |
|---|---|---|---|
| 1 | 0:00–0:35 | Face cam or B-roll: phone + laptop on desk | — |
| 2 | 0:35–1:20 | Terminal: `python -m omega.showcase --pause`, ACT 1 | showcase |
| 3 | 1:20–2:00 | Diagram: phone ↔ PC, signed events, sealed bundle | draw from SYNC_PROTOCOL.md |
| 4 | 2:00–3:10 | **Phone screen recording** (Android screen record): airplane mode on, Termux capture, `check-draft` → REPEATED_QUESTION | PHYSICAL_PROOF_PROTOCOL §3 |
| 5 | 3:10–4:00 | Split screen: phone Wi-Fi on → `lan-sync`; **PC** PowerShell `lan-serve`, `omega verify`, `omega context` | §3 |
| 6 | 4:00–5:10 | Showcase ACT 3–4: forged authorization refused, replay refused, the rules **miss** a paraphrase, the model catches it as a WARN, benchmark table | showcase; BENCHMARK_REPORT.md |
| 7 | 5:10–5:50 | `python -m omega.proof verify windows-….proof.json` on screen, `untampered: true` | proof files |
| 8 | 5:50–6:30 | Face cam: limits + what's next | PROOF_REPORT.md |

## Narration (≈ 900 words ≈ 6:30 at 140 wpm)

**[1 — Hook, 0:00]**
*(Owner: if you have a real example of this happening to you, tell it here in your own words.
Otherwise keep the hypothetical framing below. Do not present it as something that happened.)*
Picture this: an AI assistant drafts a follow-up asking a client for their budget, and the
client told you the budget two days ago. It's a small thing, but it tells the client nobody was
listening. So I built a memory system for my phone and my PC that's supposed to stop that
mistake. Then I tested it properly, including the parts where it still fails.

**[2 — The problem, 0:35]**
Here's the baseline most tools use: don't send exactly the same text twice. On my test set of
fifty questions, thirty-one of them repeats of something the client already answered, that check
catches ten. Every reworded repeat ("how much were you planning to spend?") gets through. Zero
percent.

**[3 — The design, 1:20]**
The design has three rules. First, the phone is a complete system on its own: it works in airplane
mode, with no cloud and no PC. Second, every fact is an event signed by the device that recorded
it, linked to its source, here the original SMS bytes, and history is never edited. Corrections
are new events. Third, when the phone and PC meet, they prove who they are to each other,
encrypt everything, and only exchange what each one is missing. If the connection drops halfway,
nothing is lost and nothing is duplicated.

**[4 — Offline capture, 2:00]**
The phone is in airplane mode. I record that I asked for a budget, and the reply: "about 5k". The
phone extracts the answer and keeps a pointer to the exact message it came from. Now I draft "what's
your budget?" — and it's blocked: repeated question, with the evidence attached.

**[5 — Sync and verification, 3:10]**
Wi-Fi back on. The PC is listening. Before any data moves, both devices check each other's keys,
which I confirmed once by comparing six digits on both screens. One sync: the new events arrive.
The PC re-verifies every signature and rebuilds the same view of this contact that the phone has.
I run the sync again: zero events move. No duplicates.

**[6 — Failures and the correction, 4:00]**
Now the parts that matter more. Can an AI agent on my PC approve sending a message by itself? It
tries. Refused. Approvals need my operator key, which is locked by a passphrase only I know.
Replaying an old sync file? Refused. And here's a real weakness: I reword the budget question, and
the rule-based checker misses it. On the benchmark, the rules catch only a third of reworded
repeats. So I added a small local model, Qwen 2.5 at 1.5 billion parameters, running on my own
machine. It catches 18 of 21 reworded repeats. But it also raises 8 false alarms where the rules
raise 2. Its typical mistake is treating "same topic" as "same question". So it doesn't get to
block anything: it only warns, and the rules keep the veto. And the biggest model I tried,
Llama 3.2 1B, was the worst of the lot, which is why this system picks models by measured
results, not size.

**[7 — Proof, 5:10]**
Everything you saw writes a signed proof file: which code ran, on what platform, every check and
its raw result. Anyone can clone the repo, run one command on their own machine, and check my
file hasn't been edited.

**[8 — Limits, 5:50]**
What this isn't: it isn't finished. The test set was written by me, so it's not independent. The
operator passphrase protects against software on my machine, not against someone watching me type
it. And none of this has been tested on a client's real data. Next: an independent test set, a
hardware-backed key, and connecting this to the business pipeline. The code and the
reproduction steps are linked below.

## Description template

Code: <repo link>. Reproduce: `python -m omega.proof run --device "<your machine>" --out p.json`.
Benchmark: docs/omega/BENCHMARK_REPORT.md (50 cases, sha256 d9429aee…). Limitations:
docs/omega/LIMITATIONS.md. Recorded on: <devices, from the proof files>.
