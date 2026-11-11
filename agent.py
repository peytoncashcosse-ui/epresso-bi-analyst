"""Assistant: a dispatcher plus a router.
The router (rules now, a language model later) only CHOOSES a tool and its
arguments. Our code RUNS the tool. Nothing here executes model-written code."""
from __future__ import annotations

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

UNSUPPORTED = ('I can only answer questions that my approved analytical functions can '
               'calculate from the loaded data: ' + ', '.join(TOOLS) + '. '
               'I cannot answer that one.')

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


def rules_router(question: str, model: dict):
    """Option B router (temporary: full rules come in the next step).
    Returns (tool_name, arguments) or None if the question is unsupported."""
    q = question.lower()
    if any(w in q for w in ('missing', 'duplicate', 'quality', 'blank')):
        return 'get_data_quality_report', {}
    if 'revenue' in q or 'sales' in q:
        return 'get_total_revenue', {}
    return None


def llm_router(question: str, df):
    """Option A router. TODO: after the rules-based version works, ask a model that
    supports function calling to choose from TOOLS. Return (name, args) or None."""
    raise NotImplementedError('Add the language-model router after your tools are tested.')


def format_findings(result: ToolResult) -> str:
    if result.error:
        return f'The request could not be completed: {result.error}'
    return f'{result.definition}: {result.value}  (rows used: {result.rows_used})'


def answer_question(question: str, model: dict, mode: str = 'rules') -> dict:
    log: list = []
    routed = rules_router(question, model) if mode == 'rules' else llm_router(question, model)
    if routed is None:
        return {'scope': 'n/a', 'findings': UNSUPPORTED, 'interpretation': '',
                'next_steps': '', 'tool_log': log}
    name, args = routed
    result = run_tool(name, args, model, log)
    return {
        'scope': str(result.scope),
        'findings': format_findings(result),
        'interpretation': ' '.join(result.caveats),
        'next_steps': '',
        'tool_log': log,
    }
