# Assistant tests

Mode under test: **rules-based assistant (Option B)**. The language-model router (Option A) will be tested separately once added.

## Fix and retest: a question mentioning a store got a revenue answer

| Item | Entry |
|---|---|
| Question | "What is the weather in Denver?" |
| Expected behavior | Reply that the question is unsupported, list what the assistant can answer, and call no tool. |
| Actual behavior (before fix) | Called `get_total_revenue(store='Denver')` and answered "Revenue: $732,380.00 from 1,200 sales rows". That number is correct, but it answers a question nobody asked. |
| Cause | The router's last rule sent *any* question containing a recognized store, year, category or channel to `get_total_revenue`, even with no revenue word in it. |
| Related defect found the same way | "What is the meaning of life?" matched the keyword `earn` inside "m**earn**ing". Keywords were matched anywhere in the text instead of at the start of a word. |
| Fix | (1) The fallback now requires a revenue word (`revenue`, `sales`, `how much`, `total`, `earn`, `sell`, ...). (2) `_has()` only matches a keyword at the start of a word. (3) Store IDs are matched against the IDs in the loaded data instead of a hard-coded `SH##` pattern. |
| Retest | "What is the weather in Denver?" → unsupported reply listing capabilities, tool-call log empty. "How much revenue did Denver make?" still → `get_total_revenue(store='Denver')`. Regression tests `test_store_name_alone_is_not_a_revenue_question` and `test_unsupported_question` pass. |
| Result | Pass after fix |

## Fix and retest: language-model agent (Option A) on the live app, 2026-11-11

| Item | Entry |
|---|---|
| Problem 1 | The first live question fell back to the rules: `404 NOT_FOUND: models/gemini-2.5-flash is no longer available to new users. Please update your code to use models/gemini-3.8-flash`. The fallback worked as designed (correct rules answer, reason shown under the answer). |
| Fix 1 | Default model changed to `gemini-3.8-flash`. On a 404, the agent now lists the models the key can use, switches once to the newest general "flash" model and says so in the answer. Test: `test_retired_model_switches_to_newest_flash`. |
| Problem 2 | Question: "How much revenue did the website generate in 2028?" Gemini called `get_total_revenue(year=2028, channel=Website)` and `get_revenue_by_channel(year=2028)`, and the tools returned $6,339,640.00 and a 70.68% share. Gemini wrote "about 70%", and the number check rejected it ("Number check FAILED for ['70']"), replacing the model's findings with the tool-written ones. |
| Cause | The check only allowed ±0.5% or exact rounding, and 70.68 rounds to 71, not 70. An approximation marked by "about" is honest, not invented. |
| Fix 2 | A number that follows an approximation word (about, around, roughly, nearly, ...) may be within 3% of a tool value. A number stated as exact still must match to rounding, so "70%" with no "about" is still rejected. Tests: `test_whole_number_rounding_is_accepted`. Also added a 90-second request timeout, because that answer took about a minute, and a hung request now falls back to the rules. |
| Retest (live, after redeploy) | Same question. Gemini called `get_total_revenue` and `get_revenue_by_channel`. Its own findings were shown: website revenue in 2028 = 6339640, a 70.68% share of 8969470, with Brick & Mortar 2629830 (29.32%). Answered by: "Language-model agent (Option A, gemini-3.8-flash, function calling). Number check passed: every number matches a tool result." It also stated that revenue is not profit. **Pass.** |
| Follow-up | Gemini printed money unformatted and repeated the scope inside Findings, so the answer-format prompt now asks for `$1,234,567.89` formatting and no scope in Findings. |

## Fix and retest: Gemini overloaded (503), 2026-11-12

| Item | Entry |
|---|---|
| Question | "How much revenue did the website generate in 2028?" (Gemini mode, live app) |
| What happened | Gemini returned `503 UNAVAILABLE: This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.` The app fell back to the rules-based assistant, which answered correctly ($6,339,640.00 from 240 rows) and printed the reason under the answer. **This is the required graceful failure working on the real API.** |
| Problem | One temporary overload sent every question to the rules, even though Google says these spikes are brief. |
| Fix | Temporary server errors (503/500/UNAVAILABLE/"high demand") are retried twice, after 3 s and then 6 s. If the model is still overloaded, the agent switches once to the newest *other* flash model before falling back to the rules. Quota errors (429) are not retried, because waiting a few seconds does not help them. Tests: `test_overload_is_retried_then_answers`, `test_persistent_overload_switches_to_another_flash_model`, `test_quota_error_is_not_retried`. |
| Retest | Recorded with the required tests below. |
| Follow-up problem | After the retry fix, the same question left the app on "Calculating..." for more than 3 minutes. Each request could wait up to 90 s before timing out, and with retries plus a model switch the waits added up. This is also why the student reported that "the agent isn't working". |
| Follow-up fix | Each request now times out after 25 s, and the whole answer has a 60 s budget (`TIME_BUDGET`). Retries and the model switch only happen while time remains; after that, the rules-based assistant answers and says "no answer within 60 s". Test: `test_slow_model_falls_back_within_time_budget`. |

## Fix and retest: the model choice was the real problem, 2026-11-13

| Item | Entry |
|---|---|
| Symptom | A day later, Gemini mode still timed out (504 DEADLINE_EXCEEDED) on every question, so it was not a passing outage. |
| Diagnosis | With a local copy of the key (in the git-ignored `.streamlit/secrets.toml`), every model the key can use was timed on Test 1 through the app's real agent code, with a 120 s limit and no retries. |
| Timings | `gemini-3.5-flash-lite` **3.0 s, correct, number check passed** · `gemini-3.1-flash-lite` 3.8 s, 503 overloaded · `gemini-3.5-flash` 24.5 s, correct · `gemini-3.6-flash` 34.4 s, correct · `gemini-3.7-flash` 68.8 s, 503 · `gemini-3.8-flash` (the default until now) 73.0 s, 503 |
| Cause | The default, `gemini-3.8-flash`, was the slowest and most overloaded model. Its normal response time (25–70 s) is longer than the 25 s request limit added on 2026-11-12, so it could never succeed. |
| Fix | Default changed to `gemini-3.5-flash-lite`. If it is unavailable, the backups are tried in order: `gemini-3.5-flash`, then `gemini-3.6-flash`. Test: `test_backup_prefers_known_fast_model`. |
| Retest (local, real API) | All five required questions run with `gemini-3.5-flash-lite`: every answer was correct, took 1.4–2.8 s, and passed the number check (Test 3 used no numbers or tools). Test 5 gave $42,174,440.00 before and $42,175,440.00 with the +$1,000 file. Live retest below. |

## Required tests

**Run on the live app on 2026-11-12 with the rules-based assistant (Option B).** The "Use the rules-based assistant only"
switch was turned on because Gemini was overloaded that day (503 UNAVAILABLE and 504 DEADLINE_EXCEEDED on every attempt;
see the entries above). Each time, the language-model path fell back to these same rules answers, so the results below
are what a user saw either way. The tests will be repeated in Gemini mode (Option A) once the API responds normally.
Screenshots are in `validation/screenshots/`.

| Test | Question asked | Function(s) used | Expected result / behavior | Actual result | Pass / Fail | Revision made |
|---|---|---|---|---|---|---|
| 1. Numerical calculation | "How much revenue did the website generate in 2028?" | `get_total_revenue(year=2028, channel="Website")` | $6,339,640.00 from 240 rows, matching the independent PowerShell sum of the raw file | "Revenue: **$6,339,640.00** from 240 sales rows." Scope: year 2028, channel Website. States that revenue is not profit. (`test1_answer.jpg`, `test1_tool_log.jpg`) | Pass | None needed |
| 2. Numerical comparison | "Which store experienced the greatest percentage revenue decline between 2025 and 2029?" | `get_growth(by="store", start_year=2025, end_year=2029)` | SH11 Chicago, −66.81% ($539,740 → $179,130), and acknowledge that nearly every store declined (if none had declined, it should say so; that case is covered by `test_growth_says_when_nothing_declined`) | "Largest decline: **SH11 Chicago**; 20 of 21 declined." SH11: $539,740.00 → $179,130.00 (−66.81%). Only SH00 Website grew (+121.61%). Interpretation: the data shows *that* revenue changed, not *why*. Caveat: only the two end years are compared. (`test2_answer.jpg`, `test2_tool_log.jpg`) | Pass | Earlier: next-step wording made generic for channel/category questions |
| 3. Missing information | "Which E-Presso store is the most profitable?" | None (declined by design) | Decline: no costs or margins in the data, so revenue cannot show profitability; do not name a "most profitable" store | "I cannot answer that: the loaded data contains revenue only, with no costs, expenses or margins, so profitability cannot be calculated. Revenue is not profit…" Next steps list the missing information (operating costs, profit by store, leases, staffing, customer behavior). Tool log: 0 calls. (`test3_answer.jpg`) | Pass | None needed |
| 4. Analytical judgment | "Does higher customer satisfaction cause higher revenue?" | `get_satisfaction_vs_revenue()` | Report the association with its size and sample, say that correlation is not causation, and exclude unscored store-years rather than treating them as 0 | r = **0.235** (weak positive) across 100 store-years; interest r = 0.125. "This is an association… not evidence that satisfaction causes revenue (or the reverse)." Lists the 5 SH00 (website) store-years left out because they have no score. Next step: collect costs, traffic and store size before treating satisfaction as a lever. (`test4_answer.jpg`) | Pass | None needed |
| 5. Updated data | "What is E-Presso's total revenue?" asked before and after uploading `validation/Sales_plus1000.txt` (row S0120270601: 260 → 1,260) into the Sales box, with no restart | `get_total_revenue()` | Before $42,174,440.00 from the default file; after $42,175,440.00, with the scope naming the uploaded file | Before: **$42,174,440.00**, "Data: Default: data/Sales.txt". After: **$42,175,440.00**, "Data: Uploaded: Sales_plus1000.txt". The upload was then removed, and the app returned to the default file. (`test5_before.jpg`, `test5_after.jpg`) | Pass | None needed |
| Extra: fix and retest | "What is the weather in Denver?" | none (after fix) | Unsupported reply | Before the fix it returned Denver's revenue; after the fix, an unsupported reply with no tool call. See the first entry above. | Pass after fix | Router fallback and keyword matching |
