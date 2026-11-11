"""Main app: layout and interaction only.
Calculations live in analytics.py and the assistant in agent.py."""
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import agent
import analytics

MAX_QUESTIONS = 15  # per-session limit for the assistant
DATA_DIR = Path(__file__).parent / 'data'

st.set_page_config(page_title='E-Presso BI Analyst', layout='wide')
st.title('E-Presso BI Analyst')
st.caption('Revenue, channel, product and customer-survey analysis for E-Presso. '
           'Every number is calculated from the data currently loaded.')


@st.cache_data(show_spinner='Loading and combining data...')
def load_model(files: tuple):
    """files = ((table, filename, file_bytes), ...). The cache key includes the
    file BYTES, so a modified upload is always recalculated, never served stale."""
    tables = {table: analytics.read_epresso_table(table, data, name)
              for table, name, data in files}
    return tables, analytics.build_model(tables)


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header('Data')
    st.caption('The supplied E-Presso files load by default. Upload a file to replace '
               'that table; everything recalculates. Sales, Products and Categories '
               'are CSV/TXT exports of the Access database.')
    files, sources, problems = [], {}, []
    for table, spec in analytics.TABLE_SPECS.items():
        up = st.file_uploader(spec['label'], type=['csv', 'txt', 'tsv', 'xlsx', 'xls'],
                              key=f'upload_{table}')
        if up is not None:
            files.append((table, up.name, up.getvalue()))
            sources[spec['label']] = f'Uploaded: {up.name}'
        elif (DATA_DIR / spec['default_file']).exists():
            files.append((table, spec['default_file'],
                          (DATA_DIR / spec['default_file']).read_bytes()))
            sources[spec['label']] = f'Default: data/{spec["default_file"]}'
        else:
            problems.append(f'{spec["label"]}: no file uploaded and the default '
                            f'data/{spec["default_file"]} was not found.')

if problems:
    for p in problems:
        st.error(p)
    st.stop()

try:
    tables, model = load_model(tuple(files))
except analytics.DataError as exc:
    st.error(str(exc))
    st.stop()

fact = model['fact']

tab_data, tab_dash, tab_assistant = st.tabs(['Data and quality', 'Dashboard', 'Assistant'])

# ---------------------------------------------------------- data and quality
with tab_data:
    c1, c2, c3 = st.columns(3)
    c1.metric('Total revenue (all loaded sales)', f'${analytics.total_revenue(fact):,.2f}')
    c2.metric('Sales rows', f'{len(fact):,}')
    years = fact['Year'].dropna()
    c3.metric('Years covered', f'{years.min()}–{years.max()}' if len(years) else 'none')

    st.subheader('Data sources')
    st.dataframe(pd.DataFrame({'Table': list(sources), 'Source': list(sources.values()),
                               'Rows': [len(tables[t]) for t in analytics.TABLE_SPECS]}),
                 hide_index=True)

    st.subheader('Merge checks')
    st.caption('Each join adds labels from a lookup table to Sales. A correct many-to-one '
               'join leaves the row count and revenue total unchanged.')
    checks = pd.DataFrame(model['merge_checks']).drop(columns=['warning'])
    st.dataframe(checks.style.format({'sum_before': '${:,.2f}', 'sum_after': '${:,.2f}'}),
                 hide_index=True)

    st.subheader('Data-quality findings')
    if model['issues']:
        for issue in model['issues']:
            st.warning(issue)
    else:
        st.success('No problems found in Sales: every row has a valid date and revenue, '
                   'every key matches a lookup table, and no join changed revenue.')
    key_cols = {'sales': 'Sales ID', 'products': 'Product ID', 'categories': 'Category ID',
                'stores': 'ID', 'survey': 'Survey ID'}
    for table, spec in analytics.TABLE_SPECS.items():
        blanks = analytics.blank_report(tables[table], key_cols[table])
        dupes = int(tables[table].duplicated().sum())
        if blanks or dupes:
            st.markdown(f'**{spec["label"]}**: blank values'
                        + (f', {dupes} duplicate row(s)' if dupes else ''))
            if blanks:
                st.dataframe(pd.DataFrame(blanks), hide_index=True)

    st.subheader('Table profiles')
    for table, spec in analytics.TABLE_SPECS.items():
        df = tables[table]
        profile = analytics.profile_table(df)
        with st.expander(f'{spec["label"]}: {profile["rows"]:,} rows × {profile["columns"]} columns'):
            st.dataframe(df.head(50))
            left, right = st.columns(2)
            left.markdown('Missing values')
            left.dataframe(profile['missing'], hide_index=True)
            right.markdown('Data types')
            right.dataframe(profile['dtypes'], hide_index=True)

# ------------------------------------------------------------------ dashboard
with tab_dash:
    options = analytics.filter_options(fact)
    st.markdown('**Filters** (leave a box empty to include all)')
    cols = st.columns(len(options))
    selections = {name: col.multiselect(name, choices, key=f'filter_{name}')
                  for col, (name, choices) in zip(cols, options.items())}
    view = analytics.apply_filters(fact, selections)
    scope = analytics.describe_scope(selections)
    st.caption(f'Scope: {scope}')

    if view.empty:
        st.info('No sales match this combination of filters. Clear one or more filters.')
    else:
        total = analytics.total_revenue(view)
        by_channel = analytics.revenue_by(view, 'Channel')
        kpis = st.columns(2 + len(by_channel))
        kpis[0].metric('Total revenue', f'${total:,.0f}')
        kpis[1].metric('Sales rows used', f'{len(view):,}')
        for kpi, row in zip(kpis[2:], by_channel.itertuples()):
            share = row.Revenue / total * 100 if total else 0
            kpi.metric(f'{row.Channel} revenue', f'${row.Revenue:,.0f}',
                       f'{share:.1f}% of filtered total', delta_color='off')

        money = {'Revenue': ':$,.0f'}
        left, right = st.columns(2)

        yearly = analytics.revenue_by(view, 'Year', 'Channel')
        yearly['Year'] = yearly['Year'].astype(str)
        fig = px.bar(yearly, x='Year', y='Revenue', color='Channel', barmode='group',
                     title='Annual revenue by sales channel', hover_data=money)
        fig.update_layout(yaxis_title='Revenue ($)', xaxis_title='Year')
        left.plotly_chart(fig, use_container_width=True)

        monthly = analytics.revenue_by(view, 'MonthStart', 'Channel')
        fig = px.line(monthly, x='MonthStart', y='Revenue', color='Channel', markers=True,
                      title='Monthly revenue by sales channel', hover_data=money)
        fig.update_layout(yaxis_title='Revenue ($)', xaxis_title='Month')
        right.plotly_chart(fig, use_container_width=True)

        left, right = st.columns(2)
        stores = analytics.revenue_by(view, 'Store Label', 'Channel').sort_values('Revenue')
        fig = px.bar(stores, x='Revenue', y='Store Label', color='Channel', orientation='h',
                     title='Revenue by store', hover_data=money,
                     height=max(350, 28 * len(stores)))
        fig.update_layout(xaxis_title='Revenue ($)', yaxis_title='Store (ID + city)')
        left.plotly_chart(fig, use_container_width=True)

        cats = analytics.revenue_by(view, 'Category').sort_values('Revenue', ascending=False)
        fig = px.bar(cats, x='Category', y='Revenue', title='Revenue by product category',
                     hover_data=money)
        fig.update_layout(yaxis_title='Revenue ($)', xaxis_title='Category')
        right.plotly_chart(fig, use_container_width=True)

        with st.expander('Numbers behind the charts'):
            a, b = st.columns(2)
            a.markdown('Revenue by year')
            a.dataframe(analytics.revenue_by(view, 'Year').style.format({'Revenue': '${:,.2f}'}),
                        hide_index=True)
            b.markdown('Revenue by category')
            b.dataframe(cats.style.format({'Revenue': '${:,.2f}'}), hide_index=True)
            st.markdown('Revenue by month')
            st.dataframe(analytics.revenue_by(view, 'MonthStart').style.format(
                {'Revenue': '${:,.2f}', 'MonthStart': '{:%Y-%m}'}), hide_index=True)

# ------------------------------------------------------------------ assistant
with tab_assistant:
    st.caption('Mode: rules-based starter. Describe what you actually built here.')
    st.session_state.setdefault('n_questions', 0)
    st.session_state.setdefault('history', [])
    for item in st.session_state['history']:
        with st.chat_message('user'):
            st.write(item['question'])
        with st.chat_message('assistant'):
            st.markdown(f"**Scope:** {item['answer']['scope']}")
            st.markdown(f"**Findings:** {item['answer']['findings']}")
            if item['answer']['interpretation']:
                st.markdown(f"**Interpretation:** {item['answer']['interpretation']}")
            with st.expander('Tool-call log'):
                st.json(item['answer']['tool_log'])
    question = st.chat_input('Ask a question about the loaded data')
    if question:
        if st.session_state['n_questions'] >= MAX_QUESTIONS:
            st.warning('Question limit reached for this session. Reload the page to start over.')
        else:
            st.session_state['n_questions'] += 1
            answer = agent.answer_question(question, fact, mode='rules')
            st.session_state['history'].append({'question': question, 'answer': answer})
            st.rerun()
