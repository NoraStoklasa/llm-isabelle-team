# Bugs Fixed in planner/driver.py

All four bugs were in `planner/driver.py`. No other files were changed.

---

## Bug 1 — Finisher verification loop never ran (Fix A)

### What the bug was

When `_fill_one_hole` needs to close a proof hole, it calls `prove_goal` from
the prover. Inside `prove_goal`, Isabelle's Sledgehammer runs first to find
candidate tactics (like `by auto`). Sledgehammer always runs for its full
timeout (10 seconds). After Sledgehammer finishes, the code tries to verify
each candidate with `if time_left_s() <= 0: break`.

The problem: the per-hole budget passed to `prove_goal` was often 5–20 seconds
(computed from how much global time was left). Since Sledgehammer alone consumed
10 of those seconds, `time_left_s()` was zero or negative by the time the
verification loop started. All candidates were skipped immediately.

`prove_goal` then returned `success=False` with `steps = ["lemma \"...\""]`
(just the seed). There were no finishers in this result dict. Back in
`_fill_one_hole`, `fin = ""` and `applies = []`, so the function returned
`(full_text, False, "no-steps")` — no progress.

### Symptom

The trace printed:

```
Sledgehammer finishers: ['by auto', 'by simp', ...]
Finishers (origin): [sledge:by auto, sledge:by simp, ...]
[fill] Fill made no progress. Escalating to repair stage 1...
```

Notice there are NO `finish ✓ [sledge] by auto` lines between the two print
statements. That means the finisher loop ran zero iterations. Sledgehammer
found valid tactics but they were never tried.

### Fix (Fix A)

Added a **quick finisher fast-path** in `_fill_one_hole`, placed *before* the
`prove_goal` call. It tries five standard Isabelle tactics (`by auto`, `by simp`,
`by blast`, `by fastforce`, `by force`) directly on the full proof text. Each
attempt calls `_verify_full_proof` which costs ~2–4 seconds. If any tactic
closes the hole, the function returns immediately and `prove_goal` is never
called at all.

**Before:**
```python
eff_goal = _effective_goal_from_state(state_block, goal_text, full_text, hole_span, trace)

res = prove_goal(
    isabelle, session, eff_goal, ...
)
```

**After:**
```python
eff_goal = _effective_goal_from_state(state_block, goal_text, full_text, hole_span, trace)

# Fix A: try standard tactics directly in the full proof before calling prove_goal.
# Each _verify_full_proof costs ~2-4s; prove_goal+sledgehammer costs 12-35s and can
# exhaust per_hole_budget before its finisher loop gets to run.
_qf_s, _qf_e = hole_span
_qf_line_start = full_text.rfind("\n", 0, _qf_s) + 1
_qf_indent = " " * (_qf_s - _qf_line_start)
for _qf in ("by auto", "by simp", "by blast", "by fastforce", "by force"):
    _qf_text = full_text[:_qf_line_start] + _qf_indent + _qf + full_text[_qf_e:]
    if _verify_full_proof(isabelle, session, _qf_text):
        if trace:
            print(f"[fill] Quick finisher succeeded: {_qf!r}")
        return _qf_text, True, _qf

res = prove_goal(
    isabelle, session, eff_goal, ...
)
```

---

## Bug 2 — Wrong indentation when inserting a finisher (Fix B)

### What the bug was

When a finisher was found (either from Fix A's fallback or from `prove_goal`),
the code inserted it into the proof by replacing the word `sorry` using its
character offset. `find_sorry_spans` returns the span of just the *word*
`sorry`, not its surrounding line. So `full_text[:s]` ended with the whitespace
that was already on the sorry's line (e.g., four spaces of indentation). The
insert string started with `"\n  "` — a hardcoded two-space indent.

This left the old indentation stranded on its own line, and put the new tactic
at the wrong depth:

```
  show ?case
      ← original 4-space indent, now a blank-ish line
  by auto   ← 2-space indent (wrong)
```

### Symptom

`_verify_full_proof` would sometimes return `False` on the substituted proof,
causing the function to return `"finisher-unverified"` even though the tactic
was correct. The malformed indentation could confuse Isabelle's parser in
certain proof structures.

### Fix (Fix B)

Go back to the *start of the line* containing `sorry`, compute the actual
indentation used there, and use that same indentation for the finisher. This
cleanly replaces the entire sorry line.

**Before:**
```python
if fin:
    script_lines = applies + [fin]
    insert = "\n  " + "\n  ".join(script_lines) + "\n"
    s, e = hole_span
    new_text = full_text[:s] + insert + full_text[e:]
```

**After:**
```python
# Handle finisher (Fix B: use the sorry's own line indentation, not hardcoded 2 spaces)
if fin:
    script_lines = applies + [fin]
    s, e = hole_span
    _b_line_start = full_text.rfind("\n", 0, s) + 1
    _b_indent = " " * (s - _b_line_start)
    insert = _b_indent + ("\n" + _b_indent).join(script_lines)
    new_text = full_text[:_b_line_start] + insert + full_text[e:]
```

The key change: `full_text[:_b_line_start]` goes back to the newline *before*
the sorry line, then `_b_indent` is the exact whitespace the sorry had. The
result is a clean replacement with correct indentation.

---

## Bug 3 — Repair time threshold too low (Fix C)

### What the bug was

After Fill failed, the CEGIS repair was gated by:

```python
if current_stage > 0 and repairs and left_s() > 6:
```

A single repair round needs to:
1. Call `_print_state_before_hole` (~3s)
2. Call the LLM via `_generate_simple` (5–15s for Gemini)
3. Call `_run_theory_with_timeout` to verify (~5s minimum)

That is roughly 13–23 seconds minimum. With only 6 seconds as the threshold,
the repair block would start, call the LLM, and time out before getting a
response. The LLM call itself takes longer than the remaining budget.

### Symptom

Repair appeared to fire (the `if` condition was True) but produced no output
because every LLM call timed out immediately. The hole was never repaired.

### Fix (Fix C)

Raised the threshold from 6 to 20 seconds. At 20 seconds, there is enough time
for one LLM call plus at least one Isabelle verification attempt.

**Before:**
```python
if current_stage > 0 and repairs and left_s() > 6:
```

**After:**
```python
if current_stage > 0 and repairs and left_s() > 20:  # Fix C: was > 6; LLM+verify needs ~20s
```

---

## Bug 4 — Infinite spin loop when budget expired at maximum repair stage

### What the bug was

The main Fill/Repair loop runs as:

```python
while "sorry" in full and left_s() > 0:
    ...
```

When the CEGIS repair escalated a hole all the way to stage 2 (maximum), and
then the global timer reached zero, two things happened together:

1. **Fill was skipped** — `start_stage = 2`, so the `if start_stage == 0:`
   branch was not taken. Fix A never ran.
2. **Repair was skipped** — `left_s() = 0`, which is not `> 20`.

The loop body did nothing at all, and fell through to the `while` condition.
Here, floating-point arithmetic meant `left_s()` did not return exactly `0.0`
but something like `0.0001`. In Python, `0.0001 > 0` is `True`, so the loop
ran again. Since no Isabelle calls were being made, each iteration took only
microseconds. The loop printed two trace lines per iteration and ran
hundreds of thousands of times.

### Symptom

After the timer expired, the process produced megabytes of output like:

```
[fill-diag] per_hole_budget=5, left_s=0.0, n_spans=3
[fill-diag] repair check: left_s=0.0, current_stage=2, repairs=True
[fill-diag] per_hole_budget=5, left_s=0.0, n_spans=3
[fill-diag] repair check: left_s=0.0, current_stage=2, repairs=True
... (thousands more identical lines) ...
```

The process appeared to hang and never terminated on its own.

### Fix (Spin guard)

Changed the while condition from `> 0` to `> 1.0`, and added a belt-and-
suspenders `break` inside the loop body:

**Before:**
```python
while "sorry" in full and left_s() > 0:
    spans = find_sorry_spans(full)
    if not spans:
        break
```

**After:**
```python
while "sorry" in full and left_s() > 1.0:
    if left_s() < 1.0:  # belt-and-suspenders: stop float-precision spin
        break
    spans = find_sorry_spans(full)
    if not spans:
        break
```

The `> 1.0` threshold means the loop exits as soon as less than one second
remains — at that point, no Isabelle call (minimum ~2 seconds) could complete
usefully anyway. The inner `break` is redundant given the `while` condition
but adds a second layer of protection in case the condition is ever changed.
