#!/usr/bin/env python3
"""Freeze disjoint annotation tasks. No semantic labels are generated here."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def lines(data):
    return [json.loads(l) for l in data.decode('utf-8-sig').splitlines() if l.strip()]


def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def jsonl(path, rows):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')


def graph_file(graph, name):
    graph=Path(graph)
    if graph.is_dir():return (graph/name).read_bytes()
    with zipfile.ZipFile(graph) as z:
        candidates=[n for n in z.namelist() if Path(n).name==name and '__MACOSX' not in n]
        if not candidates:raise FileNotFoundError(f'图ZIP缺少{name}')
        if len(candidates)!=1:raise ValueError(f'图ZIP中{name}必须恰好一份，实际{candidates}')
        return z.read(candidates[0])


def export_catalog(graph, destination):
    destination=Path(destination);nodes=lines(graph_file(graph,'nodes.jsonl'));edges=lines(graph_file(graph,'edges.jsonl'))
    concepts={n['id']:n for n in nodes if n['node_type']=='Concept'}
    parents=defaultdict(list)
    for e in edges:
        if e['relation']=='HAS_SUBTOPIC':parents[e['dst_id']].append(e['src_id'])
    ids={gid:n['properties']['concept_id'] for gid,n in concepts.items()}
    try:redirects=json.loads(graph_file(graph,'entity_redirects.json'))
    except FileNotFoundError:redirects={}
    legacy=defaultdict(list)
    for old in redirects:
        target=old;seen=set()
        while target in redirects and redirects[target]!=target:
            if target in seen:raise ValueError('显式旧ID映射存在环')
            seen.add(target);target=redirects[target]
        if target in ids.values() and old!=target:legacy[target].append(old)
    rows=[]
    for gid,n in concepts.items():
        props=n['properties'];profile=props.get('detail_profile') or {}
        rows.append({'id':ids[gid],'name':n['name'],'parents':[ids[p] for p in sorted(parents[gid])],
                     'definition':props.get('definition') or profile.get('introduction') or '',
                     'aliases':props.get('aliases',[]),'legacy_ids':sorted(legacy[ids[gid]]),'kind':props.get('kind','topic'),
                     'state':n['state'],'scope_boundary':profile.get('scope_boundary',''),
                     'review_status':props.get('review_status') or props.get('origin')})
    # Explicit graph relationships only; no ID-prefix or name-based parent inference.
    write(destination/'concept-registry.json',sorted(rows,key=lambda x:x['id']))
    write(destination/'catalog-manifest.json',{'registry_version':'2026-11-06.graph-v3-export',
       'concepts':len(rows),'states':dict(Counter(r['state'] for r in rows)),
       'explicit_legacy_id_count':sum(len(r['legacy_ids']) for r in rows),
       'graph_sha256':{name:sha(graph_file(graph,name)) for name in ('nodes.jsonl','edges.jsonl')},
       'note':'正式和草稿身份保留；导出不是批准草稿，标注复用仍需判断语义。'})


def prepare(source_zip, known_annotations, known_source, graph, out, batch_size=100):
    out=Path(out)
    if out.exists():raise ValueError(f'输出目录已存在，不覆盖：{out}')
    if batch_size<1:raise ValueError('batch_size必须大于0')
    with zipfile.ZipFile(source_zip) as z:
        raw=z.read('knowledge_base/questions_dedup.jsonl')
    original=lines(raw);known=lines(Path(known_annotations).read_bytes());sample=lines(Path(known_source).read_bytes())
    by_sid={r['sample_id']:r for r in sample}
    if len(by_sid)!=len(sample):raise ValueError('既有源快照ID重复')
    excluded={}
    for label in known:
        sid=label['sample_id']
        if sid not in by_sid:raise ValueError(f'既有标注缺源记录：{sid}')
        old=by_sid[sid];i=old['source_index']
        if i in excluded:raise ValueError(f'既有标签重复源索引：{i}')
        if not 0<=i<len(original):raise ValueError(f'源索引越界：{sid}')
        # Verify every original field, including answers, companies and provenance.
        if any(old.get(k)!=v for k,v in original[i].items()):
            raise ValueError(f'既有源记录与全库不一致：{sid}，不可按题干猜排除')
        excluded[i]={'existing_corpus_id':label['corpus_id'],'existing_sample_id':sid,
                     'full_sample_id':f'F{i+1:06d}','source_index':i,'record_status':label['record_status']}
    corpus_id='full-'+sha(raw)[:16]
    normalized=[{**r,'sample_id':f'F{i+1:06d}','source_index':i,'source_line':i+1}
                for i,r in enumerate(original)]
    remaining=[r for i,r in enumerate(normalized) if i not in excluded]
    out.mkdir(parents=True)
    jsonl(out/'context'/'full-source.jsonl',normalized)
    write(out/'excluded-existing.json',list(excluded.values()))
    catalog=out/'catalog';export_catalog(graph,catalog)
    skill=Path(__file__).resolve().parents[1]
    shutil.copyfile(skill/'references/scene-registry.json',catalog/'scene-registry.json')
    shutil.copyfile(skill/'references/scene-catalog.md',catalog/'scene-catalog.md')
    registry_sha=sha((catalog/'concept-registry.json').read_bytes())
    context_sha=sha((out/'context/full-source.jsonl').read_bytes())
    tasks=[]
    for offset in range(0,len(remaining),batch_size):
        tid=f'B{offset//batch_size+1:04d}';directory=out/'tasks'/tid;directory.mkdir(parents=True)
        source=remaining[offset:offset+batch_size];jsonl(directory/'source.jsonl',source)
        shutil.copyfile(catalog/'scene-registry.json',directory/'scene-registry.json')
        shutil.copyfile(catalog/'scene-catalog.md',directory/'scene-catalog.md')
        task={'schema_version':'1.0.0','task_id':tid,'corpus_id':corpus_id,
          'bundle_root':'../..','source_file':'source.jsonl','source_sha256':sha((directory/'source.jsonl').read_bytes()),
          'registry':'../../catalog/concept-registry.json','registry_version':'2026-11-06.graph-v3-export',
          'registry_sha256':registry_sha,'scene_registry':'scene-registry.json','scene_catalog':'scene-catalog.md',
          'scene_registry_version':read(directory/'scene-registry.json')['registry_version'],
          'scene_registry_sha256':sha((directory/'scene-registry.json').read_bytes()),
          'scene_catalog_sha256':sha((directory/'scene-catalog.md').read_bytes()),
          'context_sources':{'full-source.jsonl':{'path':'../../context/full-source.jsonl','sha256':context_sha}},
          'planned_sample_ids':[r['sample_id'] for r in source],
          'outputs':{'initial':'annotations.jsonl','reviewed':'reviewed_annotations.jsonl','reviews':'reviews.jsonl'},
          'assignee':None,'status':'unassigned','semantic_annotation_completed':False}
        write(directory/'task.json',task)
        tasks.append({'task_id':tid,'task':'tasks/'+tid+'/task.json','count':len(source),
                      'first_id':source[0]['sample_id'],'last_id':source[-1]['sample_id'],'source_sha256':task['source_sha256'],
                      'task_sha256':sha((directory/'task.json').read_bytes())})
    manifest={'schema_version':'1.0.0','corpus_id':corpus_id,'original_record_count':len(original),
       'excluded_existing_count':len(excluded),'remaining_record_count':len(remaining),'task_count':len(tasks),
       'batch_size':batch_size,'original_questions_sha256':sha(raw),
       'existing_annotations_sha256':sha(Path(known_annotations).read_bytes()),
       'existing_source_sha256':sha(Path(known_source).read_bytes()),
       'context_sha256':context_sha,'registry_sha256':registry_sha,'tasks':tasks,
       'semantic_annotation_completed':False,'note':'仅固定范围、分批与归档；没有生成任何语义标签。'}
    write(out/'plan.json',manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source-zip','known-annotations','known-source','graph','out'):
        parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--batch-size',type=int,default=100)
    args=parser.parse_args()
    try:
        result=prepare(args.source_zip,args.known_annotations,args.known_source,args.graph,args.out,args.batch_size)
    except (ValueError,KeyError,FileNotFoundError,zipfile.BadZipFile) as e:
        parser.exit(1,f'准备失败：{e}\n请核对输入快照，勿自行猜测或覆盖旧批次。\n')
    print(json.dumps({k:v for k,v in result.items() if k!='tasks'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
