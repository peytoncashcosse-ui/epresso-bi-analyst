"""Assistant: a dispatcher plus a router.
The router (rules now, a language model later) only CHOOSES a tool and its
arguments. Our code RUNS the tool. Nothing here executes model-written code,
and no tool changes the loaded data."""
from __future__ import annotations

import re
import time

import analytics
from analytics import ToolResult

# The ONLY things the assistant may do. Each entry: the function, the parameters it
# accepts, and a description (later given to the language model to choose from).
TOOLS = {
    'get_total_revenue': {
        'fn': analytics.get_total_revenue,
        'params': {'year', 'store', 'category', 'channel'},
        'description': 'Total revenue for a scope (any mix of year, store, category, channel).',
    },
    'get_revenue_by_channel': {
        'fn': analytics.get_revenue_by_channel,
        'params': {'year', 'store', 'category'},
        'description': 'Website vs Brick & Mortar revenue and each one\'s share of the total.',
    },
    'get_revenue_by_year': {
        'fn': analytics.get_revenue_by_year,
        'params': {'store', 'category', 'channel'},
        'description': 'Revenue for each year with % change from the prior year.',
    },
    'get_growth': {
        'fn': analytics.get_growth,
        'params': {'by', 'start_year', 'end_year', 'category', 'channel'},
        'description': 'Rank stores, channels or categories by revenue change between two years; '
                       'names the largest increase and decline.',
    },
    'get_monthly_revenue': {
        'fn': analytics.get_monthly_revenue,
        'params': {'year', 'store', 'category', 'channel'},
        'description': 'Revenue by calendar month and each month\'s share of the period total.',
    },
    'get_category_performance': {
        'fn': analytics.get_category_performance,
        'params': {'year', 'store', 'channel'},
        'description': 'Product categories ranked by revenue with their shares.',
    },
    'get_satisfaction_vs_revenue': {
        'fn': analytics.get_satisfaction_vs_revenue,
        'params': {'year'},
        'description': 'Correlation of survey satisfaction and interest with store revenue '
                       '(store-year level). Association only, not causation.',
    },
    'get_data_quality_report': {
        'fn': analytics.get_data_quality_report,
        'params': set(),
        'description': 'Blanks, duplicates, unmatched keys and join checks in the loaded data.',
    },
}

CAPABILITIES = [
    'total revenue for any year, store, category or channel ("How much did the website make in 2028?")',
    'website vs brick-and-mortar revenue and shares',
    'revenue by year and year-over-year change',
    'which store, channel or category grew or declined most between two years',
    'monthly revenue patterns',
    'product category rankings',
    'how customer satisfaction relates to revenue (association only)',
    'data-quality problems in the loaded files',
]
UNSUPPORTED = ('I can only answer questions that my approved analytical functions can '
               'calculate from the loaded data, so I cannot answer that one. I can tell you about: '
               + '; '.join(CAPABILITIES) + '.')

# For when you add a language model: keep these rules in the system prompt.
SYSTEM_PROMPT = """You are an analytical assistant for E-Presso managers.
Rules:
- Only state numbers that appear in a tool result. Never estimate or recall figures.
- Always call a tool before making a numerical claim.
- State the scope (which filters/period) of every answer.
- Separate Findings (from tool results), Interpretation, and Next steps.
- Revenue is not profit. Association is not causation.
- If the data cannot support a conclusion, say so and name the missing information.
- Never ask for, run, or write code. Never modify data."""

NO_RECOMMENDATION = ('No recommendation is supported by this data alone. A decision like this '
                     'would also need operating costs and profit by store, lease and staffing '
                     'obligations, and customer behavior (traffic, retention, overlap with the '
                     'website).')


# ------------------------------------------------------------- dispatcher
def run_tool(name: str, args: dict, model: dict, log: list) -> ToolResult:
    """The dispatcher: check the tool name and arguments, run the function on the
    loaded data, and log the call. A tool that crashes returns an error result
    instead of breaking the app."""
    if name not in TOOLS:
        result = analytics._error(name, f'Unknown tool: {name}')
    else:
        unexpected = set(args) - TOOLS[name]['params']
        if unexpected:
            result = analytics._error(name, f'Unexpected argument(s): {sorted(unexpected)}')
        else:
            try:
                result = TOOLS[name]['fn'](model, **args)
            except Exception as exc:  # report, never crash
                result = analytics._error(name, f'The calculation failed: {exc}')
    log.append({'tool': name, 'arguments': args, 'result': result.to_dict()})
    return result


# ------------------------------------------------------------ rules router
CHANNEL_WORDS = {
    'Website': ('website', 'online', 'web ', 'web-', 'internet', 'e-commerce', 'ecommerce'),
    'Brick & Mortar': ('brick', 'physical', 'in-store', 'in store', 'retail store',
                       'bricks'),
}


def _has(q: str, *words: str) -> bool:
    """True if any keyword appears at the START of a word, so 'declin' matches
    'declined' but 'earn' does not match 'meaning'."""
    return any(re.search(r'(?<![a-z])' + re.escape(w), q) for w in words)


def extract_params(question: str, model: dict) -> dict:
    """Pull years, a store, a category and a channel out of the question, using only
    values that exist in the LOADED data (so new stores or years work automatically).
    Years are passed through even if unknown, so the tool can say they don't exist."""
    q = ' ' + question.lower() + ' '
    fact = model['fact']
    found: dict = {}

    years = [int(y) for y in re.findall(r'\b(20\d\d)\b', q)]
    if years:
        found['years'] = years

    ids = [s for s in fact['Store ID'].dropna().unique()
           if re.search(rf'\b{re.escape(str(s).lower())}\b', q)]
    if ids:
        found['store'] = str(ids[0])
    else:
        for city in sorted(fact['City'].dropna().unique(), key=len, reverse=True):
            if re.search(rf'\b{re.escape(city.lower())}\b', q):
                found['store'] = city      # the tool rejects a city with two stores
                break

    for cat in sorted(fact['Category'].dropna().unique(), key=len, reverse=True):
        c = cat.lower()
        singular = c[:-3] + 'y' if c.endswith('ies') else c.rstrip('s')
        if c in q or re.search(rf'\b{re.escape(singular)}\b', q):
            found['category'] = cat
            break

    loaded_channels = set(fact['Channel'].dropna().unique())
    for channel, words in CHANNEL_WORDS.items():
        if channel in loaded_channels and _has(q, *words):
            found['channel'] = channel
            break
    return found


def _one_year(p: dict) -> dict:
    return {'year': p['years'][0]} if p.get('years') else {}


def _pick(p: dict, *keys: str) -> dict:
    return {k: p[k] for k in keys if k in p}


def rules_router(question: str, model: dict) -> dict:
    """Option B router: keyword rules choose the tool(s) and arguments.
    Returns {'calls': [(tool, args), ...], 'kind': ..., 'decline': text or None}."""
    q = question.lower()
    p = extract_params(question, model)
    judgment = _has(q, 'should', 'recommend', 'advice', 'advise', 'worth', 'close ', 'closing',
                    'shut', 'open a', 'invest')

    if _has(q, 'profit', 'margin', 'cost', 'expense', 'earnings before', 'net income', 'roi'):
        return {'kind': 'profit', 'calls': [], 'decline': (
            'I cannot answer that: the loaded data contains revenue only, with no costs, '
            'expenses or margins, so profitability cannot be calculated. Revenue is not profit: '
            'a high-revenue store can still lose money.')}
    if _has(q, 'forecast', 'predict', 'projection', 'next year', 'will be', 'future'):
        return {'kind': 'forecast', 'calls': [], 'decline': (
            'I cannot forecast. My tools only measure what happened in the loaded data; they '
            'do not project future revenue.')}

    if _has(q, 'quality', 'missing', 'blank', 'duplicate', 'null', 'error in the data',
            'data problem', 'data issue'):
        return {'kind': 'quality', 'calls': [('get_data_quality_report', {})], 'decline': None}

    if _has(q, 'satisf', 'survey', 'interest score', 'customer happiness', 'happy', 'rating'):
        return {'kind': 'satisfaction', 'decline': None,
                'calls': [('get_satisfaction_vs_revenue', _one_year(p))]}

    yearly_words = ('by year', 'each year', 'per year', 'annual', 'yearly', 'year over year',
                    'year-over-year', 'every year')
    if _has(q, *yearly_words) and not _has(q, 'which', 'most', 'greatest', 'largest'):
        return {'kind': 'yearly', 'decline': None, 'calls': [(
            'get_revenue_by_year', _pick(p, 'store', 'category', 'channel'))]}

    growth_words = ('grow', 'grew', 'growth', 'declin', 'decrease', 'increase', 'drop', 'fell',
                    'fall', 'change', 'trend', 'improv', 'worse', 'shrink', 'gain', 'lost')
    if _has(q, *growth_words) or (judgment and 'store' in p):
        if 'store' in p:   # one store's trend over the years
            calls = [('get_revenue_by_year', _pick(p, 'store', 'category'))]
            if judgment:   # put the store in context: how did every store change?
                calls.append(('get_growth', {'by': 'store'}))
            return {'kind': 'judgment' if judgment else 'store_trend', 'calls': calls,
                    'decline': None}
        if _has(q, 'channel') or ('channel' in p and 'store' not in q):
            by = 'channel'
        elif _has(q, 'categor', 'product'):
            by = 'category'
        else:
            by = 'store'
        args = {'by': by, **_pick(p, 'category')}
        if by != 'channel':
            args.update(_pick(p, 'channel'))
        years = sorted(set(p.get('years', [])))
        if len(years) >= 2:
            args.update({'start_year': years[0], 'end_year': years[-1]})
        return {'kind': 'judgment' if judgment else 'growth', 'decline': None,
                'calls': [('get_growth', args)]}

    if _has(q, 'month', 'season', 'quarter', 'busiest', 'slowest', 'holiday', 'peak'):
        return {'kind': 'monthly', 'decline': None, 'calls': [(
            'get_monthly_revenue', {**_one_year(p), **_pick(p, 'store', 'category', 'channel')})]}

    if _has(q, 'categor', 'product', 'best-selling', 'best selling', 'top selling') \
            and 'category' not in p:
        return {'kind': 'category', 'decline': None, 'calls': [(
            'get_category_performance', {**_one_year(p), **_pick(p, 'store', 'channel')})]}

    if _has(q, 'channel', ' vs', 'versus', 'compare', 'compared', 'split', 'share') \
            and _has(q, 'website', 'online', 'brick', 'channel', 'physical'):
        return {'kind': 'channel', 'decline': None, 'calls': [(
            'get_revenue_by_channel', {**_one_year(p), **_pick(p, 'store', 'category')})]}

    # A store or year alone is not enough ("weather in Denver"): a revenue word is required.
    if _has(q, 'revenue', 'sales', 'how much', 'total', 'earn', 'generate', 'made', 'make',
            'sold', 'sell', 'income', 'perform'):
        return {'kind': 'judgment' if judgment else 'total', 'decline': None, 'calls': [(
            'get_total_revenue', {**_one_year(p), **_pick(p, 'store', 'category', 'channel')})]}

    return {'kind': 'unsupported', 'calls': [], 'decline': UNSUPPORTED}


# ------------------------------------------------- language-model router
# gemini-2.5-flash was closed to new users (404) on 2026-11-10; Google's error named this one.
DEFAULT_LLM_MODEL = 'gemini-3.8-flash'
MAX_TOOL_ROUNDS = 4  # the model may ask for tools at most this many times per question

ANSWER_FORMAT = """Answer in exactly this format, with nothing before it:
FINDINGS:
- one bullet per fact, each number copied from a tool result; write money as $1,234,567.89
  and percentages as 12.34%. Do not repeat the scope here; the app already shows it.
INTERPRETATION:
- what the findings may mean, cautiously; association is not causation
NEXT STEPS:
- what to check next, or "No recommendation is supported by this data alone." plus the missing information
If no tool can answer the question, write under FINDINGS that you cannot answer it and list what you can answer."""


class LLMUnavailable(RuntimeError):
    """The language model could not be used (no key, API error, quota). Caller falls back."""


def tool_declarations(model: dict) -> list[dict]:
    """Describe each approved tool to the model. Every parameter is limited to values
    that exist in the LOADED data, so the model cannot invent a store or year."""
    fact = model['fact']
    years = [str(int(y)) for y in sorted(fact['Year'].dropna().unique())]
    allowed = {
        'year': (years, 'Calendar year. Omit for all years.'),
        'start_year': (years, 'First year to compare. Omit for the earliest year.'),
        'end_year': (years, 'Last year to compare. Omit for the latest year.'),
        'store': (sorted(fact['Store Label'].dropna().unique()),
                  'One store, as "ID City". Omit for all stores.'),
        'category': (sorted(fact['Category'].dropna().unique()), 'Product category. Omit for all.'),
        'channel': (sorted(fact['Channel'].dropna().unique()), 'Sales channel. Omit for all.'),
        'by': (list(analytics.GROWTH_DIMENSIONS), 'What to rank: store, channel or category.'),
    }
    decls = []
    for name, spec in TOOLS.items():
        props = {p: {'type': 'STRING', 'enum': [str(v) for v in allowed[p][0]],
                     'description': allowed[p][1]} for p in sorted(spec['params'])}
        decl = {'name': name, 'description': spec['description']}
        if props:
            decl['parameters'] = {'type': 'OBJECT', 'properties': props}
        decls.append(decl)
    return decls


def _numbers_in(obj) -> set[float]:
    """Every number inside a tool result (values, scope, rows used), as floats."""
    found: set[float] = set()
    if isinstance(obj, bool) or obj is None:
        return found
    if isinstance(obj, (int, float)):
        found.add(float(obj))
    elif isinstance(obj, str):
        found |= {n for n, _ in _numbers_in_text(obj)}
    elif isinstance(obj, dict):
        for k, v in obj.items():
            found |= _numbers_in(k) | _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            found |= _numbers_in(v)
    return found


_NUM = re.compile(r'(?<![A-Za-z])(-?\d[\d,]*(?:\.\d+)?)\s*(million|m\b|k\b|thousand)?', re.I)


_HEDGE = re.compile(r'(about|around|roughly|nearly|almost|approximately|approx\.?|~|close to|'
                    r'just over|just under|over|under)\s*\$?\s*$', re.I)


def _numbers_in_text(text: str, with_hedge: bool = False) -> list:
    """Numbers written in text, e.g. '$6,339,640.00', '-66.81%', '$6.34 million'.
    with_hedge=True also says whether the number follows a word like 'about'."""
    out = []
    for m in _NUM.finditer(text):
        raw, unit = m.group(1).replace(',', ''), (m.group(2) or '').lower()
        try:
            x = float(raw)
        except ValueError:
            continue
        mult = {'million': 1e6, 'm': 1e6, 'k': 1e3, 'thousand': 1e3}.get(unit, 1)
        hedged = bool(_HEDGE.search(text[max(0, m.start() - 20):m.start()]))
        out.append((x * mult, m.group(0).strip(), hedged) if with_hedge else (x * mult, m.group(0).strip()))
    return out


def unsupported_numbers(text: str, tool_log: list, question: str) -> list[str]:
    """Numbers in the model's text that do NOT come from any tool result (or the
    question). Rounded versions of a tool number count as supported."""
    known = set()
    for call in tool_log:
        known |= _numbers_in(call['result']) | _numbers_in(call['arguments'])
    known |= {n for n, _ in _numbers_in_text(question)}
    bad = []
    for x, shown, hedged in _numbers_in_text(text, with_hedge=True):
        if abs(x) <= 12 and x == int(x):      # list markers, "5 categories", month counts
            continue
        # Compare sizes: "a 66.81% decline" is the tool's -66.81. Accept the tool number
        # rounded to 0-2 decimals or abbreviated ("$6.34 million"); a number marked as
        # approximate ("about 70%" for 70.68) may be up to 3% off.
        tolerance = 0.03 if hedged else 0.005
        ok = any(abs(abs(x) - abs(k)) <= max(0.006, abs(k) * tolerance)
                 or any(abs(round(abs(k), d) - abs(x)) < 1e-9 for d in (0, 1, 2))
                 for k in known)
        if not ok:
            bad.append(shown)
    return bad


def _sections(text: str) -> dict[str, list[str]]:
    """Split the model's reply into FINDINGS / INTERPRETATION / NEXT STEPS bullet lists."""
    parts = {'findings': [], 'interpretation': [], 'next_steps': []}
    current = 'findings'
    heads = {'FINDINGS': 'findings', 'INTERPRETATION': 'interpretation', 'NEXT STEPS': 'next_steps'}
    for line in (text or '').splitlines():
        s = line.strip().strip('*#').strip()
        head = s.rstrip(':').strip().upper()
        if head in heads:
            current = heads[head]
            continue
        s = re.sub(r'^[-*•]\s*', '', line.strip())
        if s:
            parts[current].append(s)
    return parts


RETRY_DELAYS = (3, 6)  # seconds to wait before each retry of a temporary server error
TIME_BUDGET = 60        # seconds for the whole language-model answer; then the rules answer
REQUEST_TIMEOUT_MS = 25_000  # one API request; used when the app creates the client
_TRANSIENT = ('503', 'UNAVAILABLE', '500', 'INTERNAL', 'DEADLINE_EXCEEDED', 'overloaded',
              'high demand')


def _is_transient(exc) -> bool:
    """A temporary server problem (overload, outage) that is worth retrying. Quota errors
    (429) are not: retrying them a few seconds later does not help."""
    return any(t.lower() in str(exc).lower() for t in _TRANSIENT)


class OutOfTime(RuntimeError):
    """The language model did not finish within TIME_BUDGET seconds."""


def _check_time(deadline: float):
    if time.monotonic() > deadline:
        raise OutOfTime(f'no answer within {TIME_BUDGET} s')


def _generate(client, model_name, contents, config, deadline: float):
    """One model call, retried after a short wait if Google reports a temporary error,
    but never past the overall deadline."""
    for delay in (*RETRY_DELAYS, None):
        _check_time(deadline)
        try:
            return client.models.generate_content(model=model_name, contents=contents,
                                                  config=config)
        except Exception as exc:
            if delay is None or not _is_transient(exc) or time.monotonic() + delay > deadline:
                raise
            time.sleep(delay)


def newest_flash_model(client, exclude: str | None = None) -> str | None:
    """Ask the API which models this key can use and pick the newest general 'flash'
    model (not lite/image/audio variants), other than `exclude`. Used only when the
    configured model is gone or stays overloaded."""
    def version(name):
        m = re.search(r'gemini-(\d+(?:\.\d+)?)', name)
        return float(m.group(1)) if m else 0.0
    names = []
    for m in client.models.list():
        name = getattr(m, 'name', '').split('/')[-1]
        actions = getattr(m, 'supported_actions', None) or ['generateContent']
        if ('flash' in name and name != exclude and 'generateContent' in actions and not any(
                bad in name for bad in ('lite', 'image', 'live', 'tts', 'audio', 'exp', 'preview'))):
            names.append(name)
    return max(names, key=version) if names else None


def llm_answer(question: str, model: dict, client, model_name: str = DEFAULT_LLM_MODEL,
               dashboard_scope: str = '') -> tuple[dict, list, str]:
    """Like _llm_answer_once, but if the model no longer exists (404) or is still
    overloaded after retries (503), switch once to the newest OTHER flash model.
    Returns (sections, tool_log, model_name_used)."""
    deadline = time.monotonic() + TIME_BUDGET
    try:
        parts, log = _llm_answer_once(question, model, client, model_name, dashboard_scope,
                                      deadline)
        return parts, log, model_name
    except LLMUnavailable as exc:
        gone = 'NOT_FOUND' in str(exc) or '404' in str(exc)
        if not (gone or _is_transient(exc)) or time.monotonic() > deadline:
            raise
        try:
            replacement = newest_flash_model(client, exclude=model_name)
        except Exception:
            replacement = None
        if not replacement:
            raise
        parts, log = _llm_answer_once(question, model, client, replacement, dashboard_scope,
                                      deadline)
        return parts, log, replacement


def _llm_answer_once(question: str, model: dict, client, model_name: str,
                     dashboard_scope: str = '', deadline: float | None = None) -> tuple[dict, list]:
    """Option A: the language model chooses tools by function calling. OUR dispatcher
    runs each requested tool and logs it; the model only sees the results and writes
    the explanation. Raises LLMUnavailable on any API problem so the caller can fall back."""
    from google.genai import types  # imported here so the rules mode never needs it

    log: list = []
    note = (f' The user\'s dashboard filters ({dashboard_scope}) do NOT apply to your tools; '
            'pass parameters explicitly.' if dashboard_scope else '')
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT + '\n' + ANSWER_FORMAT + note,
        tools=[types.Tool(function_declarations=tool_declarations(model))],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0)
    contents = [types.Content(role='user', parts=[types.Part(text=question)])]
    deadline = deadline or time.monotonic() + TIME_BUDGET
    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = _generate(client, model_name, contents, config, deadline)
            calls = response.function_calls or []
            if not calls:
                return _sections(response.text or ''), log
            contents.append(response.candidates[0].content)
            replies = []
            for fc in calls:
                args = {k: v for k, v in dict(fc.args or {}).items() if v not in (None, '')}
                result = run_tool(fc.name, args, model, log)
                replies.append(types.Part.from_function_response(
                    name=fc.name, response={'result': result.to_dict()}))
            contents.append(types.Content(role='user', parts=replies))
    except Exception as exc:  # network, bad key, quota (429), model not found, ...
        raise LLMUnavailable(f'{type(exc).__name__}: {str(exc)[:200]}') from exc
    raise LLMUnavailable(f'The model kept requesting tools after {MAX_TOOL_ROUNDS} rounds.')


# ------------------------------------------------------- writing the answer
def _usd(x) -> str:
    return 'n/a' if x is None else f'${x:,.2f}'


def _pct(x) -> str:
    return 'n/a' if x is None else f'{x:+.2f}%'


def _scope_text(result: ToolResult) -> str:
    if result.error:
        return 'not calculated (see Findings)'
    parts = [f'{k}: {v}' for k, v in result.scope.items()]
    return ', '.join(parts) if parts else 'all loaded data'


def findings_lines(result: ToolResult) -> list[str]:
    """Turn a tool result into plain sentences. Every number here comes straight
    from result.value; nothing is calculated or remembered."""
    if result.error:
        return [f'The calculation could not be completed: {result.error}']
    v, t = result.value, result.tool
    if t == 'get_total_revenue':
        return [f'Revenue: **{_usd(v)}** from {result.rows_used:,} sales rows.']
    if t == 'get_revenue_by_channel':
        lines = [f'{ch}: **{_usd(d["revenue"])}** ({d["share_of_total_pct"]}% of the total)'
                 for ch, d in v['channels'].items()]
        return lines + [f'Total across channels: {_usd(v["total_revenue"])}.']
    if t == 'get_revenue_by_year':
        return [f'{yr}: **{_usd(d["revenue"])}**' + (
            f' ({_pct(d["change_vs_prior_year_pct"])} vs prior year)'
            if d['change_vs_prior_year_pct'] is not None else '') for yr, d in v.items()]
    if t == 'get_growth':
        groups = v['groups_ranked_by_change_pct']
        if not groups:
            return ['No groups had revenue in both years, so no change could be measured.']
        years = [k.split('_')[1] for k in groups[0] if k.startswith('revenue_')]
        a, b = years
        show = groups if len(groups) <= 6 else groups[:3] + groups[-3:]
        lines = [f'{g["group"]}: {_usd(g[f"revenue_{a}"])} in {a} → {_usd(g[f"revenue_{b}"])} '
                 f'in {b} ({_pct(g["change_pct"])})' for g in show]
        if len(groups) > 6:
            lines.insert(3, f'... {len(groups) - 6} more in the tool-call log ...')
        lines.append(f'Largest increase: **{v["largest_increase"] or "none (nothing grew)"}**.')
        lines.append(f'Largest decline: **{v["largest_decline"] or "none (nothing declined)"}**'
                     f'; {v["number_declined"]} of {len(groups)} declined.')
        return lines
    if t == 'get_monthly_revenue':
        lines = [f'{m["month"]}: {_usd(m["revenue"])} ({m["share_pct"]}%)' for m in v['months']]
        if v.get('highest_month'):
            lines.append(f'Highest month: **{v["highest_month"]}**; lowest: '
                         f'**{v["lowest_month"]}**.')
        return lines
    if t == 'get_category_performance':
        return [f'{c["rank"]}. {c["category"]}: **{_usd(c["revenue"])}** ({c["share_pct"]}%)'
                for c in v['categories']]
    if t == 'get_satisfaction_vs_revenue':
        hi, lo = v['highest_satisfaction'], v['lowest_satisfaction']
        return [f'Store-years compared: {v["store_years_compared"]}.',
                f'Correlation of satisfaction with revenue: **{v["correlation_satisfaction_revenue"]}** '
                f'({v["satisfaction_relationship"]}).',
                f'Correlation of interest with revenue: {v["correlation_interest_revenue"]} '
                f'({v["interest_relationship"]}).',
                f'Highest satisfaction: {hi["store_year"]} ({hi["satisfaction"]}, revenue {_usd(hi["revenue"])}); '
                f'lowest: {lo["store_year"]} ({lo["satisfaction"]}, revenue {_usd(lo["revenue"])}).']
    if t == 'get_data_quality_report':
        lines = [f'Sales rows loaded: {v["sales_rows"]:,}.']
        lines += [f'Issue: {i}' for i in v['issues_found']]
        changed = [c['merge'] for c in v['merge_checks'] if c['changed']]
        lines.append('Joins: ' + (f'{changed} changed rows or revenue.' if changed else
                                  'no join changed the row count or revenue total.'))
        for table, blanks in v['blank_values'].items():
            for b in blanks:
                lines.append(f'Blank {table}.{b["column"]}: {b["blank_count"]} '
                             f'(rows: {b["rows (by key)"]})')
        dupes = {t: n for t, n in v['duplicate_rows'].items() if n}
        lines.append(f'Duplicate rows: {dupes if dupes else "none"}.')
        return lines
    return [f'{result.definition}: {v}']


def interpretation_lines(kind: str, result: ToolResult) -> list[str]:
    """Careful, rule-based reading of the result. Labeled as interpretation, not fact."""
    if result.error:
        return []
    v, out = result.value, []
    if result.tool == 'get_growth':
        if v['largest_decline']:
            out.append(f'{v["largest_decline"]} fell the most in % terms. The data shows *that* '
                       'revenue changed, not *why* (prices, traffic, staffing, competition and '
                       'local conditions are not in the data).')
        else:
            out.append('Nothing declined over this period, so there is no "largest decline" to report.')
    if result.tool == 'get_satisfaction_vs_revenue':
        out.append(f'The relationship is {v["satisfaction_relationship"]}. This is an association '
                   'across store-years, not evidence that satisfaction causes revenue (or the reverse); '
                   'larger or busier stores may differ in both.')
    if result.tool == 'get_revenue_by_year' and len(v) >= 2:
        yrs = list(v)
        first, last = v[yrs[0]]['revenue'], v[yrs[-1]]['revenue']
        direction = 'higher' if last > first else 'lower' if last < first else 'the same'
        out.append(f'Revenue in {yrs[-1]} is {direction} than in {yrs[0]} for this scope.')
    out += [c for c in result.caveats]
    return out


def next_steps_lines(kind: str, result: ToolResult | None) -> list[str]:
    if kind in ('judgment', 'profit'):
        return [NO_RECOMMENDATION]
    if result is not None and result.error:
        return ['Rephrase using one of the values listed above.']
    if kind == 'growth' and result is not None and result.value.get('largest_decline'):
        return [f'Look at the year-by-year trend before drawing conclusions, e.g. "Show '
                f'{result.value["largest_decline"]} revenue by year"; two end years can hide '
                'what happened in between.']
    return {
        'growth': ['Look at the year-by-year trend before drawing conclusions; two end years '
                   'can hide what happened in between.'],
        'store_trend': ['Compare with other stores ("Which store declined most?").'],
        'satisfaction': ['Collect more data (costs, traffic, store size) before treating '
                         'satisfaction as a lever for revenue.'],
        'quality': ['Fix or confirm the listed blanks at the source, then reload the files.'],
    }.get(kind, ['No recommendation is supported by this data alone; ask a follow-up '
                 'comparison to dig deeper.'])


def _filters_note(dashboard_scope: str) -> str:
    note = ' Dashboard filters are **not** applied to the assistant'
    return note + (f' (current dashboard filters: {dashboard_scope}).' if dashboard_scope else '.')


def answer_question(question: str, model: dict, mode: str = 'rules', data_note: str = '',
                    dashboard_scope: str = '', client=None,
                    model_name: str = DEFAULT_LLM_MODEL) -> dict:
    """mode='llm': ask the language model (with our tools); if it is unavailable, fall back
    to the rules. mode='rules': rules-based assistant only."""
    if mode == 'llm':
        if client is None:
            answer = _rules_answer(question, model, data_note, dashboard_scope)
            answer['mode'] += ' (fallback: no language-model API key configured)'
            return answer
        try:
            return _llm_answer_dict(question, model, client, model_name, data_note,
                                    dashboard_scope)
        except LLMUnavailable as exc:
            answer = _rules_answer(question, model, data_note, dashboard_scope)
            answer['mode'] += f' (fallback: language model unavailable: {exc})'
            return answer
    return _rules_answer(question, model, data_note, dashboard_scope)


def _llm_answer_dict(question, model, client, model_name, data_note, dashboard_scope) -> dict:
    """Run the model, then CHECK it: any number in its text that is not in a tool result
    means its Findings are replaced by ones written directly from the tool results."""
    parts, log, used = llm_answer(question, model, client, model_name, dashboard_scope)
    if used != model_name:
        model_name = f'{used}; configured model {model_name} was unavailable'
    results = [ToolResult(**c['result']) for c in log]
    scopes = [_scope_text(r) for r in results]
    scope = ('; '.join(scopes) if scopes else 'no calculation was run')
    scope += (f'. Data: {data_note}' if data_note and log else '') + '.' + _filters_note(dashboard_scope)
    text = '\n'.join(parts['findings'] + parts['interpretation'] + parts['next_steps'])
    bad = unsupported_numbers(text, log, question)
    mode = f'Language-model agent (Option A, {model_name}, function calling)'
    findings, interpretation = parts['findings'], parts['interpretation']
    if bad:
        mode += (f'. Number check FAILED for {bad[:5]}: model text replaced by findings written '
                 'directly from the tool results')
        findings = [line for r in results for line in findings_lines(r)] or \
            ['The model gave numbers that no tool calculated, so its answer was withheld.']
        interpretation = list(dict.fromkeys(c for r in results for c in r.caveats))
    elif log:
        mode += '. Number check passed: every number matches a tool result'
    return {'mode': mode, 'kind': 'llm', 'tool_log': log, 'scope': scope,
            'findings': findings or ['(The model returned no findings.)'],
            'interpretation': interpretation,
            'next_steps': parts['next_steps'] or ['No recommendation is supported by this data alone.']}


def _rules_answer(question: str, model: dict, data_note: str = '',
                  dashboard_scope: str = '') -> dict:
    """Route the question with the rules, run the chosen tool(s), and assemble an answer
    with Scope, Findings, Interpretation and Next steps, plus the tool-call log."""
    log: list = []
    routed = rules_router(question, model)
    kind = routed['kind']
    note = _filters_note(dashboard_scope)
    base = {'mode': 'Rules-based assistant (Option B)', 'kind': kind, 'tool_log': log}

    if routed['decline']:
        return {**base, 'scope': 'no calculation was run.' + note,
                'findings': [routed['decline']], 'interpretation': [],
                'next_steps': next_steps_lines(kind, None) if kind != 'unsupported' else
                ['Try one of the questions listed above.']}

    findings, interpretation, scopes, last = [], [], [], None
    for name, args in routed['calls']:
        result = run_tool(name, args, model, log)
        scopes.append(_scope_text(result))
        findings += findings_lines(result)
        interpretation += interpretation_lines(kind, result)
        last = result
    scope = '; '.join(scopes) + (f'. Data: {data_note}' if data_note else '') + '.' + note
    return {**base, 'scope': scope, 'findings': findings,
            'interpretation': list(dict.fromkeys(interpretation)),
            'next_steps': next_steps_lines(kind, last)}
