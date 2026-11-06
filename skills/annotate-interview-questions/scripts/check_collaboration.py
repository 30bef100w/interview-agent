#!/usr/bin/env python3
"""Portable task inspection, truthful manifests and evidence auditing (stdlib).

This tool never creates semantic tags, approval decisions or review attestations.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import sys
import validate_annotations as protocol


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def rows(path):return protocol.read_lines(Path(path))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def require(value,message):
    if not value:raise ValueError(message)


def load_task(path):
    path=Path(path).resolve();task=read(path);base=path.parent
    root=(base/task['bundle_root']).resolve()
    plan=read(root/'plan.json')
    entry=[r for r in plan['tasks'] if r['task_id']==task['task_id']]
    require(len(entry)==1 and sha(path)==entry[0]['task_sha256'],'任务配置已改变或不在总计划中；请恢复原始task.json')
    require(plan['corpus_id']==task['corpus_id'],'任务与全库快照身份不符')
    def resolve(relative):
        target=(base/relative).resolve()
        require(target.is_relative_to(root),f'任务路径超出数据包：{relative}')
        require(target.is_file(),f'缺少文件：{target}；请完整解压数据包，勿单独复制task.json')
        return target
    source=resolve(task['source_file']);registry=resolve(task['registry']);scenes=resolve(task['scene_registry'])
    require(sha(source)==task['source_sha256'],'源数据哈希不符；勿修改原题或用另一批次替换文件')
    require(sha(registry)==task['registry_sha256'],'知识点索引哈希不符；请恢复固定版本')
    source_rows=rows(source)
    require([r['sample_id'] for r in source_rows]==task['planned_sample_ids'],'源记录ID/顺序不符')
    # Scene catalogs may legitimately evolve locally; initial hash is retained.
    protocol.load_scene_registry(scenes)
    return task,base,resolve,source,registry,scenes,source_rows


def manifest(task_path,annotations_path,proposals_path=None):
    task,base,resolve,source,registry,scenes,source_rows=load_task(task_path)
    annotation=rows(annotations_path);proposals=rows(proposals_path) if proposals_path else []
    ids=[r['sample_id'] for r in annotation];planned=task['planned_sample_ids']
    require(len(ids)==len(set(ids)) and set(ids)<=set(planned),'输出有重复ID或跨批次ID')
    require(ids==[sid for sid in planned if sid in set(ids)],'输出顺序应沿用源记录顺序')
    reviewed=[r for r in annotation if r.get('review_stage')=='review']
    return {'schema_version':'1.0.0','task_id':task['task_id'],'corpus_id':task['corpus_id'],
      'registry_version':task['registry_version'],'registry_sha256':sha(registry),
      'source_file':task['source_file'],'source_sha256':sha(source),
      'scene_registry_version':read(scenes)['registry_version'],'scene_registry_sha256':sha(scenes),
      'initial_scene_registry_sha256':task['scene_registry_sha256'],
      'planned_sample_ids':planned,'completed_sample_ids':ids,
      'reviewed_sample_ids':[r['sample_id'] for r in reviewed],
      'full_reviewed_sample_ids':[r['sample_id'] for r in reviewed if r.get('review_scope')=='full'],
      'status_counts':dict(Counter(r['record_status'] for r in annotation)),
      'review_stage_counts':dict(Counter(r['review_stage'] for r in annotation)),
      'review_scope_counts':dict(Counter(r.get('review_scope') or 'unspecified' for r in reviewed)),
      'proposal_count':len(proposals),
      'provenance_note':'仅从AI实际输出统计。文件行数、review字段和校验通过均不能独立证明AI已读题或语义正确。'}


def audit(task_path,annotations_path,manifest_path,proposals_path=None,review_log_path=None,allow_partial=False,reviewed=False):
    task,base,resolve,source,registry,scenes,source_rows=load_task(task_path)
    m=read(manifest_path);annotation=rows(annotations_path)
    require(m.get('source_sha256')==sha(source),'manifest源哈希不符')
    require(m.get('registry_sha256')==sha(registry),'manifest知识点索引哈希不符')
    require(m.get('corpus_id')==task['corpus_id'],'manifest不属于本任务快照')
    require(m.get('registry_version')==task['registry_version'],'manifest知识点版本与任务不符')
    require(m.get('planned_sample_ids')==task['planned_sample_ids'],'manifest改写了任务范围')
    require(m.get('source_file')==task['source_file'],'manifest源定位不符')
    args=SimpleNamespace(annotations=Path(annotations_path),registry=registry,scene_registry=scenes,
      scene_nodes=None,manifest=Path(manifest_path),proposals=Path(proposals_path) if proposals_path else None,
      allow_partial=allow_partial,require_reviewed=reviewed,regression_cases=None)
    result=protocol.validate(args)
    sources={'source.jsonl':source_rows}
    def quoted(evidence):
        locator=evidence['locator'];match=re.fullmatch(r'([^/:\\]+\.jsonl):(\d+)#(question|answer|source_file)',locator)
        require(match is not None,f'不可解析引用：{locator}；格式为source.jsonl:行号#question/answer/source_file')
        filename,line,field=match.groups();line=int(line)
        if filename not in sources:
            spec=task.get('context_sources',{}).get(filename)
            require(spec is not None,f'未登记的上下文文件：{filename}')
            context=resolve(spec['path']);require(sha(context)==spec['sha256'],f'上下文文件哈希不符：{filename}')
            sources[filename]=rows(context)
        require(1<=line<=len(sources[filename]),f'引用行号越界：{locator}')
        text=sources[filename][line-1].get(field)
        require(isinstance(text,str) and isinstance(evidence.get('quote'),str) and bool(evidence['quote'].strip())
                and evidence['quote'] in text,f'引文不在原文：{locator} → {evidence.get("quote")}')
        return filename,line,field
    by_id={r['sample_id']:(i,r) for i,r in enumerate(source_rows,1)}
    quote_count=0
    for row in annotation:
        line,original=by_id[row['sample_id']]
        require(row['source_locator']==f'source.jsonl:{line}',f'{row["sample_id"]}源行定位错误')
        contexts={(r['locator'],r['quote']) for r in row['context_refs']}
        for reference in row['context_refs']:quoted(reference);quote_count+=1
        for kind in ('tests','requires','scenes','scene_concept_links'):
            for relation in row[kind]:
                ev=relation['evidence'];filename,evline,field=quoted(ev);quote_count+=1
                if relation['basis']=='question':
                    require((filename,evline,field)==('source.jsonl',line,'question'),
                            f'{row["sample_id"]}的question依据引用了别题或非题干')
                else:
                    require((ev['locator'],ev['quote']) in contexts,
                            f'{row["sample_id"]}非题干依据必须同时记录在context_refs')
    proposals=rows(proposals_path) if proposals_path else []
    for proposal in proposals:quoted(proposal['evidence']);quote_count+=1
    if sha(scenes)!=task['scene_registry_sha256']:
        require(read(scenes)['registry_version']!=task['scene_registry_version'],'场景库变化后必须更新版本')
        md=resolve(task['scene_catalog']);text=md.read_text(encoding='utf-8')
        require(text.strip(),'场景解释MD缺失')
        old={r['id']:r for r in read((base/task['bundle_root']).resolve()/'catalog/scene-registry.json')['scenes']}
        changed=[r for r in read(scenes)['scenes'] if r['id'] not in old or r!=old[r['id']]]
        if changed:
            require(sha(md)!=task['scene_catalog_sha256'],'场景定义有变化但解释MD未同步')
            for scene in changed:require(scene['id'] in text and scene['name'] in text,'变更场景缺少MD身份与中文介绍')
    if reviewed:
        require(review_log_path is not None,'最终复核还需要--review-log，不能仅把review_stage改成review')
        log=rows(review_log_path);by_log={r['sample_id']:r for r in log}
        require(len(by_log)==len(log) and set(by_log)==set(by_id),'逐题复核日志有漏项、重复或跨批次记录')
        initial_path=base/task['outputs']['initial']
        require(initial_path.is_file() and Path(annotations_path).resolve()!=initial_path,'复核必须保留初标原件，另写reviewed_annotations.jsonl')
        initial_rows=rows(initial_path);initial={r['sample_id']:r for r in initial_rows}
        require(len(initial)==len(initial_rows) and [r['sample_id'] for r in initial_rows]==task['planned_sample_ids'],
                '初标原件重复、缺题、乱序或跨批次，先完成初标范围检查')
        for row in annotation:
            review=by_log[row['sample_id']]
            require(review.get('decision') in ('pass','fixed','needs_context','not_question'), '无效复核结论')
            require(isinstance(review.get('reason'),str) and review['reason'].strip(),'逐题复核缺少具体理由')
            expected={'status','context','tests','requires','scenes','scene_concept_links'} if row['record_status']=='labeled' else {'status','context'}
            require(set(review.get('checked_fields',[]))>=expected,'逐题复核范围不全')
            require(isinstance(review.get('evidence'),list) and review['evidence'],'复核需要短原文依据')
            for ref in review['evidence']:quoted(ref);quote_count+=1
            semantic_fields=('record_status','normalized_question','context_refs','tests','requires','scenes','scene_concept_links')
            actual={key for key in semantic_fields if initial[row['sample_id']].get(key)!=row.get(key)}
            if review['decision']=='pass':require(not actual,'复核声明pass却暗改标签或状态')
            if review['decision']=='fixed':
                changes=review.get('changes',[])
                require(actual and {c.get('field') for c in changes}==actual,'fixed必须列明实际修改的字段')
                for c in changes:
                    require(c.get('before')==initial[row['sample_id']].get(c['field']) and c.get('after')==row.get(c['field']),
                            '复核修改前后值与文件不一致')
            if review['decision'] in ('needs_context','not_question'):
                require(row['record_status']==review['decision'],'复核日志结论与最终状态不一致')
    result.update(source_quotes_checked=True,quote_count=quote_count,source_sha256_checked=True,
      registry_sha256_checked=True,review_log_complete=reviewed,
      technical_empty_tests=[r['sample_id'] for r in annotation if r['record_status']=='labeled' and not r['tests']],
      semantic_accuracy_checked=False,
      note='范围、哈希、字段、引用和声明覆盖检查通过；不替代AI逐题语义复核，也不批准新增节点。')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['inspect','manifest','check','catalog'])
    parser.add_argument('--task',required=True,type=Path);parser.add_argument('--annotations',type=Path)
    parser.add_argument('--manifest',type=Path);parser.add_argument('--proposals',type=Path);parser.add_argument('--review-log',type=Path)
    parser.add_argument('--out',type=Path);parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--reviewed',action='store_true');parser.add_argument('--query');parser.add_argument('--parent');parser.add_argument('--node')
    parser.add_argument('--offset',type=int,default=0);parser.add_argument('--limit',type=int,default=30)
    args=parser.parse_args()
    try:
        if args.mode=='inspect':
            t,*_=load_task(args.task);result={k:t[k] for k in ('task_id','corpus_id','registry_version','planned_sample_ids','status','semantic_annotation_completed')}
            result['next']='AI阅读source.jsonl并自主判断；脚本不会自动标注。'
        elif args.mode=='catalog':
            t,b,res,src,registry,scene,source_rows=load_task(args.task);catalog=read(registry)
            if args.parent:catalog=[r for r in catalog if args.parent in r['parents'] or r['id']==args.parent]
            if args.query:
                needle=args.query.casefold();catalog=[r for r in catalog if needle in json.dumps(r,ensure_ascii=False).casefold()]
            if args.node:catalog=[r for r in catalog if r['id']==args.node]
            require(args.limit>0 and args.offset>=0,'limit需为正数，offset不能为负')
            all_nodes={r['id']:r for r in read(registry)}
            selected=[{**r,'parent_nodes':[{'id':pid,'name':all_nodes[pid]['name']} for pid in r['parents']]}
                      for r in catalog[args.offset:args.offset+args.limit]]
            result={'search_only_not_labels':True,'total_matches':len(catalog),'offset':args.offset,
                    'has_more':args.offset+args.limit<len(catalog),'matches':selected}
        else:
            require(args.annotations is not None,'需要--annotations <AI输出.jsonl>')
            if args.mode=='manifest':result=manifest(args.task,args.annotations,args.proposals)
            else:
                require(args.manifest is not None,'需要--manifest <批次清单.json>')
                result=audit(args.task,args.annotations,args.manifest,args.proposals,args.review_log,args.allow_partial,args.reviewed)
        if args.out:write(args.out,result)
        else:print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,KeyError,FileNotFoundError,json.JSONDecodeError) as error:
        parser.exit(1,f'检查失败：{error}\n先修正数据或补齐实际工作，不要通过改完成数、范围或关闭检查绕过。\n')


if __name__=='__main__':main()
