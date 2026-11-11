"""Tests for the analytical tools and the dispatcher.
The data is a tiny made-up E-Presso, so every expected answer can be checked by hand:

Store  City    Channel         2025 (C1 Beans)   2026 (C1 Beans)   2026 (C2 Syrups)
W      -       Website         100               300               -
B1     Orlando Brick & Mortar  200               150               50
B2     Orlando Brick & Mortar  100               100               -
Survey: W has no scores; B1 4.0/2025, 4.5/2026; B2 2.0/2025, 3.0/2026.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import agent  # noqa: E402
import analytics  # noqa: E402


def sale(i, date, store, cat, prod, rev):
    yy = date[-2:]
    return {'Sales ID': f'S{i}', 'Date': f'{date[:-2]}20{yy} 0:00:00', 'Store ID': store,
            'StoreYear': f'{store}_{yy}', 'Category ID': cat, 'Product ID': prod,
            'Revenue': str(rev)}


@pytest.fixture
def model():
    sales = pd.DataFrame([
        sale(1, '1/31/25', 'W', 'C1', 'P1', 100),
        sale(2, '1/31/25', 'B1', 'C1', 'P1', 200),
        sale(3, '6/30/25', 'B2', 'C1', 'P1', 100),
        sale(4, '1/31/26', 'W', 'C1', 'P1', 300),
        sale(5, '6/30/26', 'B1', 'C1', 'P1', 150),
        sale(6, '6/30/26', 'B1', 'C2', 'P2', 50),
        sale(7, '6/30/26', 'B2', 'C1', 'P1', 100),
    ])
    tables = {
        'sales': sales,
        'products': pd.DataFrame({'Product ID': ['P1', 'P2'], 'Product': ['Bean', 'Syrup']}),
        'categories': pd.DataFrame({'Category ID': ['C1', 'C2'], 'Category': ['Beans', 'Syrups']}),
        'stores': pd.DataFrame({'ID': ['W', 'B1', 'B2'], 'City': [None, 'Orlando', 'Orlando'],
                                'State': [None, 'FL', 'FL'],
                                'StoreType': ['Website', 'Brick & Mortar', 'Brick & Mortar'],
                                'Market': ['5-Global', '1-Small', '1-Small'],
                                'Location': ['Website', 'South', 'East']}),
        'survey': pd.DataFrame({
            'Survey ID': ['W_25', 'W_26', 'B1_25', 'B1_26', 'B2_25', 'B2_26'],
            'Store ID': ['W', 'W', 'B1', 'B1', 'B2', 'B2'],
            'Year': ['Y2025', 'Y2026'] * 3,
            'Satisfaction': [None, None, 4.0, 4.5, 2.0, 3.0],
            'Interest': [None, None, 80, 90, 60, 70]}),
    }
    return analytics.build_model(tables)


# ------------------------------------------------------------ total revenue
def test_total_revenue_all(model):
    r = analytics.get_total_revenue(model)
    assert r.value == 1000 and r.rows_used == 7 and r.error is None
    assert any('not profit' in c for c in r.caveats)


def test_total_revenue_website_2026(model):
    r = analytics.get_total_revenue(model, year=2026, channel='website')   # case-insensitive
    assert r.value == 300
    assert r.scope == {'year': 2026, 'store': 'All', 'category': 'All', 'channel': 'Website'}


def test_year_given_as_text_and_category_by_id(model):
    assert analytics.get_total_revenue(model, year='2025', category='C1').value == 400


def test_unknown_store_is_an_error_not_a_guess(model):
    r = analytics.get_total_revenue(model, store='Chicago')
    assert r.error and r.value is None and 'B1 Orlando' in r.error


def test_city_with_two_stores_is_an_error(model):
    r = analytics.get_total_revenue(model, store='Orlando')
    assert r.error and 'more than one store' in r.error


def test_store_by_id_or_label(model):
    assert analytics.get_total_revenue(model, store='b1').value == 400
    assert analytics.get_total_revenue(model, store='B2 Orlando').value == 200


def test_unknown_year_is_an_error(model):
    assert analytics.get_total_revenue(model, year=2031).error


# ------------------------------------------------------------- by channel
def test_revenue_by_channel_shares(model):
    v = analytics.get_revenue_by_channel(model).value
    assert v['total_revenue'] == 1000
    assert v['channels']['Brick & Mortar'] == {'revenue': 600, 'share_of_total_pct': 60.0}
    assert v['channels']['Website'] == {'revenue': 400, 'share_of_total_pct': 40.0}


# ---------------------------------------------------------------- by year
def test_revenue_by_year_change(model):
    v = analytics.get_revenue_by_year(model).value
    assert v['2025'] == {'revenue': 400, 'change_vs_prior_year_pct': None}
    assert v['2026'] == {'revenue': 600, 'change_vs_prior_year_pct': 50.0}
    r = analytics.get_revenue_by_year(model)
    assert any('fewer than 12 months' in c for c in r.caveats)   # tiny data has 2 months/year


# ----------------------------------------------------------------- growth
def test_growth_by_store_finds_decline(model):
    v = analytics.get_growth(model, by='store').value
    ranked = [(g['group'], g['change_pct']) for g in v['groups_ranked_by_change_pct']]
    assert ranked == [('W Website', 200.0), ('B2 Orlando', 0.0), ('B1 Orlando', 0.0)] or \
        ranked == [('W Website', 200.0), ('B1 Orlando', 0.0), ('B2 Orlando', 0.0)]
    assert v['largest_increase'] == 'W Website'
    assert v['largest_decline'] is None and v['number_declined'] == 0


def test_growth_says_when_nothing_declined(model):
    r = analytics.get_growth(model, by='channel')
    assert r.value['largest_decline'] is None
    assert any('No channel declined' in c for c in r.caveats)


def test_growth_with_a_decline(model):
    r = analytics.get_growth(model, by='store', category='Beans')   # B1 beans: 200 -> 150
    assert r.value['largest_decline'] == 'B1 Orlando'
    b1 = [g for g in r.value['groups_ranked_by_change_pct'] if g['group'] == 'B1 Orlando'][0]
    assert b1['change'] == -50 and b1['change_pct'] == -25.0


def test_growth_rejects_bad_inputs(model):
    assert analytics.get_growth(model, by='manager').error
    assert analytics.get_growth(model, start_year=2026, end_year=2025).error


# ---------------------------------------------------------------- monthly
def test_monthly_revenue_share_uses_year_total(model):
    v = analytics.get_monthly_revenue(model, year=2026).value
    assert v['months'] == [{'month': 'Jan', 'revenue': 300, 'share_pct': 50.0},
                           {'month': 'Jun', 'revenue': 300, 'share_pct': 50.0}]


# --------------------------------------------------------------- category
def test_category_performance(model):
    v = analytics.get_category_performance(model).value
    assert v['categories'][0] == {'rank': 1, 'category': 'Beans', 'revenue': 950, 'share_pct': 95.0}
    assert v['categories'][1]['category'] == 'Syrups'


# ----------------------------------------------------------- satisfaction
def test_satisfaction_excludes_blank_scores_and_warns_on_causation(model):
    r = analytics.get_satisfaction_vs_revenue(model)
    # Store-years used: B1_25 (4.0, 200), B1_26 (4.5, 200), B2_25 (2.0, 100), B2_26 (3.0, 100)
    assert r.value['store_years_compared'] == 4
    expected = pd.Series([4.0, 4.5, 2.0, 3.0]).corr(pd.Series([200, 200, 100, 100]))
    assert r.value['correlation_satisfaction_revenue'] == round(expected, 3)
    assert any('not causation' in c for c in r.caveats)
    assert any('W_25' in c for c in r.caveats)          # website rows named, not scored as 0


def test_satisfaction_needs_three_points(model):
    assert analytics.get_satisfaction_vs_revenue(model, year=2025).error   # only 2 store-years


# ------------------------------------------------------------ data quality
def test_data_quality_report(model):
    v = analytics.get_data_quality_report(model).value
    assert v['sales_rows'] == 7
    assert all(not c['changed'] for c in v['merge_checks'])
    assert 'survey' in v['blank_values'] and 'stores' in v['blank_values']


# ------------------------------------------------------------- merge check
def test_merge_fan_out_is_detected():
    left = pd.DataFrame({'store': ['A', 'B'], 'amount': [100, 50]})
    dup = pd.DataFrame({'store': ['A', 'A', 'B'], 'city': ['X', 'X2', 'Y']})
    _, rep = analytics.check_merge(left, dup, on='store', value_col='amount')
    assert rep['changed'] and rep['sum_after'] == 250


# -------------------------------------------------------------- dispatcher
def test_dispatcher_runs_and_logs(model):
    log = []
    r = agent.run_tool('get_total_revenue', {'year': 2025}, model, log)
    assert r.value == 400
    assert log[0]['tool'] == 'get_total_revenue' and log[0]['arguments'] == {'year': 2025}
    assert log[0]['result']['value'] == 400


def test_dispatcher_rejects_unknown_tool_and_arguments(model):
    log = []
    assert agent.run_tool('run_python', {}, model, log).error
    assert agent.run_tool('get_total_revenue', {'code': 'x'}, model, log).error
    assert len(log) == 2                                   # rejected calls are logged too


def test_every_tool_follows_the_contract(model):
    for name in agent.TOOLS:
        d = agent.run_tool(name, {}, model, []).to_dict()
        assert set(d) >= {'tool', 'value', 'definition', 'scope', 'rows_used', 'caveats'}
        assert d['error'] is None and d['tool'] == name


def test_unsupported_question(model):
    out = agent.answer_question('What is the meaning of life?', model)
    assert 'cannot answer' in out['findings']
