# Explicit Remaining Limitations

Listed so that nothing here is mistaken for a demonstrated capability.

## 1. Platform evidence

* **Never executed on Android/Termux or on Windows** (re-confirmed in directive 2: this session
  had no route to the owner's devices; PHYSICAL_PROOF_PROTOCOL.md is ready). Every test ran in a Linux container. The
  next step is to run `python -m pytest -q omega/tests` and `python -m omega.demo_e2e --workdir …`
  on the phone and on the PC, then a real phone→PC sync over the LAN (INSTALL.md), and record
  the results.
* **Windows specifics not exercised:** key-file permissions (0600 has no effect on Windows; the
  keys rely on the user profile ACL), firewall prompts, `py` launcher detection in
  `omega-forge.ps1`, the `GlobalMemoryStatusEx` RAM probe.
* **Termux specifics not exercised:** availability of `python-cryptography` and FTS5 in the
  installed SQLite build (the fallback is `LIKE`, which is tested only indirectly), Android
  background limits on `omega serve`.
* **LAN discovery** verified only on loopback UDP; broadcast across a real Wi-Fi network is
  untested and may be blocked by AP isolation.

## 2. Models

* **Ollama tested in the cloud container only** (0.40.16, `qwen2.5:0.5b`, `llama3.2:1b`,
  `qwen2.5:1.5b`, CPU). It has never run on the owner's PC. The built-in routing suite (1–2 cases
  per class) is too small to rank models: it misranked them in the real run (BENCHMARK_REPORT §2).
  The 50-case memory benchmark is author-written, not independent.
* No quantized on-phone model, no speech transcription, no semantic (embedding) retrieval.
  Retrieval is lexical (FTS5) plus deterministic token and 3-gram similarity.
* The specialist "agents" are deterministic rule checkers. An optional LLM note is recorded but
  never changes a verdict. No multi-agent LLM reasoning was demonstrated. There is no code
  generation; the promotion gate evaluates candidates but nothing in omega produces them.

## 3. Relationship memory accuracy

* Question classification and answer extraction are **English, regex-based** and cover a fixed
  attribute set (budget, timeline, company, role, location, email, phone, availability,
  preferred_name, goal, boundaries). Reworded questions outside those patterns fall back to
  Jaccard similarity ≥ 0.5 against previously answered questions, which can miss paraphrases
  or flag false positives.
* A reply is attributed to a question only when it directly follows our message in the same
  conversation. When exactly one question was asked and no value pattern matches, the first
  sentence of the reply is stored as the answer (basis `STATED_IN_REPLY`, UNVERIFIED).
* Contradiction detection covers budget amounts and email addresses only.
* Cross-contact leak detection matches names and known fact values literally. It cannot catch
  paraphrased disclosures.

## 4. Security and privacy boundaries

* Event **headers** (type, links, timestamps, privacy class) are visible to every paired peer,
  including for `DEVICE_LOCAL` and withheld events (ADR-0002). Contact links are now keyed by a
  device secret (not recomputable from a phone number), but deal ids, task ids and timing remain
  visible.
* Contact ids are per device: the same person created independently on both devices before a
  sync becomes two contacts. After a sync, `add_contact` reuses the synced id.
* **Device** keys (event signing, sync) are stored unencrypted, protected only by OS file
  permissions. The **operator** key that gates consequential actions is passphrase-encrypted
  (scrypt + ChaCha20-Poly1305), but it is not hardware-backed, and a keylogger that captures the
  passphrase defeats it.
* Human actors are authenticated **only for consequential event types**
  (`policy.ATTESTED_TYPES`: task authorization, deletion, payment verification, promotion,
  retention, pairing, revocation). For everything else (messages, facts, notes),
  `--actor human:alice` is still the operator's unauthenticated assertion. One operator per
  device.
* `--passphrase-stdin` exists for scripted proofs. Anything that can write to that stdin can
  authorize, so it is not for daily use.
* The SAS is 6 digits (≈20 bits): adequate for an interactive, attended pairing, not for an
  unattended one.
* Purged payloads are removed from the live database. Earlier backups, exported bundles and
  SQLite free pages may still contain them until the file is vacuumed (`VACUUM` is not run
  automatically).
* Three-or-more-device relaying works only if every originating device is paired with the
  receiver (unknown signers are refused).

## 5. Scale

* Reconciliation computes causal ancestry by graph walk per assertion, and the sync sender scans
  the event table per batch. Fine for thousands of events; not tuned for millions.
* Artifacts are capped at 8 MiB each and travel inline in sync frames.

## 6. Integration debt

* `omega/commercial.py` and `cognition/commerce.py` are separate ledgers (ADR-0003); there is no
  omega→CXP bridge yet.
* `CapabilityGraph`, `WorkflowCompiler` and `substrate/CapabilityPromotionGate` are not on this
  branch. When they are merged, `omega.evolution.PromotionGate` must be reconciled with them
  (ADR-0001).
* The legacy `scripts/forge-sync-pack.sh` tarball flow is left as is. It is unauthenticated and
  unencrypted; use `omega bundle-export` instead.
