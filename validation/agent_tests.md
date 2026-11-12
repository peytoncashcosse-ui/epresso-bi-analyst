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

## Required tests (to be completed)

| Test | Question asked | Function(s) used | Expected result / behavior | Actual result | Pass / Fail | Revision made |
|---|---|---|---|---|---|---|
| 1. Numerical calculation | | | | | | |
| 2. Numerical comparison | | | | | | |
| 3. Missing information | | | | | | |
| 4. Analytical judgment | | | | | | |
| 5. Updated data | | | | | | |
| Extra: fix and retest | "What is the weather in Denver?" | none (after fix) | Unsupported reply | See above | Pass after fix | Router fallback and keyword matching |
