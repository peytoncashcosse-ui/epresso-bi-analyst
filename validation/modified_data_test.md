# $1,000 modified-data test

**Predictions written and committed before the modified file was uploaded.**
The git commit containing this file's predictions is earlier than the commit recording the results.

## The change

| Item | Entry |
|---|---|
| Table and row identifier | Sales, `Sales ID` = `S0120270601` |
| Date / store / channel of the row | 2027-06-30 (June 2027) / SH01 Orlando, FL / Brick & Mortar |
| Category / product | C1 Beans / P01 French Roast |
| Original value | Revenue = 260.00 |
| Modified value | Revenue = 1,260.00 (stored column, so exactly +1,000; nothing else edited) |
| Modified file | `validation/Sales_plus1000.txt`, made by `validation/make_plus1000.py` (a byte-for-byte copy of `data/Sales.txt` with that one line changed; the script stops if the line is not found exactly once) |
| How predictions were made | `make_plus1000.py` sums the raw files with pandas directly. It does not use the app's `analytics.py`, so it is an independent calculation. |

## Predictions

| Measure (where to look in the app) | Before | Predicted after | Predicted change | Actual after | Match? |
|---|---|---|---|---|---|
| Total revenue (Data tab KPI; Dashboard KPI, no filters) | $42,174,440.00 | $42,175,440.00 | +1,000 | | |
| Year 2027 (Dashboard: numbers expander, revenue by year) | $8,824,720.00 | $8,825,720.00 | +1,000 | | |
| Year 2026 | $8,016,950.00 | $8,016,950.00 | 0 | | |
| June 2027, all channels (numbers expander, revenue by month) | $562,220.00 | $563,220.00 | +1,000 | | |
| June 2027, Brick & Mortar (monthly chart, hover the Brick & Mortar point for 2027-06) | $185,900.00 | $186,900.00 | +1,000 | | |
| May 2027 | $500,370.00 | $500,370.00 | 0 | | |
| Brick & Mortar revenue (Dashboard KPI) | $14,955,560.00 | $14,956,560.00 | +1,000 | | |
| Website revenue (Dashboard KPI) | $27,218,880.00 | $27,218,880.00 | 0 | | |
| Store SH01 Orlando (revenue-by-store chart) | $727,080.00 | $728,080.00 | +1,000 | | |
| Store SH08 Orlando (the other Orlando store) | $366,190.00 | $366,190.00 | 0 | | |
| Category Beans (revenue-by-category chart) | $5,672,720.00 | $5,673,720.00 | +1,000 | | |
| Category Syrups | $2,712,040.00 | $2,712,040.00 | 0 | | |
| Filters: Year 2027 + Store SH01 Orlando + Category Beans (+ Channel Brick & Mortar) | $18,400.00 | $19,400.00 | +1,000 | | |
| Filters: Year 2027 + Channel Website | $5,931,010.00 | $5,931,010.00 | 0 | | |

**Charts that should change:** the June 2027 Brick & Mortar point on the monthly chart, the 2027 Brick & Mortar bar on the
annual chart, the SH01 Orlando bar on the store chart, and the Beans bar on the category chart. Every other point should be unchanged.

## Procedure
1. Open the live app (already running; no restart).
2. In the sidebar, upload `validation/Sales_plus1000.txt` into the **Sales** box. The Data tab's source row should change to "Uploaded: Sales_plus1000.txt".
3. Record the actual values above. Ask the assistant the same revenue question before and after (once the assistant has revenue tools).
4. Restore: remove the upload (the × next to the file). The app goes back to `data/Sales.txt`, and the total should return to $42,174,440.00.

## Results

Run on the live app on 2026-11-10 by uploading `Sales_plus1000.txt` into the Sales box, with no code change and no restart.
Every measure in the prediction table matched its predicted value: the +1,000 rows rose by exactly 1,000 and the rows
predicted not to change stayed the same.

| Item | Entry |
|---|---|
| Actual total revenue after change | $42,175,440.00 (as predicted, +$1,000.00) |
| Chart that should change, and what you saw | The June 2027 Brick & Mortar point (monthly), 2027 Brick & Mortar bar (annual), SH01 Orlando bar (store) and Beans bar (category) rose by $1,000. Website, SH08 Orlando and the other categories did not change. |
| Filter combinations checked (changed / unchanged) | 2027 + SH01 Orlando + Beans: $18,400 → $19,400 (changed, as predicted). 2027 + Website: $5,931,010 (unchanged, as predicted). |
| Code changes required? | No |
| Restart required? | No. The cache is keyed on the uploaded file's bytes, so the new file was recalculated immediately. |
| Original data restored? | Yes. Removing the upload returned the app to `data/Sales.txt`, with a total of $42,174,440.00. `data/Sales.txt` itself was never edited. |

The same check is automated in `tests/test_model.py::test_adding_1000_to_one_row_adds_exactly_1000`.
The assistant before/after question is still to do, once the assistant has revenue tools (agent Test 5).
