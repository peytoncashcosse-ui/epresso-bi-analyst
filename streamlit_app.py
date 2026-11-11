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
        left.plotly_chart(fig, width='stretch')

        monthly = analytics.revenue_by(view, 'MonthStart', 'Channel')
        fig = px.line(monthly, x='MonthStart', y='Revenue', color='Channel', markers=True,
                      title='Monthly revenue by sales channel', hover_data=money)
        fig.update_layout(yaxis_title='Revenue ($)', xaxis_title='Month')
        right.plotly_chart(fig, width='stretch')

        left, right = st.columns(2)
        stores = analytics.revenue_by(view, 'Store Label', 'Channel').sort_values('Revenue')
        fig = px.bar(stores, x='Revenue', y='Store Label', color='Channel', orientation='h',
                     title='Revenue by store', hover_data=money,
                     height=max(350, 28 * len(stores)))
        fig.update_layout(xaxis_title='Revenue ($)', yaxis_title='Store (ID + city)')
        left.plotly_chart(fig, width='stretch')

        cats = analytics.revenue_by(view, 'Category').sort_values('Revenue', ascending=False)
        fig = px.bar(cats, x='Category', y='Revenue', title='Revenue by product category',
                     hover_data=money)
        fig.update_layout(yaxis_title='Revenue ($)', xaxis_title='Category')
        right.plotly_chart(fig, width='stretch')

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
def show_answer(answer: dict):
    """Scope first, then Findings (from tool results only), Interpretation, Next steps,
    and the raw tool-call log underneath."""
    st.markdown(f"**Scope:** {answer['scope']}")
    st.markdown('**Findings** (calculated by the tools)')
    st.markdown('\n'.join(f'- {line}' for line in answer['findings']))
    if answer['interpretation']:
        st.markdown('**Interpretation**')
        st.markdown('\n'.join(f'- {line}' for line in answer['interpretation']))
    st.markdown('**Next steps**')
    st.markdown('\n'.join(f'- {line}' for line in answer['next_steps']))
    st.caption(f"Answered by: {answer['mode']}")
    with st.expander(f"Tool-call log ({len(answer['tool_log'])} call(s))"):
        if answer['tool_log']:
            st.json(answer['tool_log'])
        else:
            st.write('No tool was called for this question.')


def gemini_client():
    """Build the Gemini client from Streamlit Secrets. Returns (client, model, problem).
    The key is never shown, logged or stored anywhere else."""
    try:
        key = st.secrets.get('GEMINI_API_KEY', '')
        model_name = st.secrets.get('GEMINI_MODEL', agent.DEFAULT_LLM_MODEL)
    except Exception:  # no secrets file at all
        key, model_name = '', agent.DEFAULT_LLM_MODEL
    if not key:
        return None, model_name, 'no GEMINI_API_KEY in Streamlit Secrets'
    try:
        from google import genai
        from google.genai import types
        # A request that takes longer than 90 s raises an error, so the rules answer instead.
        client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=90_000))
        return client, model_name, ''
    except Exception as exc:
        return None, model_name, f'could not start the Gemini client ({type(exc).__name__})'


with tab_assistant:
    client, llm_model, llm_problem = gemini_client()
    rules_only = st.toggle('Use the rules-based assistant only', value=client is None,
                           disabled=client is None,
                           help='Off: Gemini chooses the tools (Option A). On: keyword rules choose '
                                'them (Option B). Both use the same eight functions.')
    if client is not None and not rules_only:
        st.caption(f'Mode: language-model agent ({llm_model}, function calling). The model may only '
                   'choose among eight approved analytical functions; our code runs them on the '
                   'currently loaded data, and every number in the answer is checked against the '
                   'tool results. If the API fails or its quota runs out, the rules-based assistant '
                   'answers instead. No AI-written code is ever run.')
    else:
        st.caption('Mode: rules-based assistant (Option B). Keyword rules pick one of eight approved '
                   'analytical functions and its parameters; the function calculates the answer '
                   'from the currently loaded data. No AI-written code is ever run.'
                   + (f' Language model off: {llm_problem}.' if llm_problem else ''))
    st.session_state.setdefault('n_questions', 0)
    st.session_state.setdefault('history', [])
    remaining = MAX_QUESTIONS - st.session_state['n_questions']
    st.caption(f'Questions left this session: {remaining} of {MAX_QUESTIONS}.')
    with st.expander('What can I ask?'):
        st.markdown('\n'.join(f'- {c}' for c in agent.CAPABILITIES))
    for item in st.session_state['history']:
        with st.chat_message('user'):
            st.write(item['question'])
        with st.chat_message('assistant'):
            show_answer(item['answer'])
    question = st.chat_input('Ask a question about the loaded data')
    if question:
        if st.session_state['n_questions'] >= MAX_QUESTIONS:
            st.warning(f'You have reached the limit of {MAX_QUESTIONS} questions for this session. '
                       'Reload the page to start a new session.')
        else:
            st.session_state['n_questions'] += 1
            active = {k: v for k, v in selections.items() if v}
            with st.spinner('Calculating...'):
                answer = agent.answer_question(
                    question, model, mode='rules' if rules_only else 'llm',
                    data_note=sources['Sales'], client=client, model_name=llm_model,
                    dashboard_scope=analytics.describe_scope(active) if active else '')
            st.session_state['history'].append({'question': question, 'answer': answer})
            st.rerun()
