# Prioritized Next-Right-Move List

1. **Meta Business verification + WhatsApp Business Platform onboarding.** Nothing downstream matters
   until this exists. Without it there is no legitimate way to get `WHATSAPP_ACCESS_TOKEN` /
   `WHATSAPP_PHONE_NUMBER_ID` / `WHATSAPP_APP_SECRET`.
2. **Host `whatsapp/src/server.py` behind TLS** somewhere reachable by Meta's webhook infrastructure
   (a small VPS, or a tunnel for initial testing). Register the webhook URL and confirm the GET
   handshake succeeds against the real Meta dashboard.
3. **Register one approved message template** (e.g. a first-contact or follow-up template) so outbound
   sends outside the 24h window are possible at all — required before `DRAFT_ONLY` approvals can ever
   actually be delivered.
4. **Run one real inbound message through the live system** with `OUTBOUND` still `DRAFT_ONLY`, and
   manually review the resulting `conversation_ledger.jsonl` / `execution_ledger.jsonl` entries against
   the schema and authority matrix before trusting the pipeline with real traffic.
5. **Legal/privacy review** of `governance/04_PRIVACY_RETENTION_MODEL.md` — this was written by an AI
   agent, not counsel, and must be checked against wherever ForgeWorld's customers actually are before
   real PII flows through the ledgers.
6. **Add encryption at rest** for the ledgers once real PII is involved (currently plaintext jsonl,
   acceptable only because no real data exists yet — see ADR consequences).
7. Only after 4–6: consider moving specific low-risk actions (already enumerated in
   `governance/05_AUTHORITY_MATRIX.md`'s AUTO tier) from CLI-approved to `ASSIST_LOW_RISK`, one action
   at a time, each backed by real approval/edit-rate evidence from the execution ledger — not by
   assumption.
8. Wire the classifier's AI-routing extension point (`classify.py`, bottom docstring) through
   `router/mission_router.py` only once there's a concrete reason the deterministic classifier is
   insufficient, with logged before/after evidence to justify the switch.

`CAMPAIGN` mode, mass outreach, and any autonomous commitment stay out of scope until real operational
evidence exists — per the mission's own default posture, not as a placeholder to revisit casually.
