# E-Presso BI Analyst (starter)

> Replace this README as you build. Your final version should cover every section below.

## What this application does
_One paragraph for a manager, not a programmer._

## Live app
https://epreapp-bi-analyst-64pcdijgktkyhappv2pxhtr.streamlit.app/

The app may take a minute to wake up if nobody has opened it recently.

## How to use it
_Upload files, use filters, ask the assistant. Include the file names and sheets it expects._

## Data model

### Grain statements
| Table | Source file / sheet | One row = | Key column(s) | Rows | Contains revenue? |
|---|---|---|---|---|---|
| Sales | `Sales.txt` (comma-separated export of the `Sales` table in `Support_EX_B_Sales_1.accdb`) | one product's revenue at one store for one month (`Date` is the month-end date) | `Sales ID` (unique); also unique on `Store ID` + `Date` + `Product ID` | 25,200 = 21 stores × 60 months × 20 products | **Yes**, stored `Revenue` column |
| Products | `Products.txt` (export of `Products`) | one product | `Product ID` (P01–P20) | 20 | No |
| Categories | `Categories.txt` (export of `Categories`) | one product category | `Category ID` (C1–C5) | 5 | No |
| Stores | `Support_EX_B_Stores_1.csv` (**tab-separated**) | one store or sales channel location | `ID` (SH00–SH20) | 21 | No |
| Survey Results | `Support_EX_B_Survey_1.xlsx`, sheet `Survey Results`, header on row 3 | one store in one year | `Survey ID` (e.g. `SH01_25`) = `Store ID` + `_` + 2-digit year | 105 = 21 stores × 5 years | No |

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

## Metric definitions
_What "revenue" means here, and anything it does not mean._

## Assistant
_State exactly what you built (live language-model agent, or rules-based assistant). List each tool, what it calculates, and what the assistant is not allowed to do._

## Validation
_Link to or summarize your Power BI comparison, independent check, and $1,000 test._

## Limitations
_Revenue is not profit. What else can this app not tell a manager?_

## Files
| File | Purpose |
|---|---|
| `streamlit_app.py` | Screen layout and interaction |
| `analytics.py` | Metrics and analytical functions (no Streamlit code) |
| `agent.py` | Tool registry, dispatcher, and routers |
| `tests/` | Tests with hand-checkable answers |
| `requirements.txt` | Packages the hosted app needs |

## Run it
Hosted: deploy from this repository on share.streamlit.io with main file `streamlit_app.py`.

Locally (optional): `pip install -r requirements-dev.txt`, then `streamlit run streamlit_app.py`. Run tests with `pytest`.

## Secrets
Never commit API keys. Use Streamlit Secrets (see `.streamlit/secrets.toml.example`).
