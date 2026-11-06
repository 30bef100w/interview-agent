"""Small integration smoke check against the published, versioned graph ZIP.

Hand-picked seeds verify execution invariants, not semantic retrieval quality.
"""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('snapshot_graph_cli',ROOT/'backend/scripts/run_graph_retrieval.py')
cli=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(cli)
ARCHIVE=ROOT/'docs/graph-demo/mgkg-9000-v3.zip'


@unittest.skipUnless(ARCHIVE.exists(),'published graph snapshot absent')
class SnapshotTests(unittest.TestCase):
    def test_active_and_draft_views_execute_with_bounded_paths_and_unique_slots(self):
        query=cli.ProjectQuery(scene_ids=('scene:candidate:proposed.scene.customer_service',),
                               concept_ids=('concept:agent','concept:rag'))
        for drafts in (False,True):
            with self.subTest(include_drafts=drafts):
                graph=cli.load_graph(ARCHIVE,drafts);retriever=cli.GraphRetriever(graph)
                out=retriever.project_retrieve(query,seed=42)
                self.assertEqual(out['meta']['unique_candidates'],500)
                self.assertEqual(out['meta']['assigned_by_lane'],{'kg':60,'mg':40})
                self.assertEqual(len(out['questions']),100)
                self.assertLessEqual(out['meta']['unique_concepts_expanded'],200)
                self.assertEqual(len({q['canonical_question_id'] for q in out['questions']}),100)
                self.assertTrue(any(q['direct_scene'] for q in out['questions']))
                for q in out['questions']:
                    for path in q['paths']:
                        self.assertLessEqual(path['concept_depth'],2)
                        if not drafts:
                            self.assertTrue(all(e['state']!='draft' for e in path['steps']))
                bagu=retriever.bagu_retrieve(domain_concept_ids=['concept:agent'],count=5,seed=42,
                                              exclude_question_ids=[q['question_id'] for q in out['questions']])
                self.assertEqual(len(bagu['questions']),5)
                self.assertFalse({q['canonical_question_id'] for q in out['questions']} &
                                 {q['canonical_question_id'] for q in bagu['questions']})
                for q in bagu['questions']:
                    self.assertTrue(all(not graph.structural_children.get(leaf) for leaf in q['leaf_concept_ids']))


if __name__=='__main__':unittest.main()
