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
    return {'fact': fact, 'survey': survey, 'merge_checks': checks, 'issues': issues}


def total_revenue(fact: pd.DataFrame) -> float:
    """Sum of the stored Revenue column over the rows given (blanks are skipped)."""
    return float(fact['Revenue'].sum())


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


def _apply_filters(df: pd.DataFrame, filters: dict | None):
    """Validate filters against the LOADED data, then apply them."""
    for col, wanted in (filters or {}).items():
        if col not in df.columns:
            return df, f'Unknown column: {col}'
        wanted_list = list(wanted) if isinstance(wanted, (list, tuple, set)) else [wanted]
        valid = set(df[col].dropna().unique())
        bad = [w for w in wanted_list if w not in valid]
        if bad:
            examples = sorted(map(str, valid))[:20]
            return df, f'{bad} not found in column {col}. Valid values include: {examples}'
        df = df[df[col].isin(wanted_list)]
    return df, None


# ------------------------------------------------------ analytical tools
def get_total(df: pd.DataFrame, value_col: str, filters: dict | None = None) -> ToolResult:
    """Sum of one numeric column, optionally filtered. EXAMPLE tool: replace the
    generic column names with your own definition of revenue."""
    name = 'get_total'
    if value_col not in df.columns:
        return _error(name, f'Unknown column: {value_col}')
    subset, err = _apply_filters(df, filters)
    if err:
        return _error(name, err, {'filters': filters})
    values = pd.to_numeric(subset[value_col], errors='coerce')
    n_bad = int(values.isna().sum())
    caveats = ['This is a sum of the chosen column. Revenue is not profit.']
    if n_bad:
        caveats.append(f'{n_bad} row(s) had a missing or non-numeric {value_col} and were excluded.')
    return ToolResult(tool=name, value=float(values.sum()), definition=f'Sum of {value_col}',
                      scope={'filters': filters or 'none (all rows)'},
                      rows_used=int(values.notna().sum()), caveats=caveats)


def group_total(df: pd.DataFrame, value_col: str, group_col: str,
                filters: dict | None = None) -> ToolResult:
    """Sum of one numeric column by group (store, channel, year, ...)."""
    name = 'group_total'
    for col in (value_col, group_col):
        if col not in df.columns:
            return _error(name, f'Unknown column: {col}')
    subset, err = _apply_filters(df, filters)
    if err:
        return _error(name, err, {'filters': filters})
    work = subset.assign(**{value_col: pd.to_numeric(subset[value_col], errors='coerce')})
    n_bad = int(work[value_col].isna().sum())
    n_nogroup = int(work[group_col].isna().sum())
    grouped = work.dropna(subset=[value_col, group_col]).groupby(group_col)[value_col].sum()
    caveats = ['Sums of the chosen column. Revenue is not profit.']
    if n_bad:
        caveats.append(f'{n_bad} row(s) with missing or non-numeric {value_col} were excluded.')
    if n_nogroup:
        caveats.append(f'{n_nogroup} row(s) with a missing {group_col} were excluded.')
    return ToolResult(tool=name, value={str(k): float(v) for k, v in grouped.items()},
                      definition=f'Sum of {value_col} by {group_col}',
                      scope={'filters': filters or 'none (all rows)'},
                      rows_used=int(len(work) - n_bad - n_nogroup), caveats=caveats)


def data_quality_report(df: pd.DataFrame) -> ToolResult:
    """Row count, duplicate rows, and missing values per column."""
    missing = {c: int(n) for c, n in df.isna().sum().items() if n > 0}
    caveats = []
    if missing:
        caveats.append('Missing values may limit conclusions drawn from those columns.')
    return ToolResult(tool='data_quality_report',
                      value={'rows': len(df), 'duplicate_rows': int(df.duplicated().sum()),
                             'columns_with_missing': missing},
                      definition='Counts of duplicate rows and missing values in the loaded table',
                      scope={'filters': 'none (full table)'}, rows_used=len(df), caveats=caveats)


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
