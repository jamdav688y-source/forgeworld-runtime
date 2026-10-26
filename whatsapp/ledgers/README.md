# Ledgers

Runtime-generated jsonl files land here (`conversation_ledger.jsonl`, `execution_ledger.jsonl`,
`consent_ledger.jsonl`, `opportunity_ledger.jsonl`, `signal_ledger.jsonl`). They are gitignored — once
live traffic flows, this directory holds real customer data and must never be committed. Tests never
write here; see `whatsapp/tests/base.py`, which redirects every ledger path to a temp directory.
