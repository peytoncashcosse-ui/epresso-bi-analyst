"""Tests for the language-model agent, using a FAKE Gemini client so they run offline
and give the same result every time. The fake plays back scripted model replies."""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import agent  # noqa: E402
from test_analytics import model  # noqa: E402,F401  (reuse the tiny made-up data)


def call(name, **args):
    """A model reply that asks for one tool."""
    return SimpleNamespace(function_calls=[SimpleNamespace(name=name, args=args)],
                           candidates=[SimpleNamespace(content='(model turn)')], text=None)


def say(text):
    """A model reply with final text and no tool request."""
    return SimpleNamespace(function_calls=None, candidates=[], text=text)


class FakeClient:
    def __init__(self, *replies, error=None):
        self.replies, self.error, self.requests = list(replies), error, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.requests.append({'model': model, 'contents': contents, 'config': config})
        if self.error:
            raise self.error
        return self.replies.pop(0)


GOOD = """FINDINGS:
- Website revenue in 2026 was $300.00, from 1 sales row.
INTERPRETATION:
- This is revenue, not profit.
NEXT STEPS:
- No recommendation is supported by this data alone."""


def test_model_chooses_tool_and_our_code_runs_it(model):
    client = FakeClient(call('get_total_revenue', year='2026', channel='Website'), say(GOOD))
    out = agent.answer_question('Website revenue 2026?', model, mode='llm', client=client)
    assert out['tool_log'][0]['tool'] == 'get_total_revenue'
    assert out['tool_log'][0]['result']['value'] == 300          # calculated by OUR function
    assert out['findings'] == ['Website revenue in 2026 was $300.00, from 1 sales row.']
    assert 'Number check passed' in out['mode'] and 'Option A' in out['mode']
    assert out['scope'].startswith('year: 2026')
    # the tool result was sent back to the model in the second request
    assert len(client.requests) == 2


def test_invented_number_is_caught_and_replaced(model):
    lie = GOOD.replace('$300.00', '$450.00')
    client = FakeClient(call('get_total_revenue', year='2026', channel='Website'), say(lie))
    out = agent.answer_question('Website revenue 2026?', model, mode='llm', client=client)
    assert 'Number check FAILED' in out['mode'] and '450.00' in out['mode']
    assert '$300.00' in out['findings'][0]                       # from the tool, not the model


def test_rounded_and_abbreviated_numbers_are_accepted(model):
    text = 'FINDINGS:\n- B1 Orlando fell 25% (from $200 to $150).\nNEXT STEPS:\n- Check trends.'
    client = FakeClient(call('get_growth', by='store', category='Beans'), say(text))
    out = agent.answer_question('Which store declined?', model, mode='llm', client=client)
    assert 'Number check passed' in out['mode']


def test_api_error_falls_back_to_rules(model):
    client = FakeClient(error=RuntimeError('429 RESOURCE_EXHAUSTED quota'))
    out = agent.answer_question('How much revenue in 2025?', model, mode='llm', client=client)
    assert out['mode'].startswith('Rules-based') and 'RESOURCE_EXHAUSTED' in out['mode']
    assert '$400.00' in out['findings'][0]


def test_no_key_falls_back_to_rules(model):
    out = agent.answer_question('How much revenue in 2025?', model, mode='llm', client=None)
    assert 'no language-model API key' in out['mode']


def test_endless_tool_requests_are_stopped(model):
    replies = [call('get_total_revenue')] * (agent.MAX_TOOL_ROUNDS + 1)
    out = agent.answer_question('Total?', model, mode='llm', client=FakeClient(*replies))
    assert out['mode'].startswith('Rules-based') and 'kept requesting tools' in out['mode']


def test_model_cannot_call_unknown_tool_or_bad_store(model):
    client = FakeClient(call('run_python', code='1+1'),
                        call('get_total_revenue', store='Narnia'),
                        say('FINDINGS:\n- I could not calculate that.'))
    out = agent.answer_question('?', model, mode='llm', client=client)
    assert [c['result']['error'] is not None for c in out['tool_log']] == [True, True]


def test_tool_parameters_are_limited_to_loaded_values(model):
    decls = {d['name']: d for d in agent.tool_declarations(model)}
    props = decls['get_total_revenue']['parameters']['properties']
    assert props['year']['enum'] == ['2025', '2026']
    assert props['store']['enum'] == ['B1 Orlando', 'B2 Orlando', 'W Website']
    assert 'parameters' not in decls['get_data_quality_report']   # takes no arguments


@pytest.mark.parametrize('text, bad', [
    ('Revenue was $6.34 million', []),             # abbreviation of 6,339,640
    ('Revenue was $7.5 million', ['7.5 million']),
])
def test_number_check_on_text(text, bad):
    log = [{'arguments': {}, 'result': {'value': 6339640.0}}]
    assert agent.unsupported_numbers(text, log, '') == bad


def test_retired_model_switches_to_newest_flash(model):
    class Retiring(FakeClient):
        def generate_content(self, model, contents, config):
            if model == 'old-model':
                raise RuntimeError('404 NOT_FOUND: model is no longer available')
            return super().generate_content(model, contents, config)

        def list(self):
            names = ['gemini-3.8-flash', 'gemini-3.9-flash-lite', 'gemini-3.1-flash', 'gemini-3.9-pro']
            return [SimpleNamespace(name=f'models/{n}', supported_actions=['generateContent'])
                    for n in names]

    client = Retiring(call('get_total_revenue', year='2026', channel='Website'), say(GOOD))
    out = agent.answer_question('Website 2026?', model, mode='llm', client=client,
                                model_name='old-model')
    assert 'gemini-3.8-flash; configured model old-model was not available' in out['mode']
    assert client.requests[-1]['model'] == 'gemini-3.8-flash'

def test_whole_number_rounding_is_accepted():
    # Regression: the live model wrote "about 70%" for a 70.68% share and was rejected.
    log = [{'arguments': {}, 'result': {'value': {'share_of_total_pct': 70.68}}}]
    assert agent.unsupported_numbers('Website had about 70% of revenue', log, '') == []
    assert agent.unsupported_numbers('Website had about 75% of revenue', log, '') == ['75']
    assert agent.unsupported_numbers('Website had 70% of revenue', log, '') == ['70']   # not marked approximate