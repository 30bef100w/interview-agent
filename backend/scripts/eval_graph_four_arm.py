#!/usr/bin/env python3
"""Four-arm offline experiment; real rerank/judge results are external artifacts.

No inferred qrels, keyword judge, network API or semantic proxy. Reranker packets
and separately randomized judge packets contain only raw text and opaque IDs.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import re
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'backend/scripts'))
from app.services.graph_retrieval import GraphIndex, GraphRetriever, GraphRetrievalConfig, ProjectQuery, _Candidate
from eval_graph_retrieval_v1 import original_rank

ARMS = ('original_tags', 'flat_semantic', 'graph_rules', 'graph_llm')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def opaque(*values):
    return hashlib.sha256(('v3-blind-fixed-salt|'+ '|'.join(map(str, values))).encode()).hexdigest()[:20]

def norm(text):
    return ''.join(c for c in str(text).casefold() if c.isalnum())

def evidence(node):
    props = node['properties']; answer = str(props.get('answer') or '')
    # Context only, never source paths, index identifiers or label metadata.
    quotes = [str(r['quote']) for r in props.get('context_refs', [])
              if isinstance(r, dict) and r.get('quote') and '#source_file' not in str(r.get('locator', ''))
              and not re.search(r'\.(?:md|jsonl|txt)(?:$|[:/])', str(r['quote']))]
    return {'question': node['name'], 'answer_excerpt': answer[:800],
            'answer_truncated': len(answer)>800, 'context_quotes': quotes}

def dedup(items, graph):
    """Verified identity + identical substantive text/answer; short text needs context.

    Merge channel membership when duplicates enter through different routes.
    No similarity threshold or LLM interpretation is used for this operation.
    """
    result=[]; seen={}; identities={}
    for original in items:
        item={**original, 'channels':list(original.get('channels', []))}
        qid=item['question_id']; node=graph.nodes[qid]; props=node['properties']
        context=tuple(str(x.get('quote','')) for x in props.get('context_refs',[]) if isinstance(x,dict))
        body=norm(node['name']); ans=norm(props.get('answer') or '')
        key=(body,ans,context) if len(body)<16 else (body,ans)
        canonical=graph.identity(qid)
        old=identities.get(canonical) or seen.get(key)
        if old is not None:
            old['channels']=sorted(set(old.get('channels',[])) | set(item.get('channels',[])))
            old['direct_scene']=old.get('direct_scene',False) or item.get('direct_scene',False)
            continue
        seen[key]=item; identities[canonical]=item; result.append(item)
    return result

def quota_select(ranked, config, has_scene):
    """Reuse the exact retriever quota allocator while preserving supplied order."""
    objects=[]
    for row in ranked:
        obj=_Candidate(row['question_id'], row['question_id'])
        obj.channels=set(row.get('channels', [])); obj.direct_scene=row.get('direct_scene',False)
        objects.append(obj)
    selected, assignments, targets=GraphRetriever._select(objects, config, has_scene)
    ids={x.question_id for x in selected}
    return [r['question_id'] for r in ranked if r['question_id'] in ids], {'assigned':assignments,'targets':targets}

def load(protocol):
    start=time.perf_counter(); directory=ROOT/protocol['graph']
    nodes=[json.loads(l) for l in (directory/'nodes.jsonl').read_text().splitlines() if l.strip()]
    edges=[json.loads(l) for l in (directory/'edges.jsonl').read_text().splitlines() if l.strip()]
    graph=GraphIndex(nodes, edges, include_drafts=False)
    graph_ms=(time.perf_counter()-start)*1000
    start=time.perf_counter()
    flat=GraphIndex(nodes,[e for e in edges if e['relation'] in ('TESTS','HAS_QUESTION','REQUIRES')],include_drafts=False)
    flat_ms=(time.perf_counter()-start)*1000
    return graph,flat,{'graph_cold_load_ms':graph_ms,'flat_extra_index_build_ms':flat_ms}

def retrieve(graph, flat, query, config, seed, arm):
    start=time.perf_counter()
    if arm=='original_tags':
        raw=original_rank(graph,query,config,seed)
        pool=[{'question_id':qid} for qid in raw['candidates']]
    else:
        project=ProjectQuery(project_id=query['id'],project_text=query['text'],
                             scene_ids=tuple(query['scene_ids']),concept_ids=tuple(query['concept_ids']))
        raw=GraphRetriever(flat if arm=='flat_semantic' else graph).project_retrieve(project,config=config,seed=seed)
        pool=raw['candidates']
    retrieval_ms=(time.perf_counter()-start)*1000
    start=time.perf_counter(); pool=dedup(pool,graph)
    dedup_ms=(time.perf_counter()-start)*1000
    start=time.perf_counter()
    if arm=='original_tags':
        shortlist=[r['question_id'] for r in pool[:30]]; selected=shortlist[:config.final_limit]; allocation={}
    else:
        shortlist,_=quota_select(pool,replace(config,final_limit=30),bool(query['scene_ids']))
        subset=set(shortlist); rows=[r for r in pool if r['question_id'] in subset]
        selected,allocation=quota_select(rows,config,bool(query['scene_ids']))
    quota_ms=(time.perf_counter()-start)*1000
    return {'selected':selected,'candidates':[r['question_id'] for r in pool], 'shortlist':shortlist,
            'shortlist_metadata':{r['question_id']:{k:r[k] for k in ('channels','direct_scene') if k in r}
                                   for r in pool if r['question_id'] in shortlist},
            'allocation':allocation,'latency':{'retrieval_ms':retrieval_ms,'dedup_ms':dedup_ms,
             'selection_ms':quota_ms,'total_ms':retrieval_ms+dedup_ms+quota_ms}}

def prepare(protocol_path,out):
    p=read(protocol_path); out=Path(out)
    if (out/'runs.prepared.json').exists(): raise ValueError('frozen experiment already exists')
    graph,flat,cold=load(p); cfg=GraphRetrievalConfig(**p['config'])
    for query in p['queries']:
        for kind,ids in [('Scene',query['scene_ids']),('Concept',query['concept_ids'])]:
            if any(not graph.typed(nid,kind) for nid in ids): raise ValueError(f'invalid active seed {query["id"]}')
    runs=[]; timings=[]; key=[]; packets=[[],[]]
    for i,q in enumerate(p['queries']):
        for seed in p['seeds']:
            for arm in ARMS[:3]:
                result=retrieve(graph,flat,q,cfg,seed,arm)
                run={'query_id':q['id'],'seed':seed,'arm':arm,**result}; runs.append(run)
                for rep in range(p['latency_repeats']):
                    r=retrieve(graph,flat,q,cfg,seed,arm)
                    if r['selected']!=result['selected'] or r['candidates']!=result['candidates']:
                        raise ValueError('nonreproducible retrieval')
                    timings.append({'query_id':q['id'],'seed':seed,'arm':arm,'rep':rep,**r['latency']})
            graph_run=runs[-1]; case=opaque('case',q['id'],seed)
            candidates=[{'candidate_id':opaque('candidate',case,qid),**evidence(graph.nodes[qid])}
                        for qid in graph_run['shortlist']]
            random.Random(int(case[:12],16)).shuffle(candidates)
            packets[i%2].append({'case_id':case,'query':q['text'],'candidates':candidates})
            key.append({'case_id':case,'query_id':q['id'],'seed':seed,
                        'ids':{opaque('candidate',case,qid):qid for qid in graph_run['shortlist']}})
    write(out/'protocol.json',p);write(out/'runs.prepared.json',runs);write(out/'rerank_key.json',key)
    for i,packet in enumerate(packets):
        random.Random(831+i).shuffle(packet);write(out/f'rerank_packet_{i+1}.json',packet)
    write(out/'latency.local.json',{'cold':cold,'warm_runs':timings,'environment':'local Python perf_counter, excludes model/queue/judging'})
    write(out/'manifest.json',{'arms':ARMS,'queries':len(p['queries']),'seeds':p['seeds'],
      'graph_sha256':{n:digest(ROOT/p['graph']/n) for n in ('nodes.jsonl','edges.jsonl')},
      'code_sha256':{n:digest(ROOT/n) for n in ('backend/scripts/eval_graph_four_arm.py',
        'backend/scripts/eval_graph_retrieval_v1.py','backend/app/services/graph_retrieval.py',
        'backend/app/services/knowledge_retrieval.py')},'protocol_sha256':digest(protocol_path),
      'frozen_at_utc':datetime.now(timezone.utc).isoformat()})
    make_judge_pool(p,runs,graph,out)
    print(json.dumps({'queries':len(p['queries']),'prepared_runs':len(runs),'rerank_cases':len(key),
                      'rerank_candidates':sum(len(x['candidates']) for pk in packets for x in pk)},ensure_ascii=False))

def make_judge_pool(p,runs,graph,out):
    """Freeze the whole graph shortlist plus baseline top-K BEFORE LLM ranking.

    This measures the rerankable ceiling without leaking its results to judges.
    It still does not judge the full 500 candidates or establish corpus recall.
    """
    pairs={};packets=[defaultdict(list),defaultdict(list),defaultdict(list)]
    for run in runs:
        ids=run['shortlist'] if run['arm']=='graph_rules' else run['selected']
        for qid in ids:
            pairs[run['query_id'],qid]={'pool_id':opaque('judge',run['query_id'],qid),'query_id':run['query_id'],
                                      'question_id':qid,**evidence(graph.nodes[qid])}
    qids=[q['id'] for q in p['queries']]
    for (query_id,_),row in pairs.items():
        packets[qids.index(query_id)%3][query_id].append({k:v for k,v in row.items() if k not in ('query_id','question_id')})
    for i,packet in enumerate(packets):
        cases=[]
        for query_id,items in packet.items():
            random.Random(opaque(query_id)).shuffle(items)
            cases.append({'case_id':opaque('judge-query',query_id),
                          'query':next(q['text'] for q in p['queries'] if q['id']==query_id),'items':items})
        random.Random(927+i).shuffle(cases);write(out/f'judge_packet_{i+1}.json',cases)
    write(out/'pool_key.json',list(pairs.values()))
    return [sum(map(len,v.values())) for v in packets]


def finalize(out):
    out=Path(out);p=read(out/'protocol.json');graph,_,_=load(p);cfg=GraphRetrievalConfig(**p['config'])
    runs=read(out/'runs.prepared.json');key=read(out/'rerank_key.json')
    outputs=[]
    for path in sorted((out/'rerank_results').glob('*.json')):
        outputs.extend(read(path))
    by_case={r['case_id']:r for r in outputs}
    if len(by_case)!=len(outputs) or set(by_case)!={r['case_id'] for r in key}:
        raise ValueError('rerank cases missing/duplicated/extra')
    for row in key:
        result=by_case[row['case_id']]; ranking=result['ranking']; mapping=row['ids']
        if len(ranking)!=len(set(ranking)) or set(ranking)!=set(mapping): raise ValueError('ranking must be a permutation')
        if not result.get('reason'): raise ValueError('missing rerank explanation')
        base=next(r for r in runs if r['query_id']==row['query_id'] and r['seed']==row['seed'] and r['arm']=='graph_rules')
        query=next(q for q in p['queries'] if q['id']==row['query_id'])
        ranked=[{'question_id':mapping[cid],**base['shortlist_metadata'][mapping[cid]]} for cid in ranking]
        started=time.perf_counter();selected,allocation=quota_select(ranked,cfg,bool(query['scene_ids']))
        selection_ms=(time.perf_counter()-started)*1000
        runs.append({**base,'arm':'graph_llm','selected':selected,'allocation':allocation,
                     'llm_ranking':[mapping[cid] for cid in ranking],'post_llm_selection_ms':selection_ms,
                     'latency':{**base['latency'],'note':'model batch latency recorded separately; total_ms here is shared local preprocessing'}})
    # D can only select from the already-blind-judged C shortlist.
    pool=read(out/'pool_key.json');pairs={(r['query_id'],r['question_id']) for r in pool}
    if any((r['query_id'],qid) not in pairs for r in runs for qid in r['selected']):
        raise ValueError('selected question outside frozen judgment pool')
    write(out/'runs.json',runs)
    print(json.dumps({'runs':len(runs),'judged_pairs_required':len(pool)}))

def pct(values,p):
    a=sorted(values);i=(len(a)-1)*p;return a[math.floor(i)]+(a[math.ceil(i)]-a[math.floor(i)])*(i%1)

def diagnostics(runs, grades, k):
    rows=[]
    for base in (r for r in runs if r['arm']=='graph_rules'):
        q=base['query_id'];llm=next(r for r in runs if r['arm']=='graph_llm' and r['query_id']==q and r['seed']==base['seed'])
        direct=lambda ids:sum(grades[q,qid]==2 for qid in ids)
        known_direct={qid for (query_id,qid),grade in grades.items() if query_id==q and grade==2}
        blocked=sorted((known_direct & set(base['candidates']))-set(base['shortlist']))
        rows.append({'query_id':q,'seed':base['seed'],
          'shortlist_direct_ceiling_at_k':min(k,direct(base['shortlist']))/k,
          'rules_direct_at_k':direct(base['selected'])/k,
          'llm_direct_at_k':direct(llm['selected'])/k,
          'llm_unconstrained_top_k_direct':direct(llm.get('llm_ranking',llm['selected'])[:k])/k,
          'same_selected_set':set(base['selected'])==set(llm['selected']),
          'same_candidate_list':base['candidates']==llm['candidates'],
          'same_shortlist':base['shortlist']==llm['shortlist'],
          'known_direct_candidates_outside_shortlist':blocked,
          'warning':'outside-shortlist positives only include pooled judged questions, not all candidates'})
    return rows


def score(out):
    out=Path(out);p=read(out/'protocol.json');runs=read(out/'runs.json');pool=read(out/'pool_key.json')
    judgments=[]
    for f in sorted((out/'judge_results').glob('*.json')): judgments.extend(read(f))
    judged={r['pool_id']:r for r in judgments}
    if len(judged)!=len(judgments) or set(judged)!={r['pool_id'] for r in pool}: raise ValueError('incomplete/duplicate/extra judgments')
    for r in judgments:
        if type(r.get('grade')) is not int or r['grade'] not in (0,1,2) or not r.get('reason'):
            raise ValueError('invalid judgment')
    grades={(r['query_id'],r['question_id']):judged[r['pool_id']]['grade'] for r in pool}
    ideals=defaultdict(list)
    for (q,_),g in grades.items():ideals[q].append(g)
    def dcg(v):return sum((2**g-1)/math.log2(i+2) for i,g in enumerate(v))
    rows=[];k=p['config']['final_limit']
    for run in runs:
        q=run['query_id'];values=[grades[q,qid] for qid in run['selected']]
        ideal=dcg(sorted(ideals[q],reverse=True)[:k])
        rows.append({'query_id':q,'seed':run['seed'],'arm':run['arm'],'direct_p_at_k':values.count(2)/k,
             'useful_p_at_k':sum(g>=1 for g in values)/k,'pooled_ndcg_at_k':dcg(values)/ideal if ideal else 0,
             'fill_rate':len(values)/k,'candidate_count':len(run['candidates']),
             'shortlist_count':len(run['shortlist'])})
    metrics=['direct_p_at_k','useful_p_at_k','pooled_ndcg_at_k','fill_rate','candidate_count','shortlist_count']
    def avg(items):return {m:statistics.mean(r[m] for r in items) for m in metrics}
    per_query=[{'query_id':q['id'],'slice':q['slice'],'arm':a,**avg([r for r in rows if r['query_id']==q['id'] and r['arm']==a])}
               for q in p['queries'] for a in ARMS]
    comparisons=[]
    for a,b in [('graph_llm','graph_rules'),('graph_rules','flat_semantic'),('graph_llm','flat_semantic'),('graph_rules','original_tags')]:
        for m in metrics[:3]:
            diffs=[next(r[m] for r in per_query if r['query_id']==q['id'] and r['arm']==a)-
                   next(r[m] for r in per_query if r['query_id']==q['id'] and r['arm']==b) for q in p['queries']]
            rng=random.Random(731);boot=sorted(statistics.mean(rng.choices(diffs,k=len(diffs))) for _ in range(10000))
            comparisons.append({'comparison':a+' - '+b,'metric':m,'mean_difference':statistics.mean(diffs),
                     'query_bootstrap_95_ci':[boot[249],boot[9749]],
                     'win_tie_loss':[sum(d>1e-9 for d in diffs),sum(abs(d)<=1e-9 for d in diffs),sum(d< -1e-9 for d in diffs)]})
    local=read(out/'latency.local.json');latency={}
    for a in ARMS[:3]:
        times=[r['total_ms'] for r in local['warm_runs'] if r['arm']==a]
        latency[a]={'p50_ms':pct(times,.5),'p95_ms':pct(times,.95),'measurements':len(times)}
    manifest=read(out/'manifest.json')
    for name,expected in manifest['graph_sha256'].items():
        if digest(ROOT/p['graph']/name)!=expected:raise ValueError('graph changed during experiment')
    summary={'k':k,'queries':len(p['queries']),'runs':len(runs),'judged_pairs':len(pool),
      'grade_distribution':dict(Counter(r['grade'] for r in judgments)),
      'summary':{a:avg([r for r in rows if r['arm']==a]) for a in ARMS},
      'slices':{s:{a:avg([r for r in rows if r['arm']==a and next(q['slice'] for q in p['queries'] if q['id']==r['query_id'])==s])
                  for a in ARMS} for s in sorted({q['slice'] for q in p['queries']})},
      'comparisons':comparisons,'per_query':per_query,'per_run':rows,'local_latency':latency,
      'rerank_diagnostics':diagnostics(runs,grades,k),
      'cold_load':local['cold'],'limitations':p['limitations']}
    write(out/'judgments.json',judgments);write(out/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ('per_query','per_run','comparisons')},ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','finalize','score']);parser.add_argument('--protocol');parser.add_argument('--out',required=True)
    args=parser.parse_args()
    if args.mode=='prepare':prepare(args.protocol,args.out)
    elif args.mode=='finalize':finalize(args.out)
    else:score(args.out)
