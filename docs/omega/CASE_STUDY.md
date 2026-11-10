# Case Study — Conversation memory that doesn't repeat itself

*Internal capability case study. There is no customer deployment yet; no customer outcome is
claimed.*

**The problem.** Small service businesses run client conversations across SMS, email and calls.
Drafting tools, human or AI, regularly re-ask questions the client already answered, mix up
names, or forget a promised follow-up. Each slip costs trust in exactly the conversations that
decide a sale. Cloud CRMs handle this by sending every message to a third party, which many
clients do not want.

**What was built.** ForgeWorld Ω is a local-first memory that runs on the owner's phone and PC.
Every captured message keeps its original source. Answers are extracted into facts linked to that
evidence. Before a draft goes out, it is checked for repeated questions, wrong names, broken
boundaries ("don't call me"), contradictions, another client's private details, and overdue
promises. The two devices sync directly, authenticated and encrypted, and work fully offline.
Nothing is sent to an outside service. Payment status separates "client says they paid" from
"bank record confirms it". Consequential actions (sending, deleting, confirming payment) need
the owner's passphrase-locked key, so an AI assistant can prepare work but cannot act alone.

**Measured result (50-question benchmark, local CPU, cloud container — BENCHMARK_REPORT.md):**

| Approach | Repeats caught (of 31) | False alarms (of 19 new questions) | Time per check |
|---|---|---|---|
| "Never send the same text twice" | 10 | 0 | <1 ms |
| ForgeWorld rules (blocking) | 17 | 2 | 2 ms |
| Rules + local Qwen 2.5 1.5B (warnings) | 29 | 9 | ≈350 ms |

**What is proven, and what isn't.** Proven by reproducible tests: offline operation, signed
provenance, authenticated and resumable sync, duplicate and replay rejection, refusal of
unauthorised actions, and the numbers above. Not yet proven: operation on a real phone and PC
(a protocol is ready), accuracy on real client conversations, and an independent test set (the
benchmark's author also wrote the rules).

**What a pilot would look like.** One business, one operator, four weeks, the operator's own
phone and PC. Measure the number of drafts blocked or warned and the operator's verdict on each
(true or false alarm), compared with the four weeks before. The data stays on the operator's devices;
only the counts are reported, with consent.
