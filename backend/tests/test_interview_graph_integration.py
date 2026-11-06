"""Main interview entry: graph material is consumed and failures really fall back."""
import json
import pytest
from app.config import settings
from app.schemas.interview import InterviewState
from app.services import knowledge_retrieval as kr
from app.services.interviewer_engine import InterviewEngine
from app.services.graph_retrieval_runtime import _load_cached


class Model:
    def __init__(self):
        self.chain_prompts = []
        self.rerank_calls = 0

    def chat_json(self, system, user, **kwargs):
        if '目录：' in user:
            return {'scenes': [{'id': 'scene:shop', 'evidence': '商户', 'reason': '商户服务'}],
                    'concepts': [{'id': 'concept:agent', 'evidence': '智能体', 'reason': '智能体工具'}]}
        if '重排器' in system:
            self.rerank_calls += 1
            return {'ranking': [row['id'] for row in json.loads(user)['candidates']]}
        raise AssertionError('Unexpected model call')

    def chat_json_many(self, calls):
        self.chain_prompts = [user for _, user in calls]
        return [{'chains': [{'question': '智能体工具如何重试？', 'trigger': '失败', 'intent': '恢复'}]} for _ in calls]


@pytest.fixture
def engine_setup(monkeypatch, tmp_path):
    nodes = [{'id': 'concept:agent', 'name': '智能体', 'node_type': 'Concept'},
             {'id': 'concept:tools', 'name': '工具调用', 'node_type': 'Concept'},
             {'id': 'scene:shop', 'name': '商户服务', 'node_type': 'Scene'}]
    edges = [{'src_id': 'concept:agent', 'relation': 'HAS_SUBTOPIC', 'dst_id': 'concept:tools'}]
    for i in range(30):
        nodes.append({'id': f'q{i}', 'name': f'智能体工具执行第{i}类失败如何防止重复调用？', 'node_type': 'Question',
                      'properties': {'roles': ['agent_dev'], 'answer': str(i), 'original_tags': {'category': 'bagu'}}})
        edges.append({'src_id': f'q{i}', 'relation': 'TESTS', 'dst_id': 'concept:tools'})
        if i < 15:
            edges.append({'src_id': 'scene:shop', 'relation': 'HAS_QUESTION', 'dst_id': f'q{i}'})
    for name, rows in [('nodes.jsonl', nodes), ('edges.jsonl', edges)]:
        (tmp_path / name).write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf8')
    monkeypatch.setattr(settings, 'graph_snapshot_path', str(tmp_path))
    monkeypatch.setattr(settings, 'graph_retrieval_enabled', True)
    monkeypatch.setattr(settings, 'graph_rerank_enabled', True)
    _load_cached.cache_clear()
    engine = InterviewEngine(Model())
    monkeypatch.setattr(engine, '_filter_hits_by_llm', lambda roles, hits, **kw: hits)
    calls = []
    def retrieve(**kwargs):
        calls.append(kwargs)
        return [{'question': '智能体岗位如何设计工具参数校验与容错？', 'roles': ['agent_dev']}]
    monkeypatch.setattr(kr, 'retrieve', retrieve)
    monkeypatch.setattr(kr, 'search_questions', retrieve)
    def forbidden(*a, **kw): raise AssertionError('Legacy scene retrieval should not run')
    monkeypatch.setattr(kr, 'search_projects', forbidden)
    state = InterviewState(8, '', {'projects': [{'name': '商户智能体甲'}, {'name': '商户智能体乙'}]}, target_role='agent_dev')
    return engine, state, calls


def test_main_retrieval_uses_graph_and_chain_reuses_material(engine_setup, monkeypatch):
    engine, state, calls = engine_setup
    def forbidden(*a, **kw): raise AssertionError('Legacy B selector should not run')
    monkeypatch.setattr(engine, '_select_b_lane_query', forbidden)
    timings = {}
    engine._plan_retrieval(state, set(), timings)
    assert state.retrieval_diagnostics['backend'] == 'mgkg'
    assert '智能体工具执行' in state.retrieved_material
    assert engine.llm.rerank_calls == 2
    assert len(engine.llm.chain_prompts) == 2
    assert all('智能体工具执行' in user for user in engine.llm.chain_prompts)
    assert timings['graph_retrieval_s'] >= 0
    assert all(call.get('lane') != 'b' for call in calls)
    assert InterviewState.from_dict(state.to_dict()).retrieval_diagnostics == state.retrieval_diagnostics
    project_ids = engine._graph_project_question_ids
    bag = engine._graph_runtime.retrieve_bagu(domain_concept_ids=engine._graph_domain_concept_ids,
                                             exclude_question_ids=project_ids, roles=['agent_dev'], count=30)
    assert bag
    assert not ({h['graph_question_id'] for h in bag} & project_ids)


def test_missing_snapshot_calls_legacy_B(engine_setup, monkeypatch, tmp_path):
    engine, state, calls = engine_setup
    monkeypatch.setattr(settings, 'graph_snapshot_path', str(tmp_path / 'missing.zip'))
    chosen = []
    def fallback(*a, **kw):
        chosen.append(True)
        return ['商户服务'], ['Agent']
    monkeypatch.setattr(engine, '_select_b_lane_query', fallback)
    monkeypatch.setattr(kr, 'search_projects', lambda *a, **kw: [])
    engine._plan_retrieval(state, set())
    assert chosen
    assert any(call.get('lane') == 'b' for call in calls)
    assert state.retrieval_diagnostics['backend'] == 'legacy'
    assert state.retrieval_diagnostics['error'] == 'FileNotFoundError'
    assert engine._graph_runtime is None


def test_switch_off_makes_no_graph_model_calls(engine_setup, monkeypatch):
    engine, state, _ = engine_setup
    monkeypatch.setattr(settings, 'graph_retrieval_enabled', False)
    monkeypatch.setattr(engine, '_select_b_lane_query', lambda *a, **kw: ([], []))
    monkeypatch.setattr(kr, 'search_projects', lambda *a, **kw: [])
    engine._plan_retrieval(state, set())
    assert state.retrieval_diagnostics['backend'] == 'legacy'
    assert engine.llm.rerank_calls == 0


def test_seed_model_validation_failure_falls_back(engine_setup, monkeypatch):
    engine, state, calls = engine_setup
    monkeypatch.setattr(engine.llm, 'chat_json', lambda *a, **kw: {'scenes': [{'id': 'invented'}], 'concepts': []})
    monkeypatch.setattr(engine, '_select_b_lane_query', lambda *a, **kw: (['商户服务'], ['Agent']))
    monkeypatch.setattr(kr, 'search_projects', lambda *a, **kw: [])
    engine._plan_retrieval(state, set())
    assert state.retrieval_diagnostics['backend'] == 'legacy'
    assert state.retrieval_diagnostics['error'] == 'ValueError'
    assert any(call.get('lane') == 'b' for call in calls)


def test_graph_bagu_enters_existing_bank_question_flow(engine_setup, monkeypatch):
    engine, state, _ = engine_setup
    engine._plan_retrieval(state, set())
    def forbidden(*a, **kw): raise AssertionError('Legacy bagu recall should not run')
    monkeypatch.setattr(kr, 'pick_bagu_questions', forbidden)
    monkeypatch.setattr(engine, '_select_bagu_with_llm',
                        lambda rows, n, *a: [(rows[0], rows[0]['question'], '智能体工具恢复', '幂等')])
    items = engine._bagu_from_bank(1)
    assert len(items) == 1
    assert items[0]['from_bank'] is True
    assert items[0]['bank_question'].startswith('智能体工具执行')
