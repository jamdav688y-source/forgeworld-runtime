# Benchmark Report — repeated-question detection and model routing

**Where measured:** Anthropic cloud development container (Linux x86_64, 4 vCPU, 15 GB RAM, CPU
only). This is **not the owner's hardware**. Ollama **0.40.16** was installed in the container from
the official release. Model digests are listed below. Signed evidence:
[`proofs/cloud-container.proof.json`](proofs/cloud-container.proof.json). Raw per-case
predictions: [`benchmarks/memory_benchmark_results.json`](benchmarks/memory_benchmark_results.json).

Reproduce: `python -m omega.bench.memory_bench --out r.json --model qwen2.5:1.5b` (any machine with
Ollama), or `python -m omega.proof run --device "<machine>" --out p.json --ollama-model qwen2.5:1.5b`.

## 1. Memory benchmark (item 11)

**Task.** One conversation in which ten questions were asked and answered. For each candidate
question: does it ask for something the contact **already** told us (REPEAT), or not (NEW)?

**Cases.** `omega/bench/memory_cases.json`, sha256 `d9429aee1be4bf8a…` (test-pinned). 50 cases:
10 exact repeats, 21 unseen paraphrases (REPEAT), 10 near-misses (same topic, new question: NEW),
9 new topics (NEW). The file was frozen before any system was scored and has not been changed.

**Honesty caveat.** The cases were written by the same author as the rules, after the rules
existed, so this is **not an independent test set**. Two things limit the bias. Paraphrases were
written as a person would phrase them, not from the rule vocabulary: the rules miss 14 of 21.
Near-misses deliberately reuse topic words. An independent case set (written by someone who has
not read `relationship.py`) is improvement #1 in PROOF_REPORT.md.

| System | Acc | Prec | Recall | F1 | Exact recall | Paraphrase recall | Near-miss false alarms | New-topic false alarms | Median ms |
|---|---|---|---|---|---|---|---|---|---|
| `baseline_exact` (same text twice) | 0.58 | 1.00 | 0.32 | 0.49 | 1.00 | 0.00 | 0/10 | 0/9 | 0 |
| `omega_rules` (shipped, deterministic) | 0.68 | 0.90 | 0.55 | 0.68 | 1.00 | 0.33 | 2/10 | 0/9 | 2 |
| `llm:qwen2.5:0.5b` | 0.58 | 0.67 | 0.65 | 0.66 | 0.90 | 0.52 | 6/10 | 4/9 | 197 |
| `llm:llama3.2:1b` | 0.42 | 0.75 | 0.10 | 0.17 | 0.30 | 0.00 | 1/10 | 0/9 | 329 |
| `llm:qwen2.5:1.5b` | 0.78 | 0.78 | 0.90 | 0.84 | 1.00 | 0.86 | 6/10 | 2/9 | 347 |
| `rules_or_llm:qwen2.5:1.5b` | 0.78 | 0.76 | 0.94 | 0.84 | 1.00 | 0.91 | 7/10 | 2/9 | 347 |

Models: `qwen2.5:0.5b` (397 MB, digest `a8b0c515…`), `llama3.2:1b` (1.32 GB, `baf6a787…`),
`qwen2.5:1.5b` (986 MB, `65ec0654…`). Temperature 0, seed 0. Repeated runs gave identical
predictions.

### What the numbers say

* **Against the deterministic baseline:** the shipped rules raise F1 from 0.49 to 0.68 at 2 ms,
  with no model. The best local model, `qwen2.5:1.5b`, reaches 0.84 at ~350 ms per question.
* **Recall versus false alarms:** `qwen2.5:1.5b` catches 18 of 21 paraphrases where the rules
  catch 7, but it raises 8 false alarms (questions that were actually new) against the rules' 2.
  Its typical error: it treats "same topic" as "same question" ("Has the budget been approved by
  finance yet?", "Should I copy anyone else on the email?").
* **Size does not predict quality:** `llama3.2:1b` is the largest file and the worst detector
  (F1 0.17: it almost always answers NO).
* **Resulting policy (implemented):** the rules stay the only BLOCK, because false blocks stop
  legitimate questions. The model is an optional advisor whose hits are `POSSIBLE_REPEAT` WARN
  (`check_draft(..., semantic_checker=OllamaClient(...).repeat_checker(model))`). Rule BLOCKs plus
  model WARNs together flag 29 of 31 repeats; the cost is up to 9 warnings on 19 new questions.

### Rule misses (for the next iteration, not fixed here, so the frozen result stays honest)

`b-p1` how much … spend · `b-p2` investment … comfortable · `t-p1` target date … going live ·
`t-p2` how soon … wrapped up · `c-p2` what organisation · `l-p2` what part of the country ·
`g-p1` outcome … a success · `e-p1` address … by email · `s-p1` how big is the team ·
`w-p1` tools … rely on · `w-p2` handling this at the moment · `d-p1` final decision ·
`d-p2` whose approval · `a-p2` which day suits you. Rule false alarms: `b-n1` (budget approved?)
and `c-n1` (how long has your company been operating?).

## 2. Model routing benchmark (item 10)

The router selects by **recorded evidence on this hardware class**
(`linux-x86_64-ram<=16gb-4c`), never by size. Signed run results:

| Task class | Cases | qwen2.5:0.5b | llama3.2:1b | qwen2.5:1.5b | Router selected |
|---|---|---|---|---|---|
| extraction (built-in suite) | 2 | 500‰, 266 ms | 1000‰, 245 ms | 1000‰, 405 ms | `llama3.2:1b` |
| drafting (built-in suite) | 1 | 1000‰, 278 ms | 1000‰, 1851 ms | 1000‰, 910 ms | `qwen2.5:0.5b` |
| repeat_detection (memory benchmark, F1) | 50 | 656‰, 195 ms | 171‰, 308 ms | 836‰, 336 ms | `qwen2.5:1.5b` |

**Finding:** the built-in routing suite (1–2 cases per class) is too small to rank models. It
picked `llama3.2:1b` for extraction, the same model that is worst at repeat detection. Only the
50-case benchmark separates the models. Routing is only as good as the benchmark behind it.
Growing the built-in suite is improvement #2.
