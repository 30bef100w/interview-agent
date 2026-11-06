#!/usr/bin/env python3
"""Run pure graph retrieval against a directory or the published offline ZIP.

Default operation consumes resolved seed IDs and performs no model/network calls.
--resolve-seeds explicitly opts into the configured LLM for raw profile projects.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.graph_retrieval import GraphIndex, GraphRetriever, GraphRetrievalConfig, ProjectQuery


def load_graph(path, include_drafts):
    if path.is_dir(): return GraphIndex.from_directory(path, include_drafts=include_drafts)
    # Read only the two expected members; no filesystem extraction / zip-slip.
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.endswith('/nodes.jsonl') or name == 'nodes.jsonl']
        if len(candidates) != 1: raise ValueError('archive must have one nodes.jsonl')
        name = candidates[0]; prefix = name[:-len('nodes.jsonl')]
        nodes = [json.loads(line) for line in archive.read(name).decode('utf-8').splitlines() if line.strip()]
        edges = [json.loads(line) for line in archive.read(prefix+'edges.jsonl').decode('utf-8').splitlines() if line.strip()]
    return GraphIndex(nodes, edges, include_drafts=include_drafts)


def run(graph, payload, *, seed=42, resolve_model=None, include_candidates=False):
    cfg = GraphRetrievalConfig(**payload.get('config', {}))
    retriever = GraphRetriever(graph); selected = set(payload.get('exclude_question_ids', [])); outputs = []
    resolver = None
    for i, item in enumerate(payload.get('projects', [])):
        resolution = None
        if 'scene_ids' in item and 'concept_ids' in item:
            for key in ('scene_ids', 'concept_ids'):
                if not isinstance(item[key], list) or not all(isinstance(v, str) for v in item[key]):
                    raise ValueError(f'{key} must be a list of graph IDs')
            query = ProjectQuery(project_id=str(item.get('project_id', i+1)), project_text=item.get('project_text',''),
                                 focus=item.get('focus',''), scene_ids=tuple(item['scene_ids']),
                                 concept_ids=tuple(item['concept_ids']), company=item.get('company',payload.get('company')))
        elif resolve_model is not None:
            from app.services.graph_seed_resolver import GraphSeedResolver
            resolver = resolver or GraphSeedResolver(graph, max_scene_seeds=cfg.max_scene_seeds,
                                                       max_concept_seeds=cfg.max_concept_seeds)
            resolution = resolver.resolve(item.get('project', item), resolve_model,
                                           project_id=str(item.get('project_id',i+1)),
                                           company=item.get('company',payload.get('company')), focus=item.get('focus',''))
            query = resolution.query
        else:
            raise ValueError('each project needs scene_ids and concept_ids; raw projects require --resolve-seeds')
        started = time.perf_counter()
        result = retriever.project_retrieve(query, config=cfg, seed=seed+i,
                                           asked_question_ids=payload.get('asked_question_ids', []),
                                           asked_question_norms=payload.get('asked_question_norms', []),
                                           exclude_question_ids=selected, history=payload.get('history',{}))
        result['meta']['elapsed_ms'] = round((time.perf_counter()-started)*1000,3)
        if not include_candidates: result.pop('candidates')
        if resolution is not None: result['seed_resolution'] = resolution.as_dict()
        outputs.append(result)
        for q in result['questions']:
            selected.update(q['source_question_ids']); selected.add(q['canonical_question_id'])
    bagu_spec = payload.get('bagu', {})
    bagu = retriever.bagu_retrieve(domain_concept_ids=bagu_spec.get('domain_concept_ids', []),
                                   count=bagu_spec.get('count',0), seed=seed,
                                   asked_question_ids=payload.get('asked_question_ids', []),
                                   asked_question_norms=payload.get('asked_question_norms', []),
                                   exclude_question_ids=selected)
    return {'schema_version':'1.0.0','implementation':'graph_retrieval_v1_offline',
            'seed':seed,'config':asdict(cfg),'include_drafts':graph.include_drafts,'projects':outputs,'bagu':bagu}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph',type=Path,default=ROOT/'docs/graph-demo/mgkg-9000-v3.zip')
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--include-drafts',action='store_true')
    parser.add_argument('--include-candidates',action='store_true')
    parser.add_argument('--include-answers',action='store_true')
    parser.add_argument('--resolve-seeds',action='store_true',help='explicitly call the configured LLM for raw projects')
    args=parser.parse_args()
    if args.out.exists(): parser.error('choose a fresh --out file; historical runs are not overwritten')
    payload=json.loads(args.input.read_text(encoding='utf-8'))
    if not isinstance(payload,dict): parser.error('--input must contain a JSON object')
    started=time.perf_counter(); graph=load_graph(args.graph,args.include_drafts)
    load_ms=(time.perf_counter()-started)*1000
    model=None
    if args.resolve_seeds:
        from app.services.llm.client import OpenAiLlm
        model=OpenAiLlm()
    result=run(graph,payload,seed=args.seed,resolve_model=model,include_candidates=args.include_candidates)
    if not args.include_answers:
        for project in result['projects']:
            for key in ('questions','candidates'):
                for q in project.get(key,[]): q.pop('answer',None)
        for q in result['bagu']['questions']:q.pop('answer',None)
    result['graph_path']=str(args.graph);result['graph_load_ms']=round(load_ms,3)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('x',encoding='utf-8') as handle:
        handle.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(args.out),'projects':[p['meta'] for p in result['projects']],
                      'bagu':result['bagu']['meta'],'graph_load_ms':result['graph_load_ms']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
