import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('four_arm', Path(__file__).parents[1]/'scripts/eval_graph_four_arm.py')
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def question(qid, text, answer='', context=None):
    return {'id':qid,'node_type':'Question','name':text,'state':'active',
            'properties':{'answer':answer,'context_refs':context or []}}


class ExperimentIntegrityTests(unittest.TestCase):
    def test_blind_evidence_excludes_provenance_and_labels(self):
        n=question('secret-id','问题','x'*900,[
            {'quote':'source/private.md','locator':'sample:1#source_file'},
            {'quote':'上文：工具失败后重试','locator':'sample:1#answer'}])
        n['properties'].update(original_tags={'scene':'secret'},source_file='/private/source')
        evidence=E.evidence(n)
        self.assertEqual(evidence['context_quotes'],['上文：工具失败后重试'])
        self.assertEqual(len(evidence['answer_excerpt']),800)
        self.assertTrue(evidence['answer_truncated'])
        blob=json.dumps(evidence)
        for secret in ('secret','source_file','locator','original_tags','private'):
            self.assertNotIn(secret,blob)
        self.assertRegex(E.opaque('judge','q','qid'),r'^[a-f0-9]{20}$')

    def test_dedup_preserves_ambiguous_context_and_different_answers(self):
        nodes=[question('a','这个怎么做','答案A',[{'quote':'场景A'}]),
               question('b','这个怎么做','答案A',[{'quote':'场景B'}]),
               question('c','这个怎么做','答案B',[{'quote':'场景A'}]),
               question('d','这个怎么做','答案A',[{'quote':'场景A'}])]
        graph=E.GraphIndex(nodes,[])
        items=[{'question_id':n['id'],'channels':['kg' if n['id']=='a' else 'mg'],
                'direct_scene':n['id']=='d'} for n in nodes]
        result=E.dedup(items,graph)
        self.assertEqual([r['question_id'] for r in result],['a','b','c'])
        self.assertEqual(result[0]['channels'],['kg','mg'])
        self.assertTrue(result[0]['direct_scene'])

    def test_same_quota_allocator_applies_to_different_rankings(self):
        rows=[{'question_id':str(i),'channels':['kg' if i<4 else 'mg'],
               'direct_scene':i==0} for i in range(8)]
        cfg=E.GraphRetrievalConfig(final_limit=5)
        for ranked in (rows,list(reversed(rows))):
            selected,allocation=E.quota_select(ranked,cfg,True)
            self.assertEqual(len(selected),5)
            self.assertEqual(len(set(selected)),5)
            self.assertIn('0',selected)
            self.assertEqual(E.Counter(allocation['assigned'].values()),{'kg':3,'mg':2})

    def test_fixed_k_common_pool_ideal_and_incomplete_judgments(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)
            E.write(out/'protocol.json',{'config':{'final_limit':10},'queries':[{'id':'q','slice':'s'}],
                                        'graph':'unused','limitations':[]})
            E.write(out/'runs.json',[{'query_id':'q','seed':42,'arm':a,'selected':['x'],
                                      'candidates':['x'],'shortlist':['x']} for a in E.ARMS])
            E.write(out/'pool_key.json',[{'pool_id':'p','query_id':'q','question_id':'x'},
                                          {'pool_id':'p2','query_id':'q','question_id':'y'}])
            E.write(out/'manifest.json',{'graph_sha256':{}})
            E.write(out/'latency.local.json',{'cold':{},'warm_runs':[
                {'arm':a,'total_ms':1} for a in E.ARMS[:3]]})
            E.write(out/'judge_results'/'test.json',[{'pool_id':'p','grade':2,'reason':'direct'}])
            with self.assertRaisesRegex(ValueError,'incomplete'):
                E.score(out)
            E.write(out/'judge_results'/'test.json',[{'pool_id':pid,'grade':2,'reason':'direct'} for pid in ('p','p2')])
            E.score(out)
            summary=E.read(out/'summary.json')
            self.assertEqual(summary['summary']['graph_rules']['direct_p_at_k'],.1)
            self.assertEqual(summary['summary']['graph_rules']['fill_rate'],.1)
            self.assertLess(summary['summary']['graph_rules']['pooled_ndcg_at_k'],1)


if __name__=='__main__':
    unittest.main()
