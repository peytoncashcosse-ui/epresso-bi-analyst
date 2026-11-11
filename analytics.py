"""Business logic. Keep Streamlit code OUT of this file so every function can be
tested on its own and reused by the assistant."""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field

import pandas as pd

EXCEL_EXT = ('.xlsx', '.xlsm', '.xls')
TEXT_EXT = ('.csv', '.txt', '.tsv')


# ---------------------------------------------------------------- loading
def excel_sheet_names(file_bytes: bytes) -> list[str]:
    return pd.ExcelFile(io.BytesIO(file_bytes)).sheet_names


def load_table(file_bytes: bytes, filename: str, sheet_name=0) -> pd.DataFrame:
    """Read an uploaded CSV / TXT / TSV / Excel file into a DataFrame."""
    name = filename.lower()
    buffer = io.BytesIO(file_bytes)
    if name.endswith(EXCEL_EXT):
        return pd.read_excel(buffer, sheet_name=sheet_name)
    if name.endswith(TEXT_EXT):
        return pd.read_csv(buffer, sep=None, engine='python')  # sniffs the delimiter
    raise ValueError(f'Unsupported file type: {filename}')


def profile_table(df: pd.DataFrame) -> dict:
    """Basic profile: size, duplicates, missing values, data types."""
    missing = df.isna().sum()
    return {
        'rows': len(df),
        'columns': df.shape[1],
        'duplicate_rows': int(df.duplicated().sum()),
        'missing': pd.DataFrame({
            'column': missing.index,
            'missing': missing.values,
            'pct_missing': (missing.values / max(len(df), 1) * 100).round(2),
        }),
        'dtypes': pd.DataFrame({'column': df.columns, 'dtype': df.dtypes.astype(str).values}),
    }


# ------------------------------------------------------- E-Presso tables
# What each source table must look like. File names are only the DEFAULTS in
# data/; an uploaded file can have any name. Column names must match exactly.
TABLE_SPECS = {
    'sales': {
        'label': 'Sales', 'default_file': 'Sales.txt',
        'required': ['Sales ID', 'Date', 'Store ID', 'StoreYear', 'Category ID',
                     'Product ID', 'Revenue'],
    },
    'products': {
        'label': 'Products', 'default_file': 'Products.txt',
        'required': ['Product ID', 'Product'],
    },
    'categories': {
        'label': 'Categories', 'default_file': 'Categories.txt',
        'required': ['Category ID', 'Category'],
    },
    'stores': {
        'label': 'Stores', 'default_file': 'Support_EX_B_Stores_1.csv',
        'required': ['ID', 'City', 'State', 'StoreType', 'Market', 'Location'],
    },
    'survey': {
        'label': 'Survey Results', 'default_file': 'Support_EX_B_Survey_1.xlsx',
        'sheet': 'Survey Results', 'header': 2,  # title rows above the header
        'required': ['Survey ID', 'Store ID', 'Year', 'Satisfaction', 'Interest'],
    },
}


class DataError(ValueError):
    """A problem with an input file, worded for a manager rather than a programmer."""


def _sniff_delimiter(file_bytes: bytes) -> str:
    """Look at the header line: tab-separated if it contains a tab, else comma."""
    first_line = file_bytes.split(b'\n', 1)[0]
    return '\t' if b'\t' in first_line else ','


def read_epresso_table(table: str, file_bytes: bytes, filename: str) -> pd.DataFrame:
    """Read one E-Presso table from raw file bytes and check its required columns.

    Text files are read with every column as text, so IDs like 'P01' and postal
    codes keep their exact form; numbers are converted later on purpose.
    Raises DataError with a plain message if the file can't be used."""
    spec = TABLE_SPECS[table]
    label, name = spec['label'], filename.lower()
    buffer = io.BytesIO(file_bytes)
    try:
        if name.endswith(EXCEL_EXT):
            df = pd.read_excel(buffer, sheet_name=spec.get('sheet', 0),
                               header=spec.get('header', 0))
        elif name.endswith(TEXT_EXT):
            df = pd.read_csv(buffer, sep=_sniff_delimiter(file_bytes), dtype=str,
                             encoding='utf-8-sig')
        else:
            raise DataError(f'{label}: "{filename}" is not a CSV, TXT or Excel file.')
    except DataError:
        raise
    except Exception as exc:  # unreadable file, missing sheet, bad encoding, ...
        raise DataError(f'{label}: could not read "{filename}" ({exc}).') from exc

    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how='all')  # fully blank rows, e.g. trailing Excel rows
    for col in df.select_dtypes(include=['object', 'string']).columns:
        df[col] = df[col].str.strip()

    missing = [c for c in spec['required'] if c not in df.columns]
    if missing:
        raise DataError(f'{label}: "{filename}" is missing required column(s) '
                        f'{missing}. Columns found: {list(df.columns)}.')
    return df


def prepare_sales(sales: pd.DataFrame) -> pd.DataFrame:
    """Turn Sales text columns into real types and add Year / Month columns.

    Date: the export looks like '1/31/2025 0:00:00'; anything in another format
    is parsed flexibly. Revenue: '$' and ',' are removed, then converted to a
    number. Values that can't be converted become blank (NaN) rather than 0, so
    they are excluded from sums and reported in the data-quality section."""
    out = sales.copy()
    raw_date = out['Date']
    dates = pd.to_datetime(raw_date, format='%m/%d/%Y %H:%M:%S', errors='coerce')
    retry = dates.isna() & raw_date.notna()
    if retry.any():
        dates.loc[retry] = pd.to_datetime(raw_date[retry], format='mixed', errors='coerce')
    out['Date'] = dates
    out['Revenue'] = pd.to_numeric(
        out['Revenue'].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce')
    out['Year'] = out['Date'].dt.year.astype('Int64')
    out['Month'] = out['Date'].dt.month.astype('Int64')
    out['MonthStart'] = out['Date'].dt.to_period('M').dt.to_timestamp()
    return out


def prepare_survey(survey: pd.DataFrame) -> pd.DataFrame:
    """Survey Year is text like 'Y2025'; pull out the 4-digit year as a number.
    Satisfaction and Interest become numbers; blanks stay blank, never 0."""
    out = survey.copy()
    out['Year'] = pd.to_numeric(out['Year'].astype(str).str.extract(r'(\d{4})')[0],
                                errors='coerce').astype('Int64')
    for col in ('Satisfaction', 'Interest'):
        out[col] = pd.to_numeric(out[col], errors='coerce')
    return out


def blank_report(df: pd.DataFrame, key_col: str) -> list[dict]:
    """For every column with blanks: how many, and which rows (by key) have them."""
    report = []
    for col in df.columns:
        mask = df[col].isna()
        if mask.any():
            keys = df.loc[mask, key_col].astype(str).tolist() if key_col in df else []
            report.append({'column': col, 'blank_count': int(mask.sum()),
                           'rows (by key)': ', '.join(keys[:25]) + (' ...' if len(keys) > 25 else '')})
    return report


def _dedupe_dimension(dim: pd.DataFrame, key: str, label: str, issues: list) -> pd.DataFrame:
    """A lookup table must have one row per key, or a join would copy sales rows and
    inflate revenue. If a key repeats, keep its first row and report it."""
    dupes = dim[key][dim[key].duplicated()].dropna().unique().tolist()
    if dupes:
        issues.append(f'{label}: key {key} repeats for {dupes}; only the first row of each '
                      'was used so revenue is not duplicated.')
        dim = dim.drop_duplicates(subset=key, keep='first')
    return dim


def build_model(tables: dict[str, pd.DataFrame]) -> dict:
    """Combine the raw tables into one sales fact table at the Sales grain
    (store x month x product) and record a merge check around every join.

    Every join is many-to-one from Sales to a lookup table, so the row count and
    revenue total must not change. Survey data is NOT joined here: it is one row
    per store-year, and is compared with revenue at that grain in its own function.
    Returns {'fact', 'survey', 'merge_checks', 'issues'}."""
    issues: list[str] = []
    sales = prepare_sales(tables['sales'])
    survey = prepare_survey(tables['survey'])

    products = _dedupe_dimension(tables['products'][['Product ID', 'Product']],
                                 'Product ID', 'Products', issues)
    categories = _dedupe_dimension(tables['categories'][['Category ID', 'Category']],
                                   'Category ID', 'Categories', issues)
    stores = tables['stores'].rename(columns={'ID': 'Store ID', 'StoreType': 'Channel'})
    stores = _dedupe_dimension(
        stores[['Store ID', 'City', 'State', 'Channel', 'Market', 'Location']],
        'Store ID', 'Stores', issues)

    checks = []
    fact = sales
    for label, dim, key in (('Sales + Products', products, 'Product ID'),
                            ('+ Categories', categories, 'Category ID'),
                            ('+ Stores', stores, 'Store ID')):
        fact, report = check_merge(fact, dim, on=key, value_col='Revenue', how='left')
        checks.append({'merge': label, 'key': key, **report})
        if report['changed']:
            issues.append(f'{label}: {report["warning"]}')

    # Sales rows whose key is not in the lookup table (they keep revenue but no label).
    for key, col, label in (('Product ID', 'Product', 'Products'),
                            ('Category ID', 'Category', 'Categories'),
                            ('Store ID', 'Channel', 'Stores')):
        orphan = fact[col].isna() & fact[key].notna()
        if orphan.any():
            ids = sorted(fact.loc[orphan, key].astype(str).unique())
            issues.append(f'{int(orphan.sum())} Sales row(s) have a {key} not found in '
                          f'{label}: {ids}.')

    # Each product should belong to exactly one category in Sales.
    cats_per_product = sales.dropna(subset=['Product ID', 'Category ID']) \
        .groupby('Product ID')['Category ID'].nunique()
    multi = cats_per_product[cats_per_product > 1].index.tolist()
    if multi:
        issues.append(f'Product(s) {multi} appear under more than one Category ID in Sales.')

    n_bad_date = int(fact['Date'].isna().sum())
    if n_bad_date:
        issues.append(f'{n_bad_date} Sales row(s) have a blank or unreadable Date; they count '
                      'in total revenue but not in any year or month.')
    n_bad_rev = int(fact['Revenue'].isna().sum())
    if n_bad_rev:
        issues.append(f'{n_bad_rev} Sales row(s) have a blank or non-numeric Revenue and are '
                      'excluded from every revenue sum.')
    n_neg = int((fact['Revenue'] < 0).sum())
    if n_neg:
        issues.append(f'{n_neg} Sales row(s) have negative Revenue (kept as-is).')
    n_dup_id = int(sales['Sales ID'].duplicated().sum())
    if n_dup_id:
        issues.append(f'{n_dup_id} Sales row(s) repeat a Sales ID that appears earlier.')

    # Label products by ID + name: some names (e.g. "Base Model") repeat across IDs.
    fact['Product Label'] = fact['Product ID'].astype(str) + ' ' + fact['Product'].fillna('(unknown)')
    # Label stores by ID + city: two stores share a city (Orlando), and the website
    # has no city, so it falls back to its channel name.
    place = fact['City'].fillna(fact['Channel']).fillna('(unknown store)')
    fact['Store Label'] = fact['Store ID'].astype(str) + ' ' + place
    # A blank channel or category gets an explicit label so it can still be filtered.
    fact['Channel'] = fact['Channel'].fillna('(missing)')
    fact['Category'] = fact['Category'].fillna('(missing)')
    return {'fact': fact, 'survey': survey, 'merge_checks': checks, 'issues': issues,
            'tables': tables}


def total_revenue(fact: pd.DataFrame) -> float:
    """Sum of the stored Revenue column over the rows given (blanks are skipped)."""
    return float(fact['Revenue'].sum())


# ----------------------------------------------------------- dashboard
FILTER_COLUMNS = {'Year': 'Year', 'Store': 'Store Label', 'Category': 'Category',
                  'Channel': 'Channel'}


def filter_options(fact: pd.DataFrame) -> dict[str, list]:
    """The choices for each dashboard filter, read from the loaded data (never typed
    in), so a new year, store or category shows up automatically."""
    return {name: sorted(fact[col].dropna().unique().tolist())
            for name, col in FILTER_COLUMNS.items()}


def apply_filters(fact: pd.DataFrame, selections: dict[str, list]) -> pd.DataFrame:
    """Keep only rows matching every filter. An empty selection means 'all'."""
    out = fact
    for name, chosen in selections.items():
        if chosen:
            out = out[out[FILTER_COLUMNS[name]].isin(chosen)]
    return out


def describe_scope(selections: dict[str, list]) -> str:
    """Plain-English scope line, e.g. 'Year: 2027 · Store: all · ...'."""
    parts = []
    for name in FILTER_COLUMNS:
        chosen = selections.get(name) or []
        parts.append(f'{name}: ' + (', '.join(map(str, chosen)) if chosen else 'all'))
    return ' · '.join(parts)


def revenue_by(fact: pd.DataFrame, *cols: str) -> pd.DataFrame:
    """Revenue summed by one or more columns, as a tidy table for charts."""
    return fact.groupby(list(cols), dropna=False)['Revenue'].sum().reset_index()


# ---------------------------------------------------------- tool contract
@dataclass
class ToolResult:
    """Every analytical function returns this. The assistant may only narrate it.
    Keep `value` to plain Python types (numbers, strings, dicts, lists)."""
    tool: str
    value: object
    definition: str
    scope: dict
    rows_used: int
    caveats: list = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _error(tool: str, message: str, scope: dict | None = None) -> ToolResult:
    return ToolResult(tool=tool, value=None, definition='', scope=scope or {},
                      rows_used=0, caveats=[], error=message)


PROFIT_CAVEAT = ('Revenue is not profit: the data has no costs, expenses or margins, '
                 'so it cannot show which store, product or channel is profitable.')
GROWTH_DIMENSIONS = {'store': 'Store Label', 'channel': 'Channel', 'category': 'Category'}
MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct',
               'Nov', 'Dec']


def _is_all(value) -> bool:
    """None, '', 'all' or 'any' all mean 'do not filter on this'."""
    return value is None or str(value).strip().lower() in ('', 'all', 'any', 'none')


def _match(fact: pd.DataFrame, columns: list[str], wanted, label: str):
    """Find the requested value among the values in the LOADED data, ignoring case.
    Tries each column in turn (e.g. a category can be given by name or by ID) and
    returns (value_in_first_column, None) or (None, error message listing valid values)."""
    w = str(wanted).strip().lower()
    for col in columns:
        rows = fact.loc[fact[col].astype(str).str.lower() == w, columns[0]].dropna().unique()
        if len(rows) == 1:
            return rows[0], None
    valid = sorted(map(str, fact[columns[0]].dropna().unique()))
    return None, f'Unknown {label} "{wanted}". Values in the loaded data: {valid}.'


def _match_store(fact: pd.DataFrame, wanted):
    """A store can be given as its ID ('SH01'), its label ('SH01 Orlando') or its city,
    but a city that has more than one store (Orlando) is an error, not a guess."""
    stores = fact[['Store ID', 'Store Label', 'City']].drop_duplicates()
    w = str(wanted).strip().lower()
    for col in ('Store ID', 'Store Label'):
        hit = stores[stores[col].astype(str).str.lower() == w]
        if len(hit) == 1:
            return hit['Store Label'].iloc[0], None
    hit = stores[stores['City'].fillna('').str.lower() == w]
    if len(hit) == 1:
        return hit['Store Label'].iloc[0], None
    if len(hit) > 1:
        return None, (f'"{wanted}" matches more than one store: {sorted(hit["Store Label"])}. '
                      'Name one store by its ID.')
    return None, f'Unknown store "{wanted}". Stores in the loaded data: {sorted(stores["Store Label"])}.'


def _subset(fact: pd.DataFrame, year=None, store=None, category=None, channel=None):
    """Check every parameter against the loaded data, then keep the matching rows.
    Returns (rows, scope, error). Scope says in words what the numbers cover."""
    scope = {'year': 'All', 'store': 'All', 'category': 'All', 'channel': 'All'}
    out = fact
    checks = (('year', year, ['Year'], 'year'),
              ('category', category, ['Category', 'Category ID'], 'category'),
              ('channel', channel, ['Channel'], 'channel'))
    for key, wanted, cols, label in checks:
        if _is_all(wanted):
            continue
        value, err = _match(fact, cols, wanted, label)
        if err:
            return None, scope, err
        scope[key] = value if key != 'year' else int(value)
        out = out[out[cols[0]] == value]
    if not _is_all(store):
        label, err = _match_store(fact, store)
        if err:
            return None, scope, err
        scope['store'] = label
        out = out[out['Store Label'] == label]
    return out, scope, None


def _revenue_caveats(rows: pd.DataFrame) -> list[str]:
    caveats = [PROFIT_CAVEAT]
    n_missing = int(rows['Revenue'].isna().sum())
    if n_missing:
        caveats.append(f'{n_missing} sales row(s) in scope have blank or non-numeric revenue '
                       'and were left out.')
    if rows.empty:
        caveats.append('No sales rows match this scope, so the result is empty.')
    return caveats


def _money(x) -> float:
    return round(float(x), 2)


def _pct(part, whole):
    return round(float(part) / float(whole) * 100, 2) if whole else None


# ------------------------------------------------------ analytical tools
def get_total_revenue(model: dict, year=None, store=None, category=None,
                      channel=None) -> ToolResult:
    """Total revenue for one scope, e.g. 'website, 2028' or 'SH05, Beans'."""
    name = 'get_total_revenue'
    rows, scope, err = _subset(model['fact'], year, store, category, channel)
    if err:
        return _error(name, err, scope)
    return ToolResult(
        tool=name, value=_money(rows['Revenue'].sum()),
        definition='Sum of the stored Revenue column over the Sales rows in scope '
                   '(one row = one product at one store in one month).',
        scope=scope, rows_used=int(rows['Revenue'].notna().sum()),
        caveats=_revenue_caveats(rows))


def get_revenue_by_channel(model: dict, year=None, store=None, category=None) -> ToolResult:
    """Website vs Brick & Mortar revenue, each with its share of the scope's total."""
    name = 'get_revenue_by_channel'
    rows, scope, err = _subset(model['fact'], year, store, category)
    if err:
        return _error(name, err, scope)
    total = rows['Revenue'].sum()
    by = rows.groupby('Channel')['Revenue'].sum().sort_values(ascending=False)
    value = {str(ch): {'revenue': _money(v), 'share_of_total_pct': _pct(v, total)}
             for ch, v in by.items()}
    return ToolResult(
        tool=name, value={'channels': value, 'total_revenue': _money(total)},
        definition='Sum of Revenue by sales channel (Stores.StoreType). Share = channel '
                   'revenue / total revenue of all channels in the same scope.',
        scope=scope, rows_used=int(rows['Revenue'].notna().sum()),
        caveats=_revenue_caveats(rows))


def get_revenue_by_year(model: dict, store=None, category=None, channel=None) -> ToolResult:
    """Revenue for each year with the % change from the year before."""
    name = 'get_revenue_by_year'
    rows, scope, err = _subset(model['fact'], None, store, category, channel)
    if err:
        return _error(name, err, scope)
    by = rows.dropna(subset=['Year']).groupby('Year')['Revenue'].sum().sort_index()
    value, prev = {}, None
    for yr, v in by.items():
        value[str(int(yr))] = {'revenue': _money(v),
                               'change_vs_prior_year_pct': _pct(v - prev, prev) if prev else None}
        prev = v
    caveats = _revenue_caveats(rows)
    months = rows.dropna(subset=['Year']).groupby('Year')['Month'].nunique()
    partial = [int(y) for y, n in months.items() if n < 12]
    if partial:
        caveats.append(f'Year(s) {partial} have fewer than 12 months of data, so their totals '
                       'are not comparable with full years.')
    no_date = int(rows['Year'].isna().sum())
    if no_date:
        caveats.append(f'{no_date} row(s) without a valid date are not in any year.')
    return ToolResult(
        tool=name, value=value,
        definition='Sum of Revenue by calendar year of the Sales Date. Change = (this year - '
                   'prior year) / prior year x 100.',
        scope=scope, rows_used=int(rows.dropna(subset=['Year'])['Revenue'].notna().sum()),
        caveats=caveats)


def get_growth(model: dict, by='store', start_year=None, end_year=None, category=None,
               channel=None) -> ToolResult:
    """Compare each store, channel or category between two years: which grew or declined most."""
    name = 'get_growth'
    fact = model['fact']
    if str(by).lower() not in GROWTH_DIMENSIONS:
        return _error(name, f'"by" must be one of {list(GROWTH_DIMENSIONS)}, not "{by}".')
    col = GROWTH_DIMENSIONS[str(by).lower()]
    years = sorted(int(y) for y in fact['Year'].dropna().unique())
    if not years:
        return _error(name, 'The loaded data has no valid dates.')
    picked = []
    for wanted, default in ((start_year, years[0]), (end_year, years[-1])):
        if _is_all(wanted):
            picked.append(default)
            continue
        value, err = _match(fact, ['Year'], wanted, 'year')
        if err:
            return _error(name, err)
        picked.append(int(value))
    start, end = picked
    if start >= end:
        return _error(name, f'start_year ({start}) must be earlier than end_year ({end}).')
    rows, scope, err = _subset(fact, None, None, category, channel)
    if err:
        return _error(name, err, scope)
    scope.update({'compared': f'{start} vs {end}', 'by': str(by).lower()})

    table = rows[rows['Year'].isin([start, end])].pivot_table(
        index=col, columns='Year', values='Revenue', aggfunc='sum')
    groups = []
    for group, r in table.iterrows():
        a, b = r.get(start), r.get(end)
        a = None if pd.isna(a) else float(a)
        b = None if pd.isna(b) else float(b)
        groups.append({
            'group': str(group),
            f'revenue_{start}': None if a is None else _money(a),
            f'revenue_{end}': None if b is None else _money(b),
            'change': None if a is None or b is None else _money(b - a),
            'change_pct': None if a is None or b is None else _pct(b - a, a),
        })
    comparable = [g for g in groups if g['change_pct'] is not None]
    comparable.sort(key=lambda g: g['change_pct'], reverse=True)
    declined = [g for g in comparable if g['change'] < 0]
    caveats = _revenue_caveats(rows)
    caveats.append(f'Compares the two years {start} and {end} only; years in between are not used.')
    if not declined and comparable:
        caveats.append(f'No {by} declined from {start} to {end}. The smallest change was '
                       f'{comparable[-1]["group"]} at {comparable[-1]["change_pct"]}%.')
    missing = [g['group'] for g in groups if g['change_pct'] is None]
    if missing:
        caveats.append(f'{missing} lack revenue in one of the two years (or it was 0), '
                       'so no % change is given for them.')
    return ToolResult(
        tool=name,
        value={'groups_ranked_by_change_pct': comparable,
               'largest_increase': comparable[0]['group'] if comparable and comparable[0]['change'] > 0 else None,
               'largest_decline': declined[-1]['group'] if declined else None,
               'number_declined': len(declined),
               'not_comparable': missing},
        definition=f'For each {by}: revenue in {end} minus revenue in {start}, and that change '
                   f'as a % of {start} revenue.',
        scope=scope, rows_used=int(rows[rows['Year'].isin([start, end])]['Revenue'].notna().sum()),
        caveats=caveats)


def get_monthly_revenue(model: dict, year=None, store=None, category=None,
                        channel=None) -> ToolResult:
    """Revenue for each calendar month and its share of the year (or all years) in scope."""
    name = 'get_monthly_revenue'
    rows, scope, err = _subset(model['fact'], year, store, category, channel)
    if err:
        return _error(name, err, scope)
    dated = rows.dropna(subset=['Month'])
    total = dated['Revenue'].sum()
    by = dated.groupby('Month')['Revenue'].sum().sort_index()
    months = [{'month': MONTH_NAMES[int(m) - 1], 'revenue': _money(v),
               'share_pct': _pct(v, total)} for m, v in by.items()]
    period = f'year {scope["year"]}' if scope['year'] != 'All' else 'all years combined'
    value = {'months': months}
    if months:
        value['highest_month'] = max(months, key=lambda m: m['revenue'])['month']
        value['lowest_month'] = min(months, key=lambda m: m['revenue'])['month']
    return ToolResult(
        tool=name, value=value,
        definition=f'Sum of Revenue by calendar month ({period}). Share = month revenue / '
                   f'total revenue of the same scope ({period}) x 100.',
        scope=scope, rows_used=int(dated['Revenue'].notna().sum()),
        caveats=_revenue_caveats(rows))


def get_category_performance(model: dict, year=None, store=None, channel=None) -> ToolResult:
    """Product categories ranked by revenue, with each one's share."""
    name = 'get_category_performance'
    rows, scope, err = _subset(model['fact'], year, store, None, channel)
    if err:
        return _error(name, err, scope)
    total = rows['Revenue'].sum()
    by = rows.groupby('Category')['Revenue'].sum().sort_values(ascending=False)
    value = [{'rank': i + 1, 'category': str(c), 'revenue': _money(v),
              'share_pct': _pct(v, total)} for i, (c, v) in enumerate(by.items())]
    return ToolResult(
        tool=name, value={'categories': value, 'total_revenue': _money(total)},
        definition='Sum of Revenue by product category (via Sales.Category ID). Share = category '
                   'revenue / total revenue in the same scope x 100.',
        scope=scope, rows_used=int(rows['Revenue'].notna().sum()),
        caveats=_revenue_caveats(rows))


def _strength(r) -> str:
    """Common rule of thumb for the size of a correlation coefficient."""
    if r is None or pd.isna(r):
        return 'not available'
    a = abs(r)
    size = 'negligible' if a < 0.1 else 'weak' if a < 0.3 else 'moderate' if a < 0.5 else 'strong'
    return f'{size} {"positive" if r > 0 else "negative"}' if size != 'negligible' else size


def get_satisfaction_vs_revenue(model: dict, year=None) -> ToolResult:
    """How store revenue lines up with survey Satisfaction and Interest, one point per store-year."""
    name = 'get_satisfaction_vs_revenue'
    fact, survey = model['fact'], model['survey']
    scope = {'year': 'All', 'unit': 'one store in one year'}
    if not _is_all(year):
        value, err = _match(fact, ['Year'], year, 'year')
        if err:
            return _error(name, err, scope)
        scope['year'] = int(value)
        fact = fact[fact['Year'] == value]
        survey = survey[survey['Year'] == value]
    # Bring revenue UP to the survey's grain (store-year) before joining.
    revenue = fact.groupby('StoreYear')['Revenue'].sum().rename('Revenue').reset_index()
    survey = survey.drop_duplicates(subset='Survey ID')
    pairs = survey.merge(revenue, left_on='Survey ID', right_on='StoreYear', how='left')
    no_score = pairs[pairs['Satisfaction'].isna()]['Survey ID'].tolist()
    no_sales = pairs[pairs['Revenue'].isna()]['Survey ID'].tolist()
    usable = pairs.dropna(subset=['Satisfaction', 'Revenue'])
    caveats = ['Correlation is not causation: a link between satisfaction and revenue does not show '
               'that one causes the other. Store size, location and market may drive both.',
               PROFIT_CAVEAT]
    if no_score:
        caveats.append(f'{len(no_score)} store-year(s) have no satisfaction score and were left out '
                       f'(not treated as 0): {no_score[:10]}{" ..." if len(no_score) > 10 else ""}.')
    if no_sales:
        caveats.append(f'{len(no_sales)} surveyed store-year(s) have no sales rows: {no_sales[:10]}.')
    if len(usable) < 3:
        return _error(name, f'Only {len(usable)} store-year(s) have both a score and revenue; '
                            'at least 3 are needed to measure a relationship.', scope)
    r_sat = usable['Satisfaction'].corr(usable['Revenue'])
    r_int = usable['Interest'].corr(usable['Revenue']) if usable['Interest'].notna().sum() >= 3 else None
    caveats.append(f'Based on {len(usable)} store-years, a small sample; one survey score per store per year.')
    top = usable.nlargest(1, 'Satisfaction').iloc[0]
    low = usable.nsmallest(1, 'Satisfaction').iloc[0]
    return ToolResult(
        tool=name,
        value={'store_years_compared': int(len(usable)),
               'correlation_satisfaction_revenue': round(float(r_sat), 3),
               'satisfaction_relationship': _strength(r_sat),
               'correlation_interest_revenue': None if r_int is None else round(float(r_int), 3),
               'interest_relationship': _strength(r_int),
               'highest_satisfaction': {'store_year': top['Survey ID'], 'satisfaction': float(top['Satisfaction']),
                                        'revenue': _money(top['Revenue'])},
               'lowest_satisfaction': {'store_year': low['Survey ID'], 'satisfaction': float(low['Satisfaction']),
                                       'revenue': _money(low['Revenue'])}},
        definition='Pearson correlation between survey Satisfaction (0-5) and that store\'s total '
                   'Revenue in the same year, across store-years; same for Interest (0-100). '
                   'Revenue is summed to store-year first so each survey row is used once.',
        scope=scope, rows_used=int(len(usable)), caveats=caveats)


def get_data_quality_report(model: dict) -> ToolResult:
    """Problems found in the loaded data: blanks, unmatched keys, join checks, duplicates."""
    tables = model.get('tables', {})
    keys = {'sales': 'Sales ID', 'products': 'Product ID', 'categories': 'Category ID',
            'stores': 'ID', 'survey': 'Survey ID'}
    blanks = {t: blank_report(df, keys.get(t, df.columns[0])) for t, df in tables.items()}
    value = {
        'sales_rows': int(len(model['fact'])),
        'issues_found': model['issues'] or ['None: every Sales row has a valid date and revenue, '
                                            'every key matches a lookup table, no join changed revenue.'],
        'merge_checks': [{k: c[k] for k in ('merge', 'rows_before', 'rows_after', 'sum_before',
                                            'sum_after', 'changed')} for c in model['merge_checks']],
        'blank_values': {t: b for t, b in blanks.items() if b},
        'duplicate_rows': {t: int(df.duplicated().sum()) for t, df in tables.items()},
    }
    return ToolResult(
        tool='get_data_quality_report', value=value,
        definition='Checks run on the currently loaded files: blank cells by table and column, '
                   'fully duplicated rows, Sales keys missing from lookup tables, and row/revenue '
                   'counts before and after every join.',
        scope={'data': 'all loaded tables, no filters'}, rows_used=int(len(model['fact'])),
        caveats=['Blank survey scores mean "not surveyed", not a score of 0.'] if 'survey' in blanks
        and blanks['survey'] else [])


# ------------------------------------------------------------ merge check
def check_merge(left: pd.DataFrame, right: pd.DataFrame, on, value_col: str, how: str = 'left'):
    """Merge, and report whether the join changed the row count or the revenue sum.
    `value_col` must be a numeric column in `left`. Returns (merged, report)."""
    before_rows = len(left)
    before_sum = float(pd.to_numeric(left[value_col], errors='coerce').sum())
    merged = left.merge(right, on=on, how=how)
    after_rows = len(merged)
    after_sum = float(pd.to_numeric(merged[value_col], errors='coerce').sum())
    fan_out = after_rows > before_rows or abs(after_sum - before_sum) > 1e-9
    report = {
        'rows_before': before_rows, 'rows_after': after_rows,
        'sum_before': before_sum, 'sum_after': after_sum,
        'changed': fan_out,
        'warning': ('The join changed the row count or the total. Check the grain and keys '
                    'of both tables before using this result.') if fan_out else '',
    }
    return merged, report
