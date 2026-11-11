# Power BI vs. Streamlit validation

Power BI values were read from the E-Presso Power BI report (Revenue Analysis page, no slicers applied) on 2026-11-11.
App values are from the live app with the supplied data loaded (Data and quality tab, and the Dashboard with no filters).

| Metric | Power BI result | App result | Match? / Explanation |
|---|---|---|---|
| Total revenue (five years, 2025–2029) | $42,174,440 | $42,174,440.00 | **Match** |
| Website revenue | $27,218,880 | $27,218,880.00 | **Match**. Channel = Stores.`StoreType`; the website is store SH00. |
| Brick-and-mortar revenue | $14,955,560 | $14,955,560.00 | **Match**. The two channels sum to the total. |
| Revenue by year | 2025–2029 all match the app | 2025 $7,181,750.00 · 2026 $8,016,950.00 · 2027 $8,824,720.00 · 2028 $8,969,470.00 · 2029 $9,181,550.00 | **Match** for all five years |
| Monthly revenue pattern | Line chart drilled to year-month: same values for the months checked, and the same shape (February low, November–December peak each year) | Jan 2025 $548,340.00 · Feb 2025 $275,510.00 (lowest month) · Jun 2027 $562,220.00 · Nov 2029 $1,125,950.00 · Dec 2029 $2,365,730.00 (highest month). Every year peaks in Nov–Dec; December alone is 25.6% of all revenue. | **Match** |
| Additional measure: revenue by category (Espresso Machines) | $27,093,220 | $27,093,220.00 | **Match**. Category comes from Sales.`Category ID` because Products has no category column. |

## Why the numbers agree
Every join from Sales to a lookup table (Products, Categories, Stores) is many-to-one. The merge checks on the app's
**Data and quality** tab show 25,200 rows and $42,174,440.00 before and after each join, so no revenue was duplicated
or dropped. Survey data is not joined to individual sales rows, so it cannot inflate revenue.

## Known difference in presentation (not a numeric discrepancy)
Power BI's revenue bar chart groups by **City**. Orlando has two stores (SH01, SH08), so Power BI shows a single combined
Orlando bar. The app groups by store (ID + city) and shows them separately: SH01 Orlando $727,080.00 and SH08 Orlando
$366,190.00, which add to $1,093,270.00 for Orlando combined.

## Independent check
The totals were recalculated outside the app with no use of `analytics.py`, by summing the raw files:

1. **PowerShell** (`Import-Csv data\Sales.txt`, then summing `Revenue`): 25,200 rows, $42,174,440.00. Joined to the
   Stores file's `StoreType`: Website $27,218,880.00, Brick & Mortar $14,955,560.00. Website, 2028 only: 240 rows,
   $6,339,640.00, matching the app's dashboard and the assistant's answer to the same question.
2. **Access database**, queried directly over ODBC (`SELECT COUNT(*), SUM(Revenue) FROM Sales`): 25,200 rows,
   42,174,440. This confirms the `Sales.txt` export is complete.
3. **`validation/make_plus1000.py`** sums the raw files with pandas for the $1,000 test. Its "before" column matches
   the app for every measure.
