import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('graph_ab', Path(__file__).parents[1]/'scripts/eval_graph_retrieval_v1.py')
EVAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVAL)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.protocol = {'config':{'final_limit':5}, 'queries':[{'id':'q','slice':'focused'}]}
        self.pool = [{'pool_id':'p','query_id':'q','question_id':'x','question':'Q?'}]
        self.judgments = [{'pool_id':'p','grade':2,'scene_match':0,'reason':'Directly asks the target.'}]
        self.runs = [{'query_id':'q','arm':arm,'seed':42,'selected':['x'],'candidates':['x'],
                      'elapsed_ms':1} for arm in EVAL.ARMS]

    def test_missing_slots_are_not_counted_as_relevant(self):
        result=EVAL.summarize(self.protocol,self.runs,self.pool,self.judgments)
        self.assertEqual(result['summary']['graph_v1']['direct_p_at_k'],.2)
        self.assertEqual(result['summary']['graph_v1']['fill_rate'],.2)
        self.assertEqual(result['summary']['graph_v1']['pooled_positive_candidate_coverage'],1)
        self.assertEqual(result['comparisons'][0]['paired_query_bootstrap_95_ci'],[0,0])

    def test_unjudged_is_rejected(self):
        with self.assertRaises(ValueError):
            EVAL.summarize(self.protocol,self.runs,self.pool,[])

    def test_duplicate_judgment_is_rejected(self):
        with self.assertRaises(ValueError):
            EVAL.summarize(self.protocol,self.runs,self.pool,self.judgments*2)

    def test_reason_and_valid_grade_required(self):
        for value in (None, True, 3):
            with self.subTest(value=value), self.assertRaises(ValueError):
                EVAL.summarize(self.protocol,self.runs,self.pool,[{**self.judgments[0],'grade':value}])
        with self.assertRaises(ValueError):
            EVAL.summarize(self.protocol,self.runs,self.pool,[{**self.judgments[0],'reason':''}])

    def test_sampled_pool_is_an_estimate_with_separate_fill(self):
        protocol={**self.protocol,'config':{'final_limit':100},'judgment_sample_size':1}
        runs=[{**r,'selected':['x','unjudged'],'judgment_ids':['x'],
               'selected_text_duplicate_count':0} for r in self.runs]
        result=EVAL.summarize_sampled(protocol,runs,self.pool,self.judgments)
        graph=result['summary']['graph_v1']
        self.assertEqual(graph['estimated_direct_precision_returned'],1)
        self.assertEqual(graph['estimated_direct_count'],2)
        self.assertEqual(graph['fill_rate'],.02)
        with self.assertRaises(ValueError):
            EVAL.summarize(protocol,runs,self.pool,self.judgments)

    def test_sampled_pool_rejects_missing_judgments(self):
        with self.assertRaises(ValueError):
            EVAL.summarize_sampled({**self.protocol,'judgment_sample_size':1},self.runs,self.pool,[])


if __name__=='__main__':
    unittest.main()
