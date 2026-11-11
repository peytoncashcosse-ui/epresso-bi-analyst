# CLAUDE.md — E-Presso AI BI Analyst

Context for Claude Code. I am a solo student (no teammate, even where the assignment says "partner").
Due **Sun Nov 15, 2026, 11:59 p.m. (Mountain)**. Full instructions live in `docs/assignment.txt` and
`docs/project_guide.txt`. **If they differ, the Project Guide controls.**

## Working rules for Claude
- Build one piece at a time, test it, then commit with a clear message. The commit history must show real iteration.
- Explain each function in plain English when you write it. I have to defend this code in an oral check.
- Calculations go in `analytics.py`, the agent in `agent.py`, and layout in `streamlit_app.py`.
- **Never hardcode** totals, chart values, expected answers, or filter lists (years, stores, categories, channels). Derive everything from the loaded data.
- Tie the cache to file contents (hash of uploaded bytes). If the cache isn't tied to the contents, the app shows stale numbers after an upload and fails the $1,000 test.
- Missing required column → show a plain message naming it, not a traceback. Blank values must not crash the app and must appear in the data-quality section.
- Never put an API key in code, the repo, or chat. Use Streamlit Secrets; `.streamlit/secrets.toml` goes in `.gitignore`.
- **Banned:** LangChain pandas agent, PandasAI, code interpreters, `eval()` / `exec()` on model output, model-written SQL or pandas, and any function that modifies loaded data.

## Data (put files in `data/`)
| Table | File | One row = | Key | Rows | Revenue? |
|---|---|---|---|---|---|
| Stores | `Support_EX_B_Stores_1.csv` (**tab-separated**) | one store | `ID` (SH00–SH20) | 21 | No |
| Survey Results | `Support_EX_B_Survey_1.xlsx`, sheet `Survey Results`, **header on row 3** (`header=2`) | store × year | `Survey ID` (e.g. `SH01_25`) | 105 | No |
| Sales | `Sales.txt` (CSV export of .accdb `Sales`) | store × month-end × product | `Sales ID` | 25,200 | **Yes, stored `Revenue` column** |
| Products | `Products.txt` | one product | `Product ID` | 20 | No |
| Categories | `Categories.txt` | one category | `Category ID` | 5 | No |

Verified 2026-11-10 (PowerShell + Access ODBC):
- Sales columns: `Sales ID, Date, Store ID, StoreYear, Category ID, Product ID, Revenue`. Date like `1/31/2025 0:00:00`.
- The .txt export matches the .accdb exactly: 25,200 rows, revenue sum 42,174,440, 0 null/non-numeric/≤0 revenue.
- No "Type Conversion Failure" table or "Sales by Category" query exists in this copy of the .accdb. Report that it was checked.
- Products has **no** category column → join to Categories via Sales.`Category ID`. Each product maps to exactly one category.
- Product name "Base Model" repeats (P11 Espresso Machines, P15 Accessories, P19 Frothers) → label products by ID + name, never name alone.
- Sales.`StoreYear` = `Store ID`_`yy` on every row → joins directly to Survey.`Survey ID`.
- Expected totals from source (for checking, never hardcode): by year 2025 7,181,750 / 2026 8,016,950 / 2027 8,824,720 / 2028 8,969,470 / 2029 9,181,550; Website 27,218,880; Brick & Mortar 14,955,560.

Findings so far (report these in the data-quality section):
- SH00 = **Website** (StoreType `Website`, Market `5-Global`); City, State and Postal code are blank, and it has no survey scores. Expected, not an error. Exclude it from satisfaction analysis; never treat blanks as 0.
- Channel = Stores.`StoreType` (`Website` vs `Brick & Mortar`).
- **Two stores in Orlando** (SH01, SH08). Group by store ID or by City+ID, never by City alone. Power BI's bar chart grouped by City, so compare against it during validation.
- Suspicious `Location` labels: SH07 Flushing NY = "Southwest"; Orlando stores = "South" and "East".
- SH11 phone is missing "(" (cosmetic).
- Survey `Year` is text `Y2025`..`Y2029`; convert to an int to join with year(Sales.Date). Satisfaction 0–5 (0.4–5.0), Interest 0–100 (62–99).
- Revenue is not profit. There is no cost data, so profitability questions must be declined with an explanation.

Power BI reference report (for validation): Revenue Analysis page (bar by City/Market/StoreType, line + column of Revenue by Date, Category slicer),
Survey Analysis page (scatter of Satisfaction vs Revenue by Survey ID, store table). I'll supply Power BI numbers for the validation table.

## Environment
- Python 3.12 in `.venv`. Run with `.\.venv\Scripts\python.exe -m pytest` / `-m streamlit run streamlit_app.py`.
- Headless app check: `streamlit.testing.v1.AppTest.from_file('streamlit_app.py').run()`.
- Push to GitHub after each finished step (Streamlit Cloud redeploys from `main`).
- `docs/` is git-ignored on purpose (local reference only). Data files in `data/` ARE committed.

## Progress log
- 2026-11-10: Data profiled; grain statements in README. Step 2–3 done: `analytics.read_epresso_table` /
  `build_model` / `total_revenue`, merge checks shown in app, data-quality section, per-table upload with
  defaults from `data/`, cache keyed on bytes (verified +$1,000 recalculates). Tests in `tests/test_model.py`.
  **Next: step 4, filters + ≥3 charts on the Dashboard tab.** Deployment status on Streamlit Cloud: unconfirmed.

## Build plan (Project Guide order)
1. Checkpoint 0: repo from `jmmcallister/epresso-starter` template, deployed on Streamlit Community Cloud.
2. Load all files, show a data profile, and write grain statements (table above → README).
3. Total revenue; reconcile with Power BI. Use the starter's `check_merge()` around **every** merge (rows + revenue before/after).
4. Filters (year, store, category, channel; lists derived from data) + ≥3 labeled charts; every KPI follows the filters.
5. Upload path that replaces the default data and recalculates with no code change.
6. Small hand-checkable unit tests on a tiny made-up table (`tests/`).
7. $1,000 test: write predictions first, then upload a modified copy without a restart, record results, restore.
8. ≥3 analytical functions using the **tool contract**: return `{tool, value, definition, scope, rows_used, caveats}`; explicit params validated against loaded values (unknown store → error result).
   Candidates: `get_total_revenue`, `get_revenue_by_channel`, `get_revenue_by_year`, `get_monthly_revenue`, `get_store_trend`, `get_category_performance`, `get_satisfaction_vs_revenue`, `get_data_quality_report`.
9. Dispatcher (tool name → function, runs it, logs it) + rules-based router (Option B).
10. Gemini function-calling router (Option A, free tier, key in Secrets). Fallback to rules-based on API error or quota.
    Chat UI: scope line first → **Findings / Interpretation / Next steps**; tool-call log (name, args, raw result) under each answer; ~15-question session limit; unsupported-question reply lists what it can answer; the model may only state numbers from tool results.
11. Five agent tests + one documented fix and retest; validation table; reflection (300–500 words); contribution statement (solo); README.
