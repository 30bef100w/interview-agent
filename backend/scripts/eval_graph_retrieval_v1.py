#!/usr/bin/env python3
"""Controlled offline A/B: original scoring, flat semantic edges, real graph v1.

prepare freezes runs and builds a method-blind top-K judgment pool; score refuses
missing judgments. No API calls, graph mutation, model judge, or label-as-gold.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from app.services.graph_retrieval import GraphIndex, GraphRetriever, GraphRetrievalConfig, ProjectQuery
from app.services.knowledge_retrieval import _score_question

ARMS = ('original_tags', 'flat_semantic', 'graph_v1')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def original_rank(graph, query, config, seed):
    """Reuse production B-lane score, without its noisy/topic bigram filters.

    This is a transparent scoring-component baseline, not the production A+B+LLM
    pipeline. Only the original tags/text/answer/era/roles are used. No semantic
    graph relations. Randomize score ties; impose the same candidate cap.
    """
    scored = []
    for qid, node in graph.nodes.items():
        if node['node_type'] != 'Question' or not graph.eligible(qid):
            continue
        props = node['properties']
        row = {**props.get('original_tags', {}), 'question': node['name'],
               'answer': props.get('answer'), 'roles': props.get('roles', []),
               'era': props.get('era'), 'company': props.get('company')}
        score = _score_question(row, {query['role']}, None,
                                [s.lower() for s in query['skills']],
                                set(query['legacy_scenes']), None,
                                recall_boost_terms=[], lane='b')
        if score > 0:
            scored.append((score, qid))
    random.Random(seed).shuffle(scored)
    scored.sort(key=lambda x: x[0], reverse=True)
    cap = config.kg_candidate_limit + config.mg_candidate_limit
    candidates = [qid for _, qid in scored[:cap]]
    return {'selected': candidates[:config.final_limit], 'candidates': candidates,
            'meta': {'eligible_scored': len(scored), 'unique_candidates': len(candidates)}}


def prepare(protocol_path, out):
    protocol_path, out = Path(protocol_path), Path(out)
    protocol = read_json(protocol_path)
    graph_dir = ROOT / protocol['graph']
    nodes = [json.loads(x) for x in (graph_dir/'nodes.jsonl').read_text().splitlines() if x.strip()]
    edges = [json.loads(x) for x in (graph_dir/'edges.jsonl').read_text().splitlines() if x.strip()]
    graph = GraphIndex(nodes, edges, include_drafts=protocol['include_drafts'])
    # Exact same implementation, rank and quota logic; ablate only graph expansion.
    flat = GraphIndex(nodes, [e for e in edges if e['relation'] in ('TESTS', 'HAS_QUESTION', 'REQUIRES')],
                      include_drafts=protocol['include_drafts'])
    cfg = GraphRetrievalConfig(**protocol['config'])
    queries = protocol['queries']
    if len({q['id'] for q in queries}) != len(queries):
        raise ValueError('duplicate query IDs')
    runs, pooled = [], {}
    for query in queries:
        project = ProjectQuery(project_id=query['id'], project_text=query['text'],
                               scene_ids=tuple(query['scene_ids']), concept_ids=tuple(query['concept_ids']))
        for seed in protocol['seeds']:
            for arm in ARMS:
                started = time.perf_counter()
                if arm == 'original_tags':
                    result = original_rank(graph, query, cfg, seed)
                else:
                    raw = GraphRetriever(flat if arm == 'flat_semantic' else graph).project_retrieve(
                        project, config=cfg, seed=seed)
                    result = {'selected': [q['question_id'] for q in raw['questions']],
                              'candidates': [q['question_id'] for q in raw['candidates']],
                              'meta': raw['meta'],
                              'selected_paths': {q['question_id']: q['paths'] for q in raw['questions']}}
                result.update(query_id=query['id'], seed=seed, arm=arm,
                              elapsed_ms=round((time.perf_counter()-started)*1000, 3))
                if len(result['candidates']) > cfg.kg_candidate_limit+cfg.mg_candidate_limit:
                    raise ValueError('candidate cap exceeded')
                if 'judgment_sample_size' in protocol:
                    sample_size = protocol['judgment_sample_size']
                    salt = int(hashlib.sha256((query['id']+'|'+arm).encode()).hexdigest()[:12], 16)
                    result['judgment_ids'] = random.Random(seed ^ salt).sample(
                        result['selected'], min(sample_size, len(result['selected'])))
                else:
                    result['judgment_ids'] = list(result['selected'])
                norms = [''.join(ch for ch in graph.nodes[qid]['name'].casefold() if ch.isalnum())
                         for qid in result['selected']]
                result['selected_text_duplicate_count'] = len(norms)-len(set(norms))
                runs.append(result)
                for qid in result['judgment_ids']:
                    key = (query['id'], qid)
                    if key in pooled:
                        continue
                    node = graph.nodes[qid]; props = node['properties']
                    pid = hashlib.sha256(('blind-v1|'+query['id']+'|'+qid).encode()).hexdigest()[:16]
                    pooled[key] = {'pool_id': pid, 'query_id': query['id'], 'question_id': qid,
                                   'question': node['name'], 'source_file': props.get('source_file'),
                                   'context_refs': props.get('context_refs', [])}
    pool = sorted(pooled.values(), key=lambda x: (x['query_id'], x['pool_id']))
    out.mkdir(parents=True, exist_ok=False)
    write_json(out/'protocol.json', protocol)
    write_json(out/'manifest.json', {
        'protocol_sha256': fingerprint(protocol_path),
        'graph_sha256': {name: fingerprint(graph_dir/name) for name in ('nodes.jsonl', 'edges.jsonl')},
        'code_sha256': {name: fingerprint(ROOT/name) for name in (
            'backend/scripts/eval_graph_retrieval_v1.py', 'backend/app/services/graph_retrieval.py',
            'backend/app/services/knowledge_retrieval.py', 'backend/app/services/scene_tag_similarity.py')},
        'corpus_questions': sum(n['node_type']=='Question' for n in nodes),
        'nodes_by_type_state': dict(Counter(n['node_type']+':'+n['state'] for n in nodes)),
        'runs': len(runs), 'pooled_query_question_pairs': len(pool), 'config': asdict(cfg),
        'arms': {'original_tags': 'production B-lane score only, no noisy/bigram filters',
                 'flat_semantic': 'same v1 retriever, TESTS/HAS_QUESTION only',
                 'graph_v1': 'unmodified GraphRetriever with active edges'},
        'limits': ['fixed manually resolved seeds; not end-to-end', 'development queries',
                   'single-assistant semantic judgments; no independent human gold',
                   'pooled top-K judgments do not establish corpus recall',
                   'K=5 shortlist experiment; not the default 100-question pool']})
    write_json(out/'runs.json', runs)
    write_json(out/'pool_key.json', pool)
    # This file deliberately hides question IDs, labels, paths, ranks and arms.
    blind = [{k:v for k,v in row.items() if k!='question_id'} for row in pool]
    write_json(out/'blind_pool.json', blind)
    write_json(out/'judgments.template.json', [{
        'pool_id':row['pool_id'], 'grade':None, 'scene_match':None, 'reason':''} for row in pool])
    print(json.dumps({'out':str(out), 'runs':len(runs), 'pool':len(pool)}, ensure_ascii=False))


def summarize(protocol, runs, pool, judgments):
    k = protocol['config']['final_limit']
    if k <= 0:
        raise ValueError('evaluation K must be positive')
    if 'judgment_sample_size' in protocol:
        raise ValueError('sampled pool audit requires summarize_sampled, not exact P@K')
    by_id = {r['pool_id']:r for r in judgments}
    expected = {r['pool_id'] for r in pool}
    if len(by_id)!=len(judgments) or set(by_id)!=expected:
        raise ValueError('judgments must cover every pooled pair exactly once, with no extras')
    for row in judgments:
        if type(row.get('grade')) is not int or row['grade'] not in (0,1,2):
            raise ValueError('every judgment needs grade 0/1/2')
        if type(row.get('scene_match')) is not int or row['scene_match'] not in (0,1):
            raise ValueError('every judgment needs scene_match 0/1')
        if not str(row.get('reason','')).strip():
            raise ValueError('every judgment needs a reason')
    grade = {(r['query_id'],r['question_id']):by_id[r['pool_id']]['grade'] for r in pool}
    scene = {(r['query_id'],r['question_id']):by_id[r['pool_id']]['scene_match'] for r in pool}
    text = {(r['query_id'],r['question_id']):r['question'] for r in pool}
    positives = defaultdict(set); ideals = defaultdict(list)
    for (query_id,qid), value in grade.items():
        if value==2: positives[query_id].add(qid)
        ideals[query_id].append(value)
    def dcg(values):
        return sum((2**v-1)/math.log2(i+2) for i,v in enumerate(values))
    rows = []
    for run in runs:
        query_id=run['query_id']; ids=run['selected']; values=[grade[query_id,qid] for qid in ids]
        ideal=dcg(sorted(ideals[query_id],reverse=True)[:k])
        distinct=set(); unique_direct=0
        for qid in ids:
            norm=''.join(ch for ch in text[query_id,qid].casefold() if ch.isalnum())
            if norm not in distinct and grade[query_id,qid]==2: unique_direct+=1
            distinct.add(norm)
        rows.append({'query_id':query_id,'seed':run['seed'],'arm':run['arm'],
            'direct_p_at_k':values.count(2)/k, 'useful_p_at_k':sum(v>=1 for v in values)/k,
            'unique_direct_at_k':unique_direct/k,
            'pooled_ndcg_at_k':dcg(values)/ideal if ideal else 0,
            'fill_rate':len(ids)/k,'exact_text_duplicate_rate':(len(ids)-len(distinct))/k,
            'scene_match_at_k':sum(scene[query_id,qid] for qid in ids)/k,
            'pooled_positive_candidate_coverage':len(set(run['candidates'])&positives[query_id])/len(positives[query_id])
                if positives[query_id] else None,
            'candidate_count':len(run['candidates']),'elapsed_ms':run['elapsed_ms']})
    metrics = [x for x in rows[0] if x not in ('query_id','seed','arm')]
    def aggregate(items):
        return {m:statistics.mean(v for r in items if (v:=r[m]) is not None)
                if any(r[m] is not None for r in items) else None for m in metrics}
    per_query=[]
    for query in protocol['queries']:
        for arm in ARMS:
            per_query.append({'query_id':query['id'],'slice':query['slice'],'arm':arm,
                              **aggregate([r for r in rows if r['query_id']==query['id'] and r['arm']==arm])})
    summary={arm:aggregate([r for r in rows if r['arm']==arm]) for arm in ARMS}
    slices={s:{arm:aggregate([r for r in rows if r['arm']==arm and r['query_id'] in
                            {q['id'] for q in protocol['queries'] if q['slice']==s}])
               for arm in ARMS} for s in sorted({q['slice'] for q in protocol['queries']})}
    comparisons=[]
    for baseline in ('original_tags','flat_semantic'):
        for metric in ('direct_p_at_k','useful_p_at_k','unique_direct_at_k','pooled_ndcg_at_k'):
            # Average repeated RNG runs first; queries, not 36 RNG runs, are units.
            differences=[]
            for query in protocol['queries']:
                values={r['arm']:r[metric] for r in per_query if r['query_id']==query['id']}
                differences.append(values['graph_v1']-values[baseline])
            rng=random.Random(731); samples=sorted(statistics.mean(rng.choices(differences,k=len(differences)))
                                                  for _ in range(10000))
            comparisons.append({'comparison':'graph_v1 - '+baseline, 'metric':metric,
                                'mean_difference':statistics.mean(differences),
                                'paired_query_bootstrap_95_ci':[samples[249],samples[9749]],
                                'queries_win_tie_loss':[sum(d>1e-9 for d in differences),
                                                       sum(abs(d)<=1e-9 for d in differences),
                                                       sum(d< -1e-9 for d in differences)]})
    return {'k':k,'judged_pairs':len(pool),'judgment_counts':dict(Counter(r['grade'] for r in judgments)),
            'summary':summary,'slices':slices,'comparisons':comparisons,
            'per_query':per_query,'per_run':rows,
            'warning':'Pooled nDCG/positive candidate coverage use incomplete pooled gold, NOT corpus Recall. '
                      'Scene rate is evidence-diagnostic only. Latency includes score scan but excludes graph load/model/judging.'}


def summarize_sampled(protocol, runs, pool, judgments):
    """Uniform sample of the returned 100-reference pool; NOT exact P@100."""
    by_id={r['pool_id']:r for r in judgments}; expected={r['pool_id'] for r in pool}
    if len(by_id)!=len(judgments) or set(by_id)!=expected:
        raise ValueError('judgments must cover every sampled pooled pair exactly once')
    for row in judgments:
        if type(row.get('grade')) is not int or row['grade'] not in (0,1,2) or not row.get('reason'):
            raise ValueError('every sampled judgment needs a valid grade and reason')
    grade={(r['query_id'],r['question_id']):by_id[r['pool_id']]['grade'] for r in pool}
    rows=[]; k=protocol['config']['final_limit']
    for run in runs:
        values=[grade[run['query_id'],qid] for qid in run['judgment_ids']]
        n=len(run['selected']); direct=values.count(2)/len(values) if values else 0
        useful=sum(v>=1 for v in values)/len(values) if values else 0
        rows.append({'query_id':run['query_id'],'seed':run['seed'],'arm':run['arm'],
                     'estimated_direct_precision_returned':direct,
                     'estimated_useful_precision_returned':useful,
                     'estimated_direct_count':direct*n,'estimated_useful_count':useful*n,
                     'fill_rate':n/k,'returned_count':n,
                     'exact_text_duplicate_rate_returned':run['selected_text_duplicate_count']/n if n else 0,
                     'sample_count':len(values),'candidate_count':len(run['candidates'])})
    metrics=[x for x in rows[0] if x not in ('query_id','seed','arm')]
    def aggregate(items):
        return {m:statistics.mean(r[m] for r in items) for m in metrics}
    per_query=[{'query_id':q['id'],'slice':q['slice'],'arm':arm,
                **aggregate([r for r in rows if r['query_id']==q['id'] and r['arm']==arm])}
               for q in protocol['queries'] for arm in ARMS]
    return {'k':k,'judged_pairs':len(pool),'per_query':per_query,'per_run':rows,
            'summary':{arm:aggregate([r for r in rows if r['arm']==arm]) for arm in ARMS},
            'warning':'Uniform 5-question sample per returned pool: precision and useful counts are estimates, NOT exact P@100. '
                      'Exact fill and duplicate rates use the complete returned pool. No corpus Recall claim.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    prep=sub.add_parser('prepare'); prep.add_argument('--protocol',type=Path,default=ROOT/'backend/data/eval/graph_retrieval_ab_v1/protocol.json')
    prep.add_argument('--out',type=Path,required=True)
    score=sub.add_parser('score'); score.add_argument('--run',type=Path,required=True)
    score.add_argument('--judgments',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='prepare':
        prepare(args.protocol,args.out)
    else:
        protocol=read_json(args.run/'protocol.json')
        summarize_fn=summarize_sampled if 'judgment_sample_size' in protocol else summarize
        result=summarize_fn(protocol,read_json(args.run/'runs.json'),
                            read_json(args.run/'pool_key.json'),read_json(args.judgments))
        write_json(args.run/'scores.json',result)
        print(json.dumps({k:result[k] for k in ('k','judged_pairs','summary','comparisons') if k in result},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
