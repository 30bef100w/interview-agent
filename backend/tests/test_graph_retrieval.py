"""Behavioral checks for bounded graph retrieval; fixtures use explicit edges."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'app/services/graph_retrieval.py'
SPEC = importlib.util.spec_from_file_location('graph_retrieval_v1_test', SCRIPT)
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def node(nid, kind='Concept', state='active', **props):
    return {'id': nid, 'name': nid, 'node_type': kind, 'state': state, 'properties': props}


def edge(src, rel, dst, state='active'):
    return {'src_id': src, 'relation': rel, 'dst_id': dst, 'state': state}


def question(qid, **props):
    return node(qid, 'Question', **props)


def cfg(**kwargs):
    defaults = dict(kg_candidate_limit=6, mg_candidate_limit=4, final_limit=4,
                    kg_final_quota=2, mg_final_quota=2, questions_per_turn=1)
    defaults.update(kwargs)
    return m.GraphRetrievalConfig(**defaults)


class GraphRetrievalTests(unittest.TestCase):
    def retriever(self, nodes, edges, **kwargs):
        return m.GraphRetriever(m.GraphIndex(nodes, edges, **kwargs))

    def test_both_routes_run_and_scene_does_not_disable_mg(self):
        r = self.retriever([node('s', 'Scene'), node('c'), question('qs'), question('qm')],
                           [edge('s', 'HAS_QUESTION', 'qs'), edge('qm', 'TESTS', 'c')])
        out = r.project_retrieve(m.ProjectQuery(scene_ids=('s',), concept_ids=('c',)), config=cfg())
        self.assertEqual({q['question_id'] for q in out['questions']}, {'qs', 'qm'})
        self.assertEqual(out['meta']['assigned_by_lane'], {'kg': 1, 'mg': 1})
        self.assertTrue(next(q for q in out['questions'] if q['question_id'] == 'qs')['direct_scene'])

    def test_no_scene_or_empty_scene_recycles_capacity_to_mg(self):
        nodes = [node('s', 'Scene'), node('c')] + [question(f'q{i}') for i in range(12)]
        edges = [edge(f'q{i}', 'TESTS', 'c') for i in range(12)]
        r = self.retriever(nodes, edges)
        for scenes in ((), ('s',)):
            out = r.project_retrieve(m.ProjectQuery(scene_ids=scenes, concept_ids=('c',)), config=cfg(), seed=3)
            self.assertEqual(out['meta']['unique_candidates'], 10)
            self.assertEqual(len(out['questions']), 4)
            self.assertEqual(out['meta']['assigned_by_lane'], {'mg': 4})

    def test_identity_overlap_is_merged_and_capacity_is_refilled(self):
        nodes = [node('s', 'Scene'), node('c')] + [question(f'q{i}') for i in range(12)]
        edges = [edge(f'q{i}', 'TESTS', 'c') for i in range(12)] + [edge('s', 'HAS_QUESTION', f'q{i}') for i in range(3)]
        r = self.retriever(nodes, edges)
        out = r.project_retrieve(m.ProjectQuery(scene_ids=('s',), concept_ids=('c',)), config=cfg(), seed=4)
        self.assertEqual(out['meta']['unique_candidates'], 10)
        self.assertGreater(out['meta']['trace'].get('duplicate_hits', 0), 0)
        overlap = [q for q in out['candidates'] if len(q['channels']) == 2]
        self.assertTrue(overlap)
        self.assertEqual(len({q['canonical_question_id'] for q in out['questions']}), len(out['questions']))
        self.assertEqual(sum(out['meta']['assigned_by_lane'].values()), len(out['questions']))

    def test_depth_zero_gets_non_leaf_direct_questions_and_never_walks_back_to_scenes(self):
        nodes = [node('s', 'Scene'), node('other', 'Scene'), node('root'), node('child'),
                 question('q0'), question('q1'), question('foreign')]
        edges = [edge('s', 'INVOLVES', 'root'), edge('root', 'HAS_SUBTOPIC', 'child'),
                 edge('q0', 'TESTS', 'root'), edge('q1', 'TESTS', 'child'),
                 edge('other', 'INVOLVES', 'root'), edge('other', 'HAS_QUESTION', 'foreign')]
        r = self.retriever(nodes, edges)
        out = r.project_retrieve(m.ProjectQuery(scene_ids=('s',)), config=cfg(max_depth=0))
        self.assertEqual([q['question_id'] for q in out['questions']], ['q0'])
        path = out['questions'][0]['paths'][0]['steps']
        self.assertEqual([s['relation'] for s in path], ['INVOLVES', 'TESTS'])
        self.assertEqual(path[0]['src_id'], 's')

    def test_bfs_is_layer_first_and_path_endpoints_match_actual_edges(self):
        nodes = [node('root'), node('a'), node('b'), node('aa')] + [question(q) for q in ('qroot', 'qa', 'qb', 'qaa')]
        edges = [edge('root','HAS_SUBTOPIC','a'), edge('root','HAS_SUBTOPIC','b'), edge('a','HAS_SUBTOPIC','aa'),
                 edge('qroot','TESTS','root'), edge('qa','TESTS','a'), edge('qb','TESTS','b'), edge('qaa','TESTS','aa')]
        r = self.retriever(nodes, edges)
        out = r.project_retrieve(m.ProjectQuery(concept_ids=('root',)), config=cfg(kg_candidate_limit=0, mg_candidate_limit=3), seed=2)
        self.assertEqual({q['question_id'] for q in out['candidates']}, {'qroot','qa','qb'})
        for q in out['candidates']:
            for path in q['paths']:
                for step in path['steps']:
                    self.assertIn((step['src_id'], step['relation'], step['dst_id']), r.graph.edge_states)
                self.assertEqual(path['steps'][-1]['src_id'], q['question_id'])

    def test_children_branch_depth_and_shared_global_node_budget(self):
        nodes = [node('s', 'Scene'), node('root'), node('mgroot')]
        edges = [edge('s','INVOLVES','root')]
        for prefix, parent in [('k','root'), ('m','mgroot')]:
            for i in range(8):
                child = f'{prefix}{i}'; grand = child + 'x'
                nodes.extend([node(child), node(grand), question('q'+child), question('q'+grand)])
                edges.extend([edge(parent,'HAS_SUBTOPIC',child), edge(child,'HAS_SUBTOPIC',grand),
                              edge('q'+child,'TESTS',child), edge('q'+grand,'TESTS',grand)])
        r = self.retriever(nodes, edges)
        out = r.project_retrieve(m.ProjectQuery(scene_ids=('s',), concept_ids=('mgroot',)),
                                 config=cfg(max_children_per_node=2, max_nodes_per_branch=1, max_concept_nodes=5), seed=7)
        self.assertLessEqual(out['meta']['unique_concepts_expanded'], 5)
        self.assertTrue(all(not q['question_id'].endswith('x') for q in out['questions']))
        self.assertGreater(out['meta']['trace'].get('child_limit_hits',0),0)

    def test_large_parent_question_pool_does_not_starve_children(self):
        nodes=[node('root'),node('child'),question('childq')]
        edges=[edge('root','HAS_SUBTOPIC','child'),edge('childq','TESTS','child')]
        for i in range(50):
            nodes.append(question(f'parent{i}'));edges.append(edge(f'parent{i}','TESTS','root'))
        r=self.retriever(nodes,edges)
        out=r.project_retrieve(m.ProjectQuery(concept_ids=('root',)),
                               config=cfg(kg_candidate_limit=0,mg_candidate_limit=3),seed=1)
        self.assertIn('childq',{q['question_id'] for q in out['candidates']})
        self.assertEqual(out['meta']['unique_candidates'],3)

    def test_checks_budget_bounds_duplicate_and_filtered_scanning(self):
        nodes = [node('root')] + [question(f'q{i}') for i in range(30)]
        edges = [edge(f'q{i}','TESTS','root') for i in range(30)]
        r = self.retriever(nodes, edges)
        out = r.project_retrieve(m.ProjectQuery(concept_ids=('root',)), config=cfg(max_question_checks=5),
                                 asked_question_ids=[f'q{i}' for i in range(30)], seed=1)
        self.assertEqual(out['questions'], [])
        self.assertEqual(out['meta']['trace']['question_checks'], 5)
        self.assertEqual(out['meta']['stop_reason'], 'question_check_limit')

    def test_fixed_seed_reproducible_and_seeds_change_sampling(self):
        nodes = [node('root')] + [question(f'q{i}') for i in range(100)]
        edges = [edge(f'q{i}','TESTS','root') for i in range(100)]
        r = self.retriever(nodes, edges); query = m.ProjectQuery(concept_ids=('root',))
        a = r.project_retrieve(query,config=cfg(),seed=1)
        self.assertEqual(a,r.project_retrieve(query,config=cfg(),seed=1))
        self.assertNotEqual(a['questions'],r.project_retrieve(query,config=cfg(),seed=2)['questions'])

    def test_overlapping_quota_matching_and_direct_scene_guarantee(self):
        # Top overlapping candidates cannot consume both quota reservations.
        nodes = [node('s','Scene'),node('c'),question('direct'),question('overlap1'),question('overlap2'),question('mg')]
        edges = [edge('s','HAS_QUESTION','direct'),edge('s','HAS_QUESTION','overlap1'),edge('s','HAS_QUESTION','overlap2'),
                 edge('overlap1','TESTS','c'),edge('overlap2','TESTS','c'),edge('mg','TESTS','c')]
        r=self.retriever(nodes,edges)
        out=r.project_retrieve(m.ProjectQuery(scene_ids=('s',),concept_ids=('c',)),config=cfg(),seed=1)
        self.assertEqual(out['meta']['assigned_by_lane'],{'kg':2,'mg':2})
        self.assertTrue(any(q['direct_scene'] for q in out['questions']))
        self.assertEqual(len(out['questions']),4)

    def test_company_is_a_bonus_not_filter_and_history_uses_actual_time(self):
        now = datetime(2026,11,6,tzinfo=timezone.utc)
        nodes=[node('c'),question('co',company='target'),question('other',company='other'),question('plain')]
        edges=[edge(x,'TESTS','c') for x in ('co','other','plain')]
        r=self.retriever(nodes,edges);query=m.ProjectQuery(concept_ids=('c',),company='target')
        out=r.project_retrieve(query,config=cfg(),seed=0,now=now)
        self.assertEqual(out['questions'][0]['question_id'],'co')
        self.assertEqual(len(out['questions']),3)
        history={'co':{'last_asked_at':now.isoformat()},'other':{'last_recalled_at':now.isoformat()},
                 'plain':{'last_selected_at':(now-timedelta(days=8)).isoformat()}}
        out=r.project_retrieve(query,config=cfg(),seed=0,now=now,history=history)
        byid={q['question_id']:q for q in out['questions']}
        self.assertLess(byid['co']['history_factor'],1)
        self.assertEqual(byid['other']['history_factor'],1)
        self.assertEqual(byid['plain']['history_factor'],1)
        self.assertNotEqual(out['questions'][0]['question_id'],'co')

    def test_explicit_duplicate_identity_and_asked_filter_cover_whole_cluster(self):
        r=self.retriever([node('c'),question('q1',canonical_question_id='cluster'),question('q2',canonical_question_id='cluster'),question('q3')],
                         [edge(q,'TESTS','c') for q in ('q1','q2','q3')])
        query=m.ProjectQuery(concept_ids=('c',))
        out=r.project_retrieve(query,config=cfg(),seed=0)
        self.assertEqual(len(out['questions']),2)
        self.assertEqual(next(q for q in out['questions'] if q['canonical_question_id']=='cluster')['source_question_ids'],['q1','q2'])
        out=r.project_retrieve(query,config=cfg(),asked_question_ids=['q2'])
        self.assertEqual([q['question_id'] for q in out['questions']],['q3'])

    def test_contextual_short_text_is_not_implicitly_merged(self):
        a,b=question('a'),question('b');a['name']=b['name']='日志怎么做的？'
        r=self.retriever([node('c'),a,b],[edge('a','TESTS','c'),edge('b','TESTS','c')])
        out=r.project_retrieve(m.ProjectQuery(concept_ids=('c',)),config=cfg())
        self.assertEqual(len(out['questions']),2)

    def test_history_on_another_verified_duplicate_applies_to_retrieved_variant(self):
        r=self.retriever([node('c'),question('q1',canonical_question_id='cluster'),
                          question('q2',canonical_question_id='cluster')],[edge('q1','TESTS','c')])
        now=datetime(2026,11,6,tzinfo=timezone.utc)
        out=r.project_retrieve(m.ProjectQuery(concept_ids=('c',)),config=cfg(),now=now,
                               history={'q2':{'last_asked_at':now.isoformat()}})
        self.assertEqual(out['questions'][0]['question_id'],'q1')
        self.assertLess(out['questions'][0]['history_factor'],1)

    def test_draft_node_or_edge_is_excluded_and_leaf_is_structural(self):
        nodes=[node('root'),node('draftchild',state='draft'),question('parentq',category='bagu'),question('draftq',state='draft',category='bagu')]
        edges=[edge('root','HAS_SUBTOPIC','draftchild',state='draft'),edge('parentq','TESTS','root'),edge('draftq','TESTS','draftchild',state='draft')]
        r=self.retriever(nodes,edges)
        self.assertEqual(r.bagu_retrieve(domain_concept_ids=['root'],count=5)['questions'],[])
        out=r.project_retrieve(m.ProjectQuery(concept_ids=('root',)),config=cfg())
        self.assertEqual([q['question_id'] for q in out['questions']],['parentq'])
        allr=self.retriever(nodes,edges,include_drafts=True)
        self.assertEqual([q['question_id'] for q in allr.bagu_retrieve(domain_concept_ids=['root'],count=5)['questions']],['draftq'])

    def test_bagu_only_leaf_direct_tests_and_category_no_requires_or_kg(self):
        nodes=[node('root'),node('leaf'),node('other'),node('s','Scene')]
        for q in ('parent','yes','no','req','foreign','scene'):
            nodes.append(question(q,original_tags={'category':'project' if q=='no' else 'bagu'}))
        edges=[edge('root','HAS_SUBTOPIC','leaf'),edge('parent','TESTS','root'),edge('yes','TESTS','leaf'),
               edge('no','TESTS','leaf'),edge('req','REQUIRES','leaf'),edge('foreign','TESTS','other'),
               edge('s','HAS_QUESTION','scene'),edge('s','INVOLVES','leaf')]
        r=self.retriever(nodes,edges)
        out=r.bagu_retrieve(domain_concept_ids=['root'],count=10,seed=4)
        self.assertEqual([q['question_id'] for q in out['questions']],['yes'])
        self.assertEqual(out['questions'][0]['leaf_concept_ids'],['leaf'])
        self.assertEqual(len(r.graph._bagu_cache),1)
        r.bagu_retrieve(domain_concept_ids=['root'],count=1)
        self.assertEqual(len(r.graph._bagu_cache),1)

    def test_bagu_multi_leaf_uniform_identity_pool_and_cross_section_exclusion(self):
        nodes=[node('root'),node('a'),node('b'),question('q1',category='bagu'),question('q2',category='bagu'),question('alias',category='bagu',canonical_question_id='q1')]
        edges=[edge('root','HAS_SUBTOPIC','a'),edge('root','HAS_SUBTOPIC','b'),edge('q1','TESTS','a'),
               edge('q1','TESTS','b'),edge('alias','TESTS','b'),edge('q2','TESTS','a')]
        r=self.retriever(nodes,edges)
        out=r.bagu_retrieve(domain_concept_ids=['root'],count=10,seed=42)
        self.assertEqual(out['meta']['pool_count'],2)
        self.assertEqual(len(out['questions']),2)
        out=r.bagu_retrieve(domain_concept_ids=['root'],count=10,exclude_question_ids=['alias'],seed=42)
        self.assertEqual([q['question_id'] for q in out['questions']],['q2'])
        self.assertEqual(r.bagu_retrieve(domain_concept_ids=['root'],count=0)['questions'],[])

    def test_no_shared_graph_mutation(self):
        nodes=[node('c'),question('q',category='bagu')];edges=[edge('q','TESTS','c')]
        old=deepcopy((nodes,edges));r=self.retriever(nodes,edges)
        r.project_retrieve(m.ProjectQuery(concept_ids=('c',)),config=cfg(),history={'q':{'last_selected_at':'2026-11-06T00:00:00Z'}})
        r.bagu_retrieve(domain_concept_ids=['c'],count=1)
        self.assertEqual((nodes,edges),old)

    def test_invalid_configuration_seeds_and_graph_are_rejected(self):
        with self.assertRaises(ValueError):cfg(max_depth=-1)
        with self.assertRaises(ValueError):cfg(questions_per_turn=0)
        with self.assertRaises(ValueError):cfg(max_depth=True)
        r=self.retriever([node('c')],[])
        with self.assertRaises(ValueError):r.project_retrieve(m.ProjectQuery(concept_ids=('typo',)))
        with self.assertRaises(ValueError):r.bagu_retrieve(domain_concept_ids=['c'],count=-1)
        with self.assertRaises(ValueError):self.retriever([node('a'),node('b')],[edge('a','HAS_SUBTOPIC','b'),edge('b','HAS_SUBTOPIC','a')])
        with self.assertRaises(ValueError):self.retriever([node('a')],[edge('a','INVOLVES','a')])
        with self.assertRaises(ValueError):self.retriever([question('q1'),question('q2')],[],duplicate_ids={'q1':'q2','q2':'q1'})


if __name__=='__main__':unittest.main()
