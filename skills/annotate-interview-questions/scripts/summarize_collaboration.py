#!/usr/bin/env python3
"""Audit partition coverage and report actual files; never fill missing labels."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import check_collaboration as C


def summarize(bundle):
    root=Path(bundle);plan=C.read(root/'plan.json');all_rows=C.rows(root/'context/full-source.jsonl')
    C.require(C.sha(root/'context/full-source.jsonl')==plan['context_sha256'],'全库上下文哈希不符')
    excluded=C.read(root/'excluded-existing.json');seen=set();initial=reviewed=ready=0;details=[]
    for entry in plan['tasks']:
        task,base,resolve,src,registry,scene,source=C.load_task(root/entry['task'])
        ids={r['sample_id'] for r in source};C.require(not ids & seen,'任务之间存在重复源记录');seen.update(ids)
        C.require(len(source)==entry['count'],'分片记录数不符')
        i=base/'annotations.jsonl';r=base/'reviewed_annotations.jsonl'
        ni=len(C.rows(i)) if i.exists() else 0;nr=len(C.rows(r)) if r.exists() else 0
        initial+=ni;reviewed+=nr
        state='not_started';error=None
        if ni:state='initial_written_unverified'
        if nr:state='review_written_unverified'
        if r.exists() and (base/'manifest.reviewed.json').exists() and (base/'reviews.jsonl').exists():
            try:
                proposals=base/'node_proposals.jsonl'
                C.audit(root/entry['task'],r,base/'manifest.reviewed.json',proposals if proposals.exists() else None,
                        base/'reviews.jsonl',reviewed=True)
                state='review_records_and_checks_complete';ready+=len(source)
            except (ValueError,KeyError) as e:error=str(e)
        details.append({'task_id':task['task_id'],'planned':len(source),'initial_rows':ni,'reviewed_rows':nr,
                        'state':state,'error':error})
    old_ids=[r['full_sample_id'] for r in excluded]
    C.require(len(old_ids)==len(set(old_ids)) and not set(old_ids)&seen,'原有排除清单重复或与新任务重叠')
    C.require(seen | set(old_ids)=={r['sample_id'] for r in all_rows},'任务与既有记录未完整覆盖全库')
    C.require(len(seen)==plan['remaining_record_count'],'待处理总数不符')
    return {'source_partition_valid':True,'original_records':len(all_rows),'excluded_existing_records':len(old_ids),
      'planned_new_records':len(seen),'task_count':len(details),'initial_file_rows':initial,'reviewed_file_rows':reviewed,
      'records_with_complete_review_attestation_and_checks':ready,'semantic_accuracy_proven':False,
      'note':'文件记录、引用与AI复核声明可核查，脚本不能证明模型实际阅读或语义100%正确。','tasks':details}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--bundle',required=True,type=Path);parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    try:result=summarize(args.bundle)
    except (ValueError,KeyError,FileNotFoundError) as e:parser.exit(1,f'汇总失败：{e}\n')
    if args.out:C.write(args.out,result)
    print(json.dumps({k:v for k,v in result.items() if k!='tasks'},ensure_ascii=False,indent=2))
