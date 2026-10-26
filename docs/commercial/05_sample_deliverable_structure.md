# Sample Deliverable Structure — Workflow Loss Diagnostic Report

> **DRAFT FOR OPERATOR REVIEW.** Not validated with any customer.
>
> **STRUCTURE ONLY.** This is the outline the customer would receive. It contains no findings, because no diagnostic has been carried out. Bracketed text describes what each section will hold.

---

**Workflow Loss Diagnostic — [Customer] — [Workflow]**
Version `[n]` · Prepared `[date]` · Checked against Outcome Specification `[reference]`

### 1. Summary (one page)
- The workflow examined, and its start and end points.
- The three most significant loss points, each in one sentence with its evidence label.
- The single proposed improvement and how it would be tested.

### 2. Scope and sources
- What was in scope and what was not.
- Sources used: documents and exports (with date ranges), conversations (by role, never by name), observations.
- What we could not examine, and why.

### 3. Current-state workflow map
- A step-by-step diagram from start to end.
- Each handoff marked: who passes what to whom, and how (system, email, phone, paper).
- Points where work has **no owner**, **waits for a decision**, or is **re-entered** are highlighted.

### 4. Loss register
| # | Where | What happens | How often | Evidence | Confidence |
|---|---|---|---|---|---|
| L-1 | `[step/handoff]` | `[work disappears / stalls / repeats / needs manual rescue]` | `[measured value or "unmeasured"]` | `[export, staff account, observation]` | `[high / medium / low]` |

### 5. Evidence and uncertainty register
- Every finding mapped to its sources.
- Where sources disagree, both versions are shown. Disagreements are not averaged away.
- Explicit list of what remains **unmeasured** or **unverified**.

### 6. Prioritised opportunities (top three)
| # | Opportunity | Addresses | Effort (estimate) | Expected impact (estimate, range) |
|---|---|---|---|---|

### 7. Proposed improvement (one)
- The change, described precisely enough to try.
- **Validation plan:** what to measure, the current baseline (or how to establish it), the trial duration, and what result would count as success or failure.
- Risks and how to stop the trial safely.

### 8. Implementation scope estimate
- What doing it would involve: people, steps, tools, approximate effort.
- What is **not** included.

### 9. Limitations and disclosures
- All impact figures are estimates until measured.
- Findings cover only the sources listed in section 2.
- No individual's performance is assessed.

### Appendix: Acceptance checklist
A table of the agreed acceptance criteria (AC-1 … AC-8), each marked met or not met, with where in the report it is satisfied. The customer confirms acceptance, or asks for a revision, against this list.
