"""Regression checks for scene identities and annotation boundary enforcement."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from validate_annotations import ancestor_map, check_regressions, load_scene_registry, validate

ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / 'backend/data/scene_registry_v01.json'
PREFIX = 'scene:candidate:proposed.scene.'


class SceneContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.catalog = json.loads(CATALOG.read_text())

    def write(self, name, value, lines=False):
        p = self.base / name
        p.write_text(('\n'.join(json.dumps(v) for v in value) if lines else json.dumps(value)) + '\n')
        return p

    def check_catalog(self, value=None):
        return load_scene_registry(self.write('scenes.json', value or self.catalog))

    def fixture(self, scene_id=None, proposals=None):
        relation = {'scene_id': scene_id, 'basis': 'question',
                    'evidence': {'locator': 'fixture:1', 'quote': '测试语料'}, 'reason': '测试引用'}
        row = dict(schema_version='1.0.0', corpus_id='fixture', sample_id='T1',
                   registry_version='fixture.v1', source_locator='fixture:1',
                   record_status='labeled', review_stage='initial', normalized_question=None,
                   context_refs=[], reason='测试', tests=[], requires=[],
                   scenes=[relation] if scene_id else [], scene_concept_links=[])
        manifest = dict(schema_version='1.0.0', corpus_id='fixture', registry_version='fixture.v1',
                        source_file='fixture.jsonl', source_sha256='0'*64, planned_sample_ids=['T1'],
                        completed_sample_ids=['T1'], status_counts={'labeled': 1},
                        review_stage_counts={'initial': 1}, proposal_count=len(proposals or []),
                        scene_registry_version=self.catalog['registry_version'],
                        scene_registry_sha256=hashlib.sha256(CATALOG.read_bytes()).hexdigest())
        return SimpleNamespace(registry=self.write('concepts.json', []), scene_registry=CATALOG,
                               scene_nodes=None, annotations=self.write('annotations.jsonl', [row], True),
                               proposals=self.write('proposals.jsonl', proposals, True) if proposals else None,
                               manifest=self.write('manifest.json', manifest), allow_partial=False)

    def test_catalog_covers_all_legacy_scenes(self):
        old = {n['id'] for n in map(json.loads, (ROOT/'data/index_review/2026-11-03/nodes.jsonl').read_text().splitlines()) if n['node_type']=='Scene'}
        self.assertEqual(len(old), 48)
        self.assertTrue(old <= {s['id'] for s in self.catalog['scenes']})
        ids, _ = self.check_catalog()
        self.assertEqual(len(ids), 39)

    def test_duplicate_id_and_identity_rejected(self):
        for field in ('id', 'name'):
            with self.subTest(field=field):
                c=copy.deepcopy(self.catalog)
                c['scenes'][1][field]=c['scenes'][0][field]
                with self.assertRaises(ValueError):self.check_catalog(c)
        c=copy.deepcopy(self.catalog)
        c['scenes'][1]['aliases']=[c['scenes'][0]['name']]
        with self.assertRaises(ValueError):self.check_catalog(c)

    def test_missing_definition_or_boundaries_rejected(self):
        for field in ('definition', 'match_when', 'exclude_when'):
            c=copy.deepcopy(self.catalog)
            c['scenes'][0][field]=[] if field.endswith('_when') else ''
            with self.subTest(field=field), self.assertRaises(ValueError):self.check_catalog(c)

    def test_bad_redirect_and_cycles_rejected(self):
        for target in ('scene:absent', PREFIX+'order_timeout', PREFIX+'trading_agent'):
            c=copy.deepcopy(self.catalog)
            s=next(s for s in c['scenes'] if s['id']==PREFIX+'commerce_agent')
            s['redirect_to']=target
            if target==PREFIX+'trading_agent':
                next(s for s in c['scenes'] if s['id']==target)['redirect_to']=s['id']
            with self.subTest(target=target), self.assertRaises(ValueError):self.check_catalog(c)

    def test_reusable_and_empty_scene_accepted(self):
        for sid in ('scene:business:delivery', 'scene:business:local_life', 'scene:business:ecommerce', None):
            with self.subTest(sid=sid):self.assertTrue(validate(self.fixture(sid))['valid'])

    def test_tutorial_project_ids_are_classification_redirects(self):
        by_id = {s['id']: s for s in self.catalog['scenes']}
        for old, target in (
            ('scene:project:heima_dianping', 'scene:business:local_life'),
            ('scene:project:sky_take_out', 'scene:business:delivery'),
        ):
            self.assertEqual(by_id[old]['tag_policy'], 'redirect')
            self.assertEqual(by_id[old]['redirect_to'], target)
            self.assertEqual(by_id[old]['redirect_semantics'], 'business_scenario_classification')
            with self.assertRaises(ValueError):
                validate(self.fixture(old))

    def test_all_retired_ids_rejected_as_labels(self):
        for s in self.catalog['scenes']:
            if s['tag_policy'] in {'redirect', 'module_only', 'context_review'}:
                with self.subTest(sid=s['id']), self.assertRaises(ValueError):validate(self.fixture(s['id']))

    def test_scene_proposal_requires_definition_and_boundaries(self):
        node=dict(id='new:scene:fixture',node_type='Scene',name='测试完整产品',definition='测试独立产品定义',
                  aliases=[],parents=[],evidence={'locator':'fixture:1','quote':'测试语料'},
                  match_when=['明确完整产品'],exclude_when=['孤立技术原理'])
        self.assertTrue(validate(self.fixture(node['id'],[node]))['valid'])
        for field in ('definition','match_when','exclude_when'):
            n=copy.deepcopy(node);n.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):validate(self.fixture(node['id'],[n]))

    def test_scene_version_and_hash_pin(self):
        for field in ('scene_registry_version','scene_registry_sha256'):
            args=self.fixture();m=json.loads(args.manifest.read_text());m[field]='incorrect'
            args.manifest=self.write('manifest.json',m)
            with self.subTest(field=field), self.assertRaises(ValueError):validate(args)

    def test_regression_cases_block_known_bad_edges_only(self):
        args = self.fixture('scene:project:sky_take_out')
        rows = [json.loads(line) for line in args.annotations.read_text().splitlines() if line.strip()]
        rows[0]['review_stage'] = 'review'
        rows[0]['review_scope'] = 'full'
        rows[0]['tests'] = [{'concept_id': 'mysql', 'basis': 'question',
                             'evidence': {'locator': 'fixture:1', 'quote': '测试语料'},
                             'reason': '测试'}]
        # A fixture case must be bound to the same corpus/hash, and a forbidden edge is rejected.
        manifest = json.loads(args.manifest.read_text())
        case = {'schema_version': '1.0.0', 'corpus_id': manifest['corpus_id'],
                'source_sha256': manifest['source_sha256'], 'cases': [
                    {'sample_id': 'T1', 'forbidden_tests': ['mysql'], 'forbidden_scenes': [],
                     'forbidden_scene_concept_links': [], 'reason': 'fixture regression'}]}
        case_path = self.write('regression.json', case)
        with self.assertRaises(ValueError):
            check_regressions(case_path, manifest, rows)

    def test_review_scope_is_counted_and_required(self):
        args = self.fixture()
        rows = [json.loads(line) for line in args.annotations.read_text().splitlines() if line.strip()]
        rows[0]['review_stage'] = 'review'
        rows[0]['review_scope'] = 'full'
        args.annotations = self.write('review.jsonl', rows, True)
        manifest = json.loads(args.manifest.read_text())
        manifest['review_stage_counts'] = {'review': 1}
        manifest['reviewed_sample_ids'] = ['T1']
        manifest['full_reviewed_sample_ids'] = ['T1']
        manifest['review_scope_counts'] = {'full': 1}
        args.manifest = self.write('review-manifest.json', manifest)
        args.require_reviewed = True
        self.assertTrue(validate(args)['valid'])

    def test_regressions_require_correct_relations_as_well_as_removing_wrong_ones(self):
        args = self.fixture()
        manifest = json.loads(args.manifest.read_text())
        row = json.loads(args.annotations.read_text())
        row.update(review_stage='review', review_scope='full')
        case = dict(schema_version='1.0.0', corpus_id=manifest['corpus_id'],
                    source_sha256=manifest['source_sha256'], cases=[
                        dict(sample_id='T1', required_tests=['spring.aop'],
                             required_scenes=['scene:customer_service'], reason='测试正确关系不能漏掉')])
        path = self.write('positive-regression.json', case)
        with self.assertRaisesRegex(ValueError, 'missing_tests'):
            check_regressions(path, manifest, [row])
        row['tests'] = [{'concept_id': 'spring.aop'}]
        with self.assertRaisesRegex(ValueError, 'scene:customer_service'):
            check_regressions(path, manifest, [row])
        row['scenes'] = [{'scene_id': 'scene:customer_service'}]
        self.assertEqual(check_regressions(path, manifest, [row])['cases_checked'], 1)
        # Cases for another source snapshot must never be applied by matching local IDs alone.
        manifest['source_sha256'] = '1' * 64
        with self.assertRaisesRegex(ValueError, 'source_sha256 differs'):
            check_regressions(path, manifest, [row])

    def test_status_only_acceptance_depends_on_record_status(self):
        for status in ('labeled', 'needs_context', 'not_question'):
            with self.subTest(status=status):
                args = self.fixture()
                row = json.loads(args.annotations.read_text())
                row.update(record_status=status, review_stage='review', review_scope='status_only')
                args.annotations = self.write('status-review.jsonl', [row], True)
                manifest = json.loads(args.manifest.read_text())
                manifest.update(status_counts={status: 1}, review_stage_counts={'review': 1})
                args.manifest = self.write('status-manifest.json', manifest)
                args.require_reviewed = True
                if status == 'labeled':
                    with self.assertRaisesRegex(ValueError, 'requires review_scope=full'):
                        validate(args)
                else:
                    self.assertTrue(validate(args)['valid'])

    def test_require_reviewed_rejects_initial_records(self):
        args = self.fixture()
        args.require_reviewed = True
        with self.assertRaisesRegex(ValueError, 'review incomplete'):
            validate(args)

    def test_multi_parent_overlap_is_counted_without_rejecting_relations(self):
        args = self.fixture()
        args.registry = self.write('concepts.json', [
            {'id': 'root', 'parents': []},
            {'id': 'left', 'parents': ['root']},
            {'id': 'right', 'parents': ['root']},
            {'id': 'leaf', 'parents': ['left', 'right']},
        ])
        row = json.loads(args.annotations.read_text())
        row['tests'] = [dict(concept_id=cid, basis='question',
                             evidence={'locator': 'fixture:1', 'quote': '测试语料'}, reason='测试')
                        for cid in ('root', 'left', 'leaf')]
        args.annotations = self.write('overlap.jsonl', [row], True)
        result = validate(args)
        self.assertTrue(result['valid'])
        self.assertEqual(result['ancestor_overlap_count'], 3)
        self.assertEqual(ancestor_map({'root': [], 'left': ['root'], 'right': ['root'],
                                       'leaf': ['left', 'right']})['leaf'],
                         {'root', 'left', 'right'})


if __name__ == '__main__':
    unittest.main()
