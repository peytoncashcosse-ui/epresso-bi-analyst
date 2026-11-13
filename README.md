# E-Presso BI Analyst

## What this application does
E-Presso BI Analyst is a web dashboard for E-Presso managers. It loads the company's sales, product, store and
customer-survey data and shows total revenue, how the website compares with physical stores, how each year, month,
store and product category performed, and how customer satisfaction lines up with revenue. Every number is calculated
from whatever data is currently loaded, so uploading an updated file updates the whole app. An analytical assistant
answers business questions in plain English. It calculates its answers with the same functions as the dashboard,
shows exactly which calculation it ran, and says when the data cannot support a conclusion (for example, anything
about profit).

## Live app
https://epreapp-bi-analyst-64pcdijgktkyhappv2pxhtr.streamlit.app/

The app may take a minute to wake up if nobody has opened it recently.

## How to use it
1. **Data and quality tab.** Shows total revenue, where each table came from, the merge checks, data-quality findings
   (blank values by row, duplicates, unmatched IDs) and a profile of every table.
2. **Dashboard tab.** Four filters: Year, Store, Category and Channel. Leave one empty to include everything. The
   choices are read from the loaded data. Every KPI and chart follows the filters, and a **Scope** line says what is
   included. Charts: annual revenue by channel, monthly revenue by channel, revenue by store (ID + city, so the two
   Orlando stores stay separate) and revenue by category. "Numbers behind the charts" shows the totals as tables.
3. **Assistant tab.** Type a business question. Each answer shows **Scope → Findings → Interpretation → Next steps**,
   says which assistant answered, and has a **Tool-call log** with the function, its arguments and the raw result.
   "What can I ask?" lists the supported questions. There is a limit of 15 questions per session.
4. **Uploading updated data (sidebar).** The supplied files in `data/` load by default. Upload a file into a table's
   box to replace that table; everything recalculates with no restart. Remove the upload (×) to go back to the
   default. Expected files (names can differ; **column names must match**):

| Table | Default file | Format | Required columns |
|---|---|---|---|
| Sales | `data/Sales.txt` | CSV/TXT (export of the Access `Sales` table) | `Sales ID, Date, Store ID, StoreYear, Category ID, Product ID, Revenue` |
| Products | `data/Products.txt` | CSV/TXT | `Product ID, Product` |
| Categories | `data/Categories.txt` | CSV/TXT | `Category ID, Category` |
| Stores | `data/Support_EX_B_Stores_1.csv` | tab- or comma-separated | `ID, City, State, StoreType, Market, Location` |
| Survey Results | `data/Support_EX_B_Survey_1.xlsx` | Excel, sheet `Survey Results`, header on row 3 | `Survey ID, Store ID, Year, Satisfaction, Interest` |

If a required column is missing, the app shows a plain message naming it. Blank values do not crash the app; they are
listed in the data-quality section and are never treated as 0.

## Data model

### Grain statements
| Table | Source file / sheet | One row = | Key column(s) | Rows | Contains revenue? |
|---|---|---|---|---|---|
| Sales | `Sales.txt` (comma-separated export of the `Sales` table in `Support_EX_B_Sales_1.accdb`) | one product's revenue at one store for one month (`Date` is the month-end date) | `Sales ID` (unique); also unique on `Store ID` + `Date` + `Product ID` | 25,200 = 21 stores × 60 months × 20 products | **Yes**, stored `Revenue` column |
| Products | `Products.txt` (export of `Products`) | one product | `Product ID` (P01–P20) | 20 | No |
| Categories | `Categories.txt` (export of `Categories`) | one product category | `Category ID` (C1–C5) | 5 | No |
| Stores | `Support_EX_B_Stores_1.csv` (**tab-separated**) | one store or sales channel location | `ID` (SH00–SH20) | 21 | No |
| Survey Results | `Support_EX_B_Survey_1.xlsx`, sheet `Survey Results`, header on row 3 | one store in one year | `Survey ID` (e.g. `SH01_25`) = `Store ID` + `_` + 2-digit year | 105 = 21 stores × 5 years | No |

The `.txt` exports were checked against the Access database over ODBC: 25,200 rows and $42,174,440 in both. The
database has no "Type Conversion Failure" table, so no revenue values failed to import.

### Relationships
- Sales.`Product ID` → Products.`Product ID` (many-to-one)
- Sales.`Category ID` → Categories.`Category ID` (many-to-one). Products has no category column, so this is the only path to a category. Every product maps to exactly one category in Sales.
- Sales.`Store ID` → Stores.`ID` (many-to-one). Channel = Stores.`StoreType`.
- Sales.`StoreYear` → Survey.`Survey ID` (many-to-one). `StoreYear` always equals `Store ID` + `_` + the 2-digit year of `Date` (checked on all 25,200 rows).

All joins are many-to-one from Sales, so none should change the row count or the revenue sum. The app runs `check_merge()` around every join and shows the result on the **Data and quality** tab. Results on the supplied data:

| Merge | Key | Rows before | Rows after | Revenue sum before | Revenue sum after | Explanation |
|---|---|---|---|---|---|---|
| Sales + Products | `Product ID` | 25,200 | 25,200 | $42,174,440.00 | $42,174,440.00 | One row per product in Products, so no duplication |
| + Categories | `Category ID` | 25,200 | 25,200 | $42,174,440.00 | $42,174,440.00 | One row per category |
| + Stores | `Store ID` = Stores.`ID` | 25,200 | 25,200 | $42,174,440.00 | $42,174,440.00 | One row per store |

Survey Results is **not** joined to the sales rows. It is one row per store-year, so it is compared with revenue summed to store-year, never repeated onto each sales row.

If an updated lookup table repeats a key, the app keeps the first row for that key and reports it, so the join cannot copy sales rows and inflate revenue.

### Data-quality findings on the supplied data
- **SH00 is the website** (StoreType `Website`, Market `5-Global`). Its City, State and PostalCode are blank and it has no
  survey scores. This is expected, not an error. It is left out of satisfaction analysis, and its blanks are never treated as 0.
- **Two stores are in Orlando** (SH01, SH08), so the app groups by store ID, never by city alone. Power BI's bar chart
  grouped by City and showed one combined Orlando bar.
- **"Base Model"** is the name of three different products (P11 Espresso Machines, P15 Accessories, P19 Frothers), so
  products are labeled by ID + name.
- Survey `Year` is text (`Y2025`) and is converted to a number. Satisfaction runs 0.4–5.0 and Interest 62–99.
- No blank, non-numeric or negative revenue; no duplicate Sales IDs; every Sales key matches a lookup table.

## Metric definitions
- **Revenue** = the sum of the stored `Revenue` column on Sales rows. It is **not profit**: the data has no costs,
  expenses or margins.
- **Channel** = Stores.`StoreType`: `Website` (SH00) or `Brick & Mortar` (SH01–SH20).
- **Share of total** = group revenue ÷ total revenue *in the same scope* × 100 (for example, a channel's share of
  that year's revenue).
- **Year-over-year change** = (this year − prior year) ÷ prior year × 100.
- **Growth between two years** = (end-year revenue − start-year revenue) ÷ start-year revenue × 100. It uses the two
  end years only.
- **Monthly share** = month revenue ÷ total revenue of the same year (or of all years combined) × 100.
- **Satisfaction vs revenue** = Pearson correlation between a store's survey Satisfaction and its total revenue in the
  same year, one point per store-year (revenue is summed to store-year first). It measures association, not causation.

## Assistant
**What was built:** a **language-model agent (Option A)** using Google Gemini function calling, with a **rules-based
assistant (Option B)** as an automatic fallback and as a selectable mode ("Use the rules-based assistant only").

**How an answer is produced**
1. The question goes to Gemini (`gemini-3.5-flash-lite` by default, chosen by timing every available model on the
   five required tests: about 2 s per answer) along with descriptions of eight approved tools. Every
   parameter is limited to values in the loaded data (real years, stores, categories and channels).
2. When Gemini requests a tool, **our dispatcher** (`agent.run_tool`) checks the name and arguments, runs the
   function on the loaded data and logs the call. The SDK's automatic function calling is turned off.
3. The tool result goes back to Gemini, which writes Findings, Interpretation and Next steps.
4. **Number check:** every number in Gemini's text is compared with the tool results (rounding and "about 70%" style
   approximations are allowed). If any number does not match, the findings are replaced by ones written directly from
   the tool results, and the answer says so.
5. **Fallback:** if there is no API key, an API error, a quota error, an overload that outlasts two retries and a
   switch to another model, or no answer within 60 seconds, the rules-based assistant answers and the reason is shown.

**The rules-based assistant** reads years, stores, categories and channels from the question (only values that exist
in the loaded data), picks a tool by keyword, and writes the answer from the tool result. It declines profit and
forecasting questions without running a tool, and gives evidence but **no recommendation** for judgment questions
("Should we close Chicago?").

**Tools** (all in `analytics.py`; each returns `{tool, value, definition, scope, rows_used, caveats}`)

| Tool | Calculates |
|---|---|
| `get_total_revenue(year, store, category, channel)` | Revenue for any scope |
| `get_revenue_by_channel(year, store, category)` | Website vs Brick & Mortar revenue and shares |
| `get_revenue_by_year(store, category, channel)` | Revenue per year and year-over-year change |
| `get_growth(by, start_year, end_year, category, channel)` | Stores, channels or categories ranked by change between two years; names the largest rise and decline, or says nothing declined |
| `get_monthly_revenue(year, store, category, channel)` | Revenue per month and its share of the period |
| `get_category_performance(year, store, channel)` | Categories ranked by revenue with shares |
| `get_satisfaction_vs_revenue(year)` | Correlation of Satisfaction and Interest with revenue (store-year level) |
| `get_data_quality_report()` | Blanks, duplicates, unmatched keys, merge checks |

An unknown or ambiguous value returns an error result that lists the valid values. For example, "Orlando" matches two
stores, so the tool asks for a store ID rather than guessing.

**The assistant is not allowed to:** run model-written code or SQL (no `eval`/`exec`, no pandas agents or code
interpreters); change the loaded data; state a number that no tool calculated; claim that revenue shows profitability;
present correlation as causation; or make a recommendation the data cannot support.

**Scope:** every answer starts with what it covers and names the Sales file in use. The dashboard filters are **not**
applied to the assistant, and the answer says so.

**Status:** all five required tests pass on the live app in **both** modes. In Gemini mode (2026-11-13, after switching to
`gemini-3.5-flash-lite`), every answer passed the number check within a few seconds. In rules-based mode (2026-11-12),
the tests were run while the earlier default model was overloaded. See `validation/agent_tests.md`.

## Validation
- **Power BI comparison:** all six measures match: total ($42,174,440), Website ($27,218,880), Brick & Mortar
  ($14,955,560), revenue for each year, monthly values and pattern, and Espresso Machines ($27,093,220).
  See `validation/validation_table.md`.
- **Independent check:** the raw files were summed outside the app with PowerShell, and the Access database was queried
  over ODBC. Both give the same totals; website revenue in 2028 is $6,339,640 in both.
- **$1,000 test:** row S0120270601 (SH01 Orlando, June 2027) was changed from 260 to 1,260. The predictions were
  committed before the upload. On upload the total rose by exactly $1,000 to $42,175,440, only the predicted charts
  and filters changed, there was no code change or restart, and the original was restored. See
  `validation/modified_data_test.md`.
- **Assistant tests:** five required tests plus four documented fix-and-retest cycles, in `validation/agent_tests.md`,
  with screenshots in `validation/screenshots/`.
- **Automated tests:** 70 `pytest` tests on tiny hand-checkable tables (`tests/`), covering loading, joins, filters,
  every tool, the router, the number check and the fallbacks. The Gemini client is replaced by a scripted fake, so the
  tests run offline.

## Limitations
- **Revenue is not profit.** There is no cost data, so the app cannot say which store, product or channel is
  profitable, or whether closing a store makes financial sense.
- **Correlation is not causation.** The satisfaction analysis has 100 store-years and one score per store per year.
  Store size, location and market may drive both satisfaction and revenue.
- **The website has no survey scores**, so satisfaction conclusions apply to physical stores only.
- **The data explains *what* happened, not *why*.** The decline of every physical store (−45.8% for Brick & Mortar,
  2025–2029) has no explanation in the data: there are no prices, traffic, staffing, competition or marketing data.
- **Growth compares two years only;** use revenue by year to see what happened in between.
- **No forecasting.**
- **The language model depends on Google's free tier.** It can be slow or unavailable, in which case the rules-based
  assistant answers and says so.

## Files
| File | Purpose |
|---|---|
| `streamlit_app.py` | Screen layout and interaction |
| `analytics.py` | Loading, joins, metrics and the eight analytical tools (no Streamlit code) |
| `agent.py` | Tool registry, dispatcher, rules router, Gemini agent, number check |
| `tests/` | Tests with hand-checkable answers |
| `data/` | The supplied E-Presso files (loaded by default) |
| `validation/` | Validation table, $1,000 test, agent tests, screenshots, and `make_plus1000.py` |
| `requirements.txt` | Packages the hosted app needs |

## Run it
Hosted: deploy from this repository on share.streamlit.io with main file `streamlit_app.py`.

Locally: `pip install -r requirements-dev.txt`, then `streamlit run streamlit_app.py`. Run the tests with `pytest`.

## Secrets
Never commit API keys. Put `GEMINI_API_KEY` in Streamlit Secrets (App settings → Secrets), or for local work in
`.streamlit/secrets.toml`, which is git-ignored. See `.streamlit/secrets.toml.example`. An optional `GEMINI_MODEL`
secret changes the model without a code change.

## Contribution
Solo project (no Power BI Buddy teammate). One student built, tested, validated and documented every part of the
application, using Claude Code as the AI development assistant. See `validation/reflection.md` for the reflection and
contribution statement.
