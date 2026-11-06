import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0,str(Path(__file__).parent))
import prepare_collaboration as P
import check_collaboration as C
import summarize_collaboration as S


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='标注 portable ')
        self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.original=[{'question':'如何比较两个方案？','answer':'给定成本比较','company':'甲企业','roles':['agent_dev'],'source_file':'one.md'},
                       {'question':'既有记录','answer':'原答案','company':'乙企业','source_file':'two.md'},
                       {'question':'如何控制调用重试？','answer':'幂等处理','company':'丙企业','source_file':'three.md'}]
        self.zip=self.root/'knowledge.zip'
        with zipfile.ZipFile(self.zip,'w') as z:z.writestr('knowledge_base/questions_dedup.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in self.original))
        self.sample=self.root/'sample.jsonl';P.jsonl(self.sample,[{**self.original[1],'sample_id':'S1','source_index':1}])
        self.known=self.root/'known.jsonl';P.jsonl(self.known,[{'sample_id':'S1','corpus_id':'old','record_status':'labeled'}])
        self.graph=self.root/'graph';self.graph.mkdir()
        P.jsonl(self.graph/'nodes.jsonl',[{'id':'concept:'+i,'node_type':'Concept','name':i,'state':'active','properties':{'concept_id':i}} for i in ('a','b')])
        P.jsonl(self.graph/'edges.jsonl',[])
        self.bundle=self.root/'完整数据包';self.plan=P.prepare(self.zip,self.known,self.sample,self.graph,self.bundle,2)
        self.base=self.bundle/'tasks/B0001';self.task=self.base/'task.json'
        t=C.read(self.task)
        self.initial=self.base/'annotations.jsonl';self.output=[]
        for i,source in enumerate(C.rows(self.base/'source.jsonl'),1):
            relation={'concept_id':'a','basis':'question','evidence':{'locator':f'source.jsonl:{i}#question','quote':source['question']},'reason':'题干明确要求比较或处理。'}
            self.output.append({'schema_version':'1.0.0','corpus_id':t['corpus_id'],'registry_version':t['registry_version'],
              'sample_id':source['sample_id'],'source_locator':f'source.jsonl:{i}','record_status':'labeled',
              'review_stage':'initial','review_scope':None,'normalized_question':None,'context_refs':[],
              'tests':[relation],'requires':[],'scenes':[],'scene_concept_links':[],'reason':'结构测试夹具，不声称语义正确。'})
        P.jsonl(self.initial,self.output);self.manifest=self.base/'manifest.initial.json';self.refresh()

    def refresh(self,annotation=None,path=None):
        C.write(path or self.manifest,C.manifest(self.task,annotation or self.initial))

    def audit(self,**kwargs):
        return C.audit(self.task,self.initial,self.manifest,**kwargs)

    def test_exact_exclusion_and_source_attributes_preserved(self):
        self.assertEqual(self.plan['remaining_record_count'],2)
        sources=C.rows(self.base/'source.jsonl')
        self.assertEqual([r['sample_id'] for r in sources],['F000001','F000003'])
        self.assertEqual([r['company'] for r in sources],['甲企业','丙企业'])
        self.assertEqual([r['answer'] for r in sources],['给定成本比较','幂等处理'])
        self.assertFalse(self.plan['semantic_annotation_completed'])
        with self.assertRaisesRegex(ValueError,'不覆盖'):
            P.prepare(self.zip,self.known,self.sample,self.graph,self.bundle,2)

    def test_existing_record_with_wrong_answer_is_not_silently_skipped(self):
        P.jsonl(self.sample,[{**self.original[1],'answer':'另一版本','sample_id':'S1','source_index':1}])
        with self.assertRaisesRegex(ValueError,'不一致'):
            P.prepare(self.zip,self.known,self.sample,self.graph,self.root/'other',2)

    def test_scope_and_source_hash_cannot_be_changed(self):
        t=C.read(self.task);t['planned_sample_ids']=t['planned_sample_ids'][:1];C.write(self.task,t)
        with self.assertRaisesRegex(ValueError,'任务配置已改变'):C.load_task(self.task)

    def test_stale_source_is_rejected(self):
        (self.base/'source.jsonl').write_text('{}\n')
        with self.assertRaisesRegex(ValueError,'源数据哈希'):self.audit()

    def test_valid_structure_and_quotes_do_not_claim_semantic_accuracy(self):
        r=self.audit()
        self.assertTrue(r['source_quotes_checked'])
        self.assertFalse(r['semantic_accuracy_checked'])
        self.assertEqual(r['initial_count'],2)
        self.assertEqual(r['full_review_count'],0)

    def test_fabricated_quote_is_rejected(self):
        self.output[0]['tests'][0]['evidence']['quote']='原文根本不存在的句子';P.jsonl(self.initial,self.output);self.refresh()
        with self.assertRaisesRegex(ValueError,'引文不在原文'):self.audit()

    def test_other_question_cannot_be_used_as_question_basis(self):
        self.output[0]['tests'][0]['evidence']={'locator':'source.jsonl:2#question','quote':'如何控制调用重试？'}
        P.jsonl(self.initial,self.output);self.refresh()
        with self.assertRaisesRegex(ValueError,'引用了别题'):self.audit()

    def test_partial_progress_is_not_full_delivery(self):
        P.jsonl(self.initial,self.output[:1]);self.refresh()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.audit()
        self.assertEqual(self.audit(allow_partial=True)['completed'],1)

    def review_fixture(self):
        reviewed=copy.deepcopy(self.output)
        for r in reviewed:r.update(review_stage='review',review_scope='full')
        path=self.base/'reviewed_annotations.jsonl';P.jsonl(path,reviewed)
        m=self.base/'manifest.reviewed.json';self.refresh(path,m)
        logs=[{'sample_id':r['sample_id'],'decision':'pass','checked_fields':['status','context','tests','requires','scenes','scene_concept_links'],
               'reason':'用于检查日志覆盖。','evidence':[r['tests'][0]['evidence']]} for r in reviewed]
        log=self.base/'reviews.jsonl';P.jsonl(log,logs)
        return reviewed,path,m,logs,log

    def test_review_flags_without_review_log_are_rejected(self):
        reviewed,path,m,logs,log=self.review_fixture()
        with self.assertRaisesRegex(ValueError,'review-log'):
            C.audit(self.task,path,m,reviewed=True)
        r=C.audit(self.task,path,m,review_log_path=log,reviewed=True)
        self.assertTrue(r['review_log_complete']);self.assertFalse(r['semantic_accuracy_checked'])

    def test_pass_cannot_hide_label_changes(self):
        reviewed,path,m,logs,log=self.review_fixture();reviewed[0]['tests'][0]['concept_id']='b';P.jsonl(path,reviewed);self.refresh(path,m)
        with self.assertRaisesRegex(ValueError,'pass却暗改'):
            C.audit(self.task,path,m,review_log_path=log,reviewed=True)
        logs[0]['decision']='fixed';logs[0]['changes']=[{'field':'tests','before':self.output[0]['tests'],'after':reviewed[0]['tests'],'reason':'测试差异记录。'}];P.jsonl(log,logs)
        self.assertTrue(C.audit(self.task,path,m,review_log_path=log,reviewed=True)['review_log_complete'])

    def test_review_log_must_cover_every_record(self):
        reviewed,path,m,logs,log=self.review_fixture();P.jsonl(log,logs[:1])
        with self.assertRaisesRegex(ValueError,'漏项'):
            C.audit(self.task,path,m,review_log_path=log,reviewed=True)

    def test_scene_definition_change_requires_md_sync(self):
        scenes=C.read(self.base/'scene-registry.json');scenes['registry_version']='test.new'
        scenes['scenes'][0]['definition']+='真实范围补充。';C.write(self.base/'scene-registry.json',scenes);self.refresh()
        with self.assertRaisesRegex(ValueError,'MD未同步'):self.audit()

    def test_global_progress_uses_actual_outputs_and_preserves_scope(self):
        report=S.summarize(self.bundle)
        self.assertEqual(report['initial_file_rows'],2)
        self.assertEqual(report['records_with_complete_review_attestation_and_checks'],0)
        self.review_fixture()
        report=S.summarize(self.bundle)
        self.assertEqual(report['records_with_complete_review_attestation_and_checks'],2)
        self.assertFalse(report['semantic_accuracy_proven'])
        excluded=C.read(self.bundle/'excluded-existing.json');excluded[0]['full_sample_id']='F000001';C.write(self.bundle/'excluded-existing.json',excluded)
        with self.assertRaisesRegex(ValueError,'重叠'):S.summarize(self.bundle)

    def test_windows_utf8_bom_annotation_output_is_supported(self):
        content=self.initial.read_text(encoding='utf-8')
        self.initial.write_text(content,encoding='utf-8-sig');self.refresh()
        self.assertEqual(self.audit()['completed'],2)

    def test_final_review_cannot_accept_duplicate_initial_rows(self):
        reviewed,path,m,logs,log=self.review_fixture();P.jsonl(self.initial,self.output+[self.output[-1]])
        with self.assertRaisesRegex(ValueError,'初标原件重复'):
            C.audit(self.task,path,m,review_log_path=log,reviewed=True)

    def test_export_keeps_explicit_legacy_ids_without_creating_nodes(self):
        P.write(self.graph/'entity_redirects.json',{'old.a':'a','older.a':'old.a'})
        destination=self.root/'alias catalog';P.export_catalog(self.graph,destination)
        nodes=C.read(destination/'concept-registry.json')
        self.assertEqual(len(nodes),2)
        self.assertEqual(next(r for r in nodes if r['id']=='a')['legacy_ids'],['old.a','older.a'])


if __name__=='__main__':unittest.main()
