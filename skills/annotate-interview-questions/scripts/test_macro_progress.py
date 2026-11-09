import unittest

import check_collaboration as C
import macro_progress as M
import prepare_collaboration as P
import test_collaboration as fixtures


class MacroProgressTests(unittest.TestCase):
    setUp = fixtures.CollaborationTests.setUp
    refresh = fixtures.CollaborationTests.refresh
    review_fixture = fixtures.CollaborationTests.review_fixture

    def report(self, stage='initial'):
        path = self.root / 'macro-plan.json'
        if not path.exists():
            C.write(path, {'corpus_id': self.plan['corpus_id'],
                          'source_plan_sha256': C.sha(self.bundle / 'plan.json'),
                          'remaining_record_count': 2,
                          'macros': [{'macro_id': 'M01', 'record_count': 2, 'task_ids': ['B0001']}]})
        return M.progress(path, self.bundle, 'M01', stage)

    def test_skip_only_full_checked_outputs(self):
        report = self.report()
        self.assertTrue(report['complete_for_stage'])
        self.assertIsNone(report['next_task'])
        self.assertEqual(report['records_with_checks_passed'], 2)
        self.assertFalse(report['semantic_accuracy_proven'])
        self.manifest.unlink()
        report = self.report()
        self.assertFalse(report['complete_for_stage'])
        self.assertEqual(report['next_task']['state'], 'written_unchecked')

    def test_partial_output_resumes_at_next_source_id(self):
        P.jsonl(self.initial, self.output[:1])
        report = self.report()
        self.assertEqual(report['written_records'], 1)
        self.assertEqual(report['next_task']['state'], 'partial')
        self.assertEqual(report['next_task']['next_sample_id'], self.output[1]['sample_id'])
        self.assertEqual(report['records_with_checks_passed'], 0)

    def test_existing_pass_file_cannot_hide_fabricated_evidence(self):
        C.write(self.base / 'validation.initial.json', {'passed': True})
        self.output[0]['tests'][0]['evidence']['quote'] = '伪造引用'
        P.jsonl(self.initial, self.output)
        report = self.report()
        self.assertEqual(report['next_task']['state'], 'needs_fix')
        self.assertEqual(report['records_with_checks_passed'], 0)
        self.assertIn('引文不在原文', report['next_task']['error'])

    def test_non_prefix_output_is_not_a_resumable_prefix(self):
        P.jsonl(self.initial, self.output[1:])
        self.assertEqual(self.report()['next_task']['state'], 'needs_fix')

    def test_initial_and_reviewed_progress_are_separate(self):
        self.assertTrue(self.report()['complete_for_stage'])
        report = self.report('reviewed')
        self.assertFalse(report['complete_for_stage'])
        self.assertEqual(report['written_records'], 0)
        self.review_fixture()
        self.assertTrue(self.report('reviewed')['complete_for_stage'])
        (self.base / 'reviews.jsonl').unlink()
        self.assertEqual(self.report('reviewed')['next_task']['state'], 'needs_fix')

    def test_reject_changed_plan_and_overlapping_assignment(self):
        self.report()
        path = self.root / 'macro-plan.json'
        plan = C.read(path)
        plan['macros'].append(plan['macros'][0])
        C.write(path, plan)
        with self.assertRaisesRegex(ValueError, '无重叠'):
            self.report()
        original_plan = C.read(self.bundle / 'plan.json')
        original_plan['remaining_record_count'] = 999
        C.write(self.bundle / 'plan.json', original_plan)
        with self.assertRaisesRegex(ValueError, '不是同一快照'):
            self.report()


if __name__ == '__main__':
    unittest.main()
