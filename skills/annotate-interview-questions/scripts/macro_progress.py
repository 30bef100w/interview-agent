#!/usr/bin/env python3
"""Locate resumable work in a 5,000-record assignment; never generate labels."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import check_collaboration as C

REPO = Path(__file__).resolve().parents[3]


def progress(plan_path, bundle, macro_id, stage):
    assignment = C.read(plan_path)
    bundle = Path(bundle).resolve()
    plan_path_in_bundle = bundle / 'plan.json'
    C.require(C.sha(plan_path_in_bundle) == assignment['source_plan_sha256'],
              '宏计划与解压数据包不是同一快照，请恢复匹配版本')
    plan = C.read(plan_path_in_bundle)
    C.require(assignment['corpus_id'] == plan['corpus_id'], '题库身份不符')
    expected = [row['task_id'] for row in plan['tasks']]
    assigned = [tid for group in assignment['macros'] for tid in group['task_ids']]
    C.require(assigned == expected, '宏批次必须按原顺序无重叠、无遗漏地覆盖原任务')
    entries = {row['task_id']: row for row in plan['tasks']}
    C.require(sum(row['count'] for row in plan['tasks']) == assignment['remaining_record_count'],
              '全库任务数量不符')
    for group in assignment['macros']:
        C.require(sum(entries[tid]['count'] for tid in group['task_ids']) == group['record_count'],
                  f"宏批次 {group['macro_id']} 题数不符")
    matches = [row for row in assignment['macros'] if row['macro_id'] == macro_id]
    C.require(len(matches) == 1, f'宏批次不存在或重复：{macro_id}')
    group = matches[0]
    details = []
    statuses = Counter()
    written = checked = 0
    reviewed = stage == 'reviewed'
    for tid in group['task_ids']:
        task_path = (bundle / entries[tid]['task']).resolve()
        C.require(task_path.is_relative_to(bundle), '任务路径越界')
        task, base, _, _, _, _, _ = C.load_task(task_path)
        output = base / task['outputs']['reviewed' if reviewed else 'initial']
        manifest = base / ('manifest.reviewed.json' if reviewed else 'manifest.initial.json')
        proposals = base / 'node_proposals.jsonl'
        detail = {'task_id': tid, 'task': str(task_path), 'planned': entries[tid]['count'],
                  'written_rows': 0, 'state': 'not_started'}
        try:
            if output.exists():
                rows = C.rows(output)
                ids = [row['sample_id'] for row in rows]
                planned_ids = task['planned_sample_ids']
                C.require(len(ids) == len(set(ids)) and set(ids) <= set(planned_ids),
                          '输出包含重复或跨批次ID')
                C.require(ids == planned_ids[:len(ids)], '断点输出必须是源顺序的连续前缀')
                detail['written_rows'] = len(rows)
                written += len(rows)
                detail['next_sample_id'] = planned_ids[len(ids)] if len(ids) < len(planned_ids) else None
                detail['state'] = 'partial' if len(ids) < len(planned_ids) else 'written_unchecked'
                if len(ids) == len(planned_ids) and manifest.exists():
                    C.audit(task_path, output, manifest,
                            proposals if proposals.exists() else None,
                            base / task['outputs']['reviews'] if reviewed else None,
                            reviewed=reviewed)
                    checked += len(ids)
                    detail['state'] = 'checks_passed'
        except (ValueError, KeyError, FileNotFoundError, TypeError) as error:
            detail.update(state='needs_fix', error=str(error))
        statuses[detail['state']] += 1
        details.append(detail)
    next_task = next((row for row in details if row['state'] != 'checks_passed'), None)
    return {'macro_id': macro_id, 'stage': stage, 'planned_records': group['record_count'],
            'written_records': written, 'records_with_checks_passed': checked,
            'complete_for_stage': next_task is None, 'task_states': dict(statuses),
            'next_task': next_task, 'tasks': details, 'semantic_accuracy_proven': False,
            'note': '校验只核对覆盖、格式、哈希、引文及复核声明；不证明实际逐题阅读或语义正确。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--macro', required=True, help='M01–M08')
    parser.add_argument('--plan', type=Path, default=REPO / 'docs/annotation-collaboration/macro-plan.json')
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--stage', choices=['initial', 'reviewed'], default='initial')
    parser.add_argument('--out', type=Path, help='只写进度检查点，不修改任务配置')
    args = parser.parse_args()
    try:
        bundle = args.bundle or REPO / C.read(args.plan)['bundle_root']
        result = progress(args.plan, bundle, args.macro, args.stage)
        if args.out:
            protected = ['plan.json', 'task.json', 'source.jsonl', 'macro-plan.json']
            C.require(args.out.name not in protected, '进度输出不得覆盖任务输入')
            args.out.parent.mkdir(parents=True, exist_ok=True)
            C.write(args.out, result)
        print(json.dumps({key: value for key, value in result.items() if key != 'tasks'},
                         ensure_ascii=False, indent=2))
    except (ValueError, KeyError, FileNotFoundError, TypeError) as error:
        parser.exit(1, f'宏批次检查失败：{error}\n')


if __name__ == '__main__':
    main()
