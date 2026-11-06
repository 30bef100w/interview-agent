"""The CLI pipeline consumes the published graph schema without provider calls."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

BACKEND=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('run_graph_retrieval_test',BACKEND/'scripts/run_graph_retrieval.py')
cli=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(cli)


def graph_rows():
    nodes=[{'id':'c','name':'Agent','node_type':'Concept','state':'active','properties':{}}]
    nodes.extend({'id':f'q{i}','name':f'问题{i}','node_type':'Question','state':'active',
                  'properties':{'answer':'完整答案','original_tags':{'category':'bagu'}}} for i in range(5))
    edges=[{'src_id':f'q{i}','relation':'TESTS','dst_id':'c','state':'active'} for i in range(5)]
    return nodes,edges


class CliTests(unittest.TestCase):
    def test_multi_project_and_bagu_do_not_repeat_selected_questions(self):
        graph=cli.GraphIndex(*graph_rows())
        result=cli.run(graph,{'config':{'final_limit':1},
                             'projects':[{'scene_ids':[],'concept_ids':['c']},{'scene_ids':[],'concept_ids':['c']}],
                             'bagu':{'domain_concept_ids':['c'],'count':10}},seed=1)
        picked=[q['question_id'] for p in result['projects'] for q in p['questions']]
        picked.extend(q['question_id'] for q in result['bagu']['questions'])
        self.assertEqual(len(picked),5)
        self.assertEqual(len(set(picked)),5)
        with self.assertRaises(ValueError):cli.run(graph,{'projects':[{'name':'unresolved'}]})
        with self.assertRaises(ValueError):cli.run(graph,{'projects':[{'scene_ids':'scene','concept_ids':['c']}]})

    def test_zip_cli_creates_report_omits_answers_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp=Path(tmp);archive=tmp/'graph.zip';query=tmp/'query.json';out=tmp/'out.json'
            with zipfile.ZipFile(archive,'w') as z:
                for name,rows in zip(['nodes.jsonl','edges.jsonl'],graph_rows()):
                    z.writestr('snapshot/'+name,'\n'.join(json.dumps(x,ensure_ascii=False) for x in rows))
            query.write_text(json.dumps({'projects':[{'scene_ids':[],'concept_ids':['c']}],
                                         'bagu':{'domain_concept_ids':['c'],'count':2}}))
            command=[sys.executable,str(BACKEND/'scripts/run_graph_retrieval.py'),'--graph',str(archive),
                     '--input',str(query),'--out',str(out)]
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(out.read_text())
            self.assertEqual(report['projects'][0]['meta']['selected_count'],5)
            self.assertNotIn('answer',report['projects'][0]['questions'][0])
            result=subprocess.run(command,capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('fresh --out',result.stderr)


if __name__=='__main__':unittest.main()
