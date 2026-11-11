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

## Required tests (to be completed)

| Test | Question asked | Function(s) used | Expected result / behavior | Actual result | Pass / Fail | Revision made |
|---|---|---|---|---|---|---|
| 1. Numerical calculation | | | | | | |
| 2. Numerical comparison | | | | | | |
| 3. Missing information | | | | | | |
| 4. Analytical judgment | | | | | | |
| 5. Updated data | | | | | | |
| Extra: fix and retest | "What is the weather in Denver?" | none (after fix) | Unsupported reply | See above | Pass after fix | Router fallback and keyword matching |
