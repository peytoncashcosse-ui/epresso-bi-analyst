"""Tests for loading and combining the E-Presso tables.
Every table here is tiny and made up, so each expected answer can be checked by hand."""
import io
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import analytics  # noqa: E402

SALES_CSV = (
    '"Sales ID","Date","Store ID","StoreYear","Category ID","Product ID","Revenue"\n'
    '"S1",1/31/2025 0:00:00,"W","W_25","C1","P1",100.00\n'
    '"S2",2/28/2025 0:00:00,"B","B_25","C1","P1",200.00\n'
    '"S3",1/31/2026 0:00:00,"B","B_26","C2","P2",50.00\n'
)
STORES_TSV = (
    'ID\tCity\tState\tPostalCode\tPhone\tStoreType\tMarket\tLocation\tManager\n'
    'W\t\t\t\t1-800\tWebsite\t5-Global\tWebsite\t"Doe, Jane"\n'
    'B\tTown\tFL\t12345\t(555)\tBrick & Mortar\t1-Small\tSouth\t"Roe, Rick"\n'
)


def read(table, text, name):
    return analytics.read_epresso_table(table, text.encode(), name)


@pytest.fixture
def tables():
    return {
        'sales': read('sales', SALES_CSV, 'Sales.txt'),
        'products': pd.DataFrame({'Product ID': ['P1', 'P2'], 'Product': ['Bean', 'Syrup']}),
        'categories': pd.DataFrame({'Category ID': ['C1', 'C2'], 'Category': ['Beans', 'Syrups']}),
        'stores': read('stores', STORES_TSV, 'Stores.csv'),
        'survey': pd.DataFrame({'Survey ID': ['W_25', 'B_25'], 'Store ID': ['W', 'B'],
                                'Year': ['Y2025', 'Y2025'], 'Satisfaction': [None, 4.5],
                                'Interest': [None, 80]}),
    }


# ---------------------------------------------------------------- reading
def test_tab_separated_stores_keep_quoted_comma_names():
    stores = read('stores', STORES_TSV, 'Stores.csv')
    assert len(stores) == 2
    assert stores.loc[0, 'Manager'] == 'Doe, Jane'      # comma inside a name did not split it
    assert pd.isna(stores.loc[0, 'City'])                # blank stays blank


def test_missing_required_column_gives_plain_message():
    bad = SALES_CSV.replace('"Revenue"', '"Amount"')
    with pytest.raises(analytics.DataError, match=r"missing required column\(s\) \['Revenue'\]"):
        read('sales', bad, 'Sales.txt')


def test_survey_excel_header_on_row_3():
    buf = io.BytesIO()
    rows = pd.DataFrame([['E-Presso Market Survey', None, None, None, None],
                         [None] * 5,
                         ['Survey ID', 'Store ID', 'Year', 'Satisfaction', 'Interest'],
                         ['B_25', 'B', 'Y2025', 4.5, 80]])
    with pd.ExcelWriter(buf) as xl:
        rows.to_excel(xl, sheet_name='Survey Results', header=False, index=False)
    survey = analytics.read_epresso_table('survey', buf.getvalue(), 'survey.xlsx')
    assert list(survey.columns) == ['Survey ID', 'Store ID', 'Year', 'Satisfaction', 'Interest']
    assert analytics.prepare_survey(survey).loc[0, 'Year'] == 2025


# --------------------------------------------------------------- preparing
def test_prepare_sales_types_and_blanks():
    raw = pd.DataFrame({'Date': ['1/31/2025 0:00:00', '2025-02-28', None],
                        'Revenue': ['$1,000.50', 'abc', '']})
    out = analytics.prepare_sales(raw)
    assert out['Revenue'].iloc[0] == 1000.50
    assert out['Revenue'].isna().sum() == 2            # 'abc' and blank are NaN, not 0
    assert list(out['Year'].iloc[:2]) == [2025, 2025]  # second date format also understood
    assert pd.isna(out['Year'].iloc[2])


# ---------------------------------------------------------------- the model
def test_total_and_joins_do_not_change_revenue(tables):
    model = analytics.build_model(tables)
    assert analytics.total_revenue(model['fact']) == 350          # 100 + 200 + 50
    assert all(not c['changed'] for c in model['merge_checks'])
    assert model['issues'] == []
    by_channel = model['fact'].groupby('Channel')['Revenue'].sum().to_dict()
    assert by_channel == {'Website': 100, 'Brick & Mortar': 250}


def test_duplicate_lookup_key_does_not_inflate_revenue(tables):
    tables['products'] = pd.DataFrame({'Product ID': ['P1', 'P1', 'P2'],
                                       'Product': ['Bean', 'Bean copy', 'Syrup']})
    model = analytics.build_model(tables)
    assert analytics.total_revenue(model['fact']) == 350          # not 650
    assert any('repeats' in i for i in model['issues'])


def test_unknown_product_is_reported_but_revenue_kept(tables):
    tables['products'] = tables['products'].iloc[:1]              # drop P2
    model = analytics.build_model(tables)
    assert analytics.total_revenue(model['fact']) == 350
    assert any("not found in Products: ['P2']" in i for i in model['issues'])


def test_adding_1000_to_one_row_adds_exactly_1000(tables):
    before = analytics.total_revenue(analytics.build_model(tables)['fact'])
    tables['sales'].loc[tables['sales']['Sales ID'] == 'S2', 'Revenue'] = '1200.00'
    after = analytics.total_revenue(analytics.build_model(tables)['fact'])
    assert after - before == 1000


def test_blank_report_names_rows(tables):
    rep = analytics.blank_report(tables['stores'], 'ID')
    assert {'column': 'City', 'blank_count': 1, 'rows (by key)': 'W'} in rep
