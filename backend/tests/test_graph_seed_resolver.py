"""Closed catalog/evidence checks use fake models; no provider calls."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.graph_retrieval import GraphIndex
from app.services.graph_seed_resolver import GraphSeedResolver, project_text


def concept(nid,**props):
    return {'id':nid,'name':nid,'node_type':'Concept','state':'active','properties':props}


class Model:
    def __init__(self,result):self.result=result;self.calls=[]
    def chat_json(self,system,user):self.calls.append((system,user));return self.result


class SeedResolverTests(unittest.TestCase):
    def setUp(self):
        self.graph=GraphIndex([
            concept('concept:nav',kind='navigation'),concept('concept:redis'),
            {'id':'scene:local','name':'本地生活','node_type':'Scene','state':'active',
             'properties':{'definition':'商户点评与到店核销','exclude_when':['单纯Redis技术题']}}
        ],[{'src_id':'concept:nav','relation':'HAS_SUBTOPIC','dst_id':'concept:redis','state':'active'}])
        self.project={'name':'商户点评系统','tech_stack':['Redis'],'highlights':['使用缓存展示商户信息'],
                      'dig_points':['虚构的Kafka实现'],'scene_tags':['旧推断标签']}
        self.valid={'scenes':[{'id':'scene:local','evidence':'商户点评系统','reason':'业务为商户点评'}],
                    'concepts':[{'id':'concept:redis','evidence':'Redis','reason':'明确技术栈'}]}

    def test_resolves_scene_and_concept_independently_with_actual_quotes(self):
        model=Model(self.valid);out=GraphSeedResolver(self.graph).resolve(self.project,model,project_id='p1')
        self.assertEqual(out.query.scene_ids,('scene:local',))
        self.assertEqual(out.query.concept_ids,('concept:redis',))
        self.assertEqual(out.query.project_id,'p1')
        self.assertEqual(len(model.calls),1)
        self.assertIn('单纯Redis技术题',model.calls[0][1])
        self.assertNotIn('虚构的Kafka实现',model.calls[0][1])
        self.assertNotIn('旧推断标签',project_text(self.project))
        self.assertEqual(out.as_dict()['concept_evidence'][0]['evidence'],'Redis')

    def test_no_scene_does_not_drop_concepts(self):
        result={**self.valid,'scenes':[]}
        out=GraphSeedResolver(self.graph).resolve(self.project,Model(result))
        self.assertEqual(out.query.scene_ids,())
        self.assertEqual(out.query.concept_ids,('concept:redis',))

    def test_unknown_ids_invented_evidence_navigation_and_limits_are_rejected(self):
        bad=[{'scenes':[],'concepts':[{'id':'concept:invented','evidence':'Redis','reason':'x'}]},
             {'scenes':[],'concepts':[{'id':'concept:nav','evidence':'Redis','reason':'x'}]},
             {'scenes':[],'concepts':[{'id':'concept:redis','evidence':'使用了Kafka','reason':'x'}]},
             {'scenes':[],'concepts':[{'id':'concept:redis','evidence':'Redis','reason':''}]},
             {'scenes':[],'concepts':'concept:redis'},
             {'scenes':[],'concepts':[self.valid['concepts'][0],self.valid['concepts'][0]]}]
        for result in bad:
            with self.subTest(result=result),self.assertRaises(ValueError):
                GraphSeedResolver(self.graph).resolve(self.project,Model(result))
        with self.assertRaises(ValueError):
            GraphSeedResolver(self.graph,max_concept_seeds=0).resolve(self.project,Model(self.valid))
        with self.assertRaises(ValueError):GraphSeedResolver(self.graph,max_catalog_chars=1)
        with self.assertRaises(ValueError):GraphSeedResolver(self.graph).resolve({},Model(self.valid))


if __name__=='__main__':unittest.main()
