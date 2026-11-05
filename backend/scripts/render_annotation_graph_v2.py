#!/usr/bin/env python3
"""Create a standalone, offline viewer of a materialized MG/KG snapshot."""
import argparse
import json
from pathlib import Path


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>深问 MG / KG · 9000 条离线图</title>
<style>
:root{font-family:system-ui,-apple-system,sans-serif;color:#172b41;background:#f5f7fa;font-size:15px}
*{box-sizing:border-box}body{margin:0;padding:28px}main{max-width:1440px;margin:auto}
h1{font-size:25px;margin:0 0 10px}p{line-height:1.7;color:#4b5c70}header{margin-bottom:20px}
.controls{display:flex;gap:18px;flex-wrap:wrap;align-items:end}label{display:grid;gap:7px}select{font:inherit;padding:9px 12px;border:1px solid #c2ccd8;border-radius:7px;max-width:100%}
.legend{display:flex;flex-wrap:wrap;gap:18px;margin:17px 0;color:#4b5c70}.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:7px}
.canvas{background:white;border:1px solid #dce3ec;border-radius:12px;overflow:auto}svg{display:block;width:100%;min-width:980px}svg text{font-family:inherit}
.node{cursor:pointer}.node:focus rect{stroke:#172b41;stroke-width:3}.node:hover rect{filter:brightness(.97)}
.detail{background:white;padding:24px;border:1px solid #dce3ec;border-radius:12px;margin-top:16px;overflow-wrap:anywhere;line-height:1.8}
.detail h3{font-size:21px;margin:0 0 8px}.detail h4{font-size:16px;margin:22px 0 8px}.detail p{margin:8px 0}.detail ul,.detail ol{padding-left:24px;margin:8px 0}.detail li{margin:7px 0}.muted{color:#63758a;font-size:13px}.prose{white-space:pre-wrap}.badge{display:inline-block;padding:1px 9px;background:#edf1f6;border-radius:5px;margin-right:8px;font-size:13px}.node-link,.pager button{font:inherit;color:#22647f;background:#f1f7fa;border:1px solid #d3e3ec;border-radius:5px;padding:3px 9px;cursor:pointer;text-align:left;max-width:100%}.node-link:hover,.pager button:hover{background:#e5f0f5}.pager{display:flex;gap:12px;align-items:center;margin:10px 0}.evidence{border-left:3px solid #d4e1eb;padding:6px 14px;margin:8px 0;background:#f8fafc}.detail details{margin:14px 0}.detail summary{cursor:pointer;color:#385b7b}.detail details[open]>summary{margin-bottom:10px}.answer{max-height:480px;overflow:auto;background:#f7f9fc;padding:15px}
#caption{margin:12px 0;color:#506579}h2{font-size:18px;margin:0 0 10px}@media(max-width:600px){body{padding:14px}.controls{display:grid}select{width:100%}}
</style>
<main>
<header><h1>深问 MG / KG · 真实离线子图</h1>
<p>__RECORD_COUNT__ 条已处理记录 · __QUESTION_COUNT__ 道题目 · __CONCEPT_COUNT__ 个知识点 · __SCENE_COUNT__ 个场景入口。子图仅截取已有边，省略部分节点以便阅读。虚线表示草稿关系，不代表已批准。</p></header>
<div class="controls"><label>图视图<select id="mode"><option value="kg">KG · 项目 / 场景索引</option><option value="mg">MG · 知识目录与题库</option></select></label>
<label>入口<select id="anchor"></select></label><label>每栏最多显示<select id="budget"><option>6</option><option>10</option><option>16</option></select></label></div>
<div class="legend"><span><i class="dot" style="background:#7957bb"></i>场景</span><span><i class="dot" style="background:#227592"></i>知识点</span><span><i class="dot" style="background:#257b56"></i>题目</span><span>→ 表示原始关系方向</span><span>点击节点查看原文 / 关系证据</span></div>
<div class="canvas"><svg id="graph" role="img" aria-label="实际题库的有限子图"></svg></div>
<div id="caption" aria-live="polite"></div><section class="detail"><h2>节点详情</h2><div id="detail">选择一个节点查看来源与实际连边。</div></section>
</main>
<script id="graph-data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('graph-data').textContent), nodes=new Map(data.nodes.map(n=>[n.id,n]));
const mode=document.getElementById('mode'), anchor=document.getElementById('anchor'), budget=document.getElementById('budget'), svg=document.getElementById('graph');
const relNames={HAS_SUBTOPIC:'细分',COVERS_TOPIC:'涉及主题',TESTS:'考察',REQUIRES:'依赖',HAS_QUESTION:'场景相关题',INVOLVES:'涉及'};
const outgoing=new Map(),incoming=new Map();for(const e of data.edges){if(!outgoing.has(e.src_id))outgoing.set(e.src_id,[]);outgoing.get(e.src_id).push(e);if(!incoming.has(e.dst_id))incoming.set(e.dst_id,[]);incoming.get(e.dst_id).push(e)}
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const relevant=(id,r,reverse=false)=>(reverse?incoming:outgoing).get(id)?.filter(e=>e.relation===r)||[];
function anchors(){anchor.textContent='';const list=data.nodes.filter(n=>mode.value==='kg'?n.node_type==='Scene':data.mgAnchors.includes(n.id));list.sort((a,b)=>a.name.localeCompare(b.name,'zh-CN'));for(const n of list){const o=document.createElement('option');o.value=n.id;const count=relevant(n.id,mode.value==='kg'?'HAS_QUESTION':'TESTS',mode.value==='mg').length;o.textContent=n.name+(mode.value==='kg'?` · ${count} 道项目原题`:'');anchor.append(o)}anchor.value=mode.value==='kg'?'scene:candidate:proposed.scene.customer_service':'concept:redis';draw()}
let selectedId=null, detailPages={};
const readable=v=>typeof v==='string'?v:JSON.stringify(v,null,2);
const paragraph=v=>v?`<p class="prose">${esc(readable(v))}</p>`:'';
function bulletSection(title,values,ordered=false){if(!values?.length)return '';const tag=ordered?'ol':'ul';return `<h4>${esc(title)}</h4><${tag}>${values.map(v=>`<li>${esc(readable(v))}</li>`).join('')}</${tag}>`}
function nodeLink(id){const n=nodes.get(id);return n?`<button type="button" class="node-link" data-show-node="${esc(id)}">${esc(n.name)}</button>${n.state==='draft'?'<span class="muted"> 草稿</span>':''}`:esc(id)}
function paginated(key,items,row){if(!items.length)return '<p class="muted">本批暂无直接关联。</p>';const size=12,last=Math.ceil(items.length/size)-1,page=Math.max(0,Math.min(detailPages[key]||0,last));detailPages[key]=page;return items.slice(page*size,(page+1)*size).map(row).join('')+(last?`<div class="pager"><button type="button" data-page-key="${esc(key)}" data-page="${page-1}" ${page===0?'disabled':''}>上一页</button><span>第 ${page+1} / ${last+1} 页 · 共 ${items.length} 条</span><button type="button" data-page-key="${esc(key)}" data-page="${page+1}" ${page===last?'disabled':''}>下一页</button></div>`:'')}
function relatedNodes(title,ids,key){const unique=[...new Set(ids)];if(!unique.length)return '';return `<h4>${esc(title)} · ${unique.length}</h4>`+paginated(key,unique,id=>`<p>${nodeLink(id)}</p>`)}
function showDetail(id){const n=nodes.get(id);if(!n)return;if(selectedId!==id){selectedId=id;detailPages={}}const p=n.properties||{},profile=p.detail_profile||{},es=[...(outgoing.get(id)||[]),...(incoming.get(id)||[])];
let html=`<h3>${esc(n.name)}</h3><div><span class="badge">${{Scene:'场景',Concept:'知识点',Question:'题目'}[n.node_type]||esc(n.node_type)}</span><span class="badge">${n.state==='draft'?'草稿':'已登记'}</span><span class="muted">${esc(id)}</span></div>`;
if(profile.introduction||p.definition)html+=`<h4>${n.node_type==='Scene'?'业务介绍':'知识点说明'}</h4>`+paragraph(profile.introduction||p.definition);
if(n.node_type==='Scene'){
html+=bulletSection('主要参与者',profile.participants)+bulletSection('典型业务流程（示例）',profile.typical_workflow,true)+bulletSection('可识别的简历线索',profile.resume_clues)+bulletSection('可能考察的方向（示例）',profile.interview_focus)+bulletSection('匹配条件',p.match_when)+bulletSection('不适用情况',p.exclude_when);
}else if(n.node_type==='Concept'){
html+=bulletSection('理解这个知识点可关注',profile.key_questions);
if(!profile.introduction&&!p.definition)html+='<p class="muted">该节点尚未补写独立概念介绍，可先查看下方索引位置和真实关联题目。</p>';
html+=relatedNodes('上级知识点',relevant(id,'HAS_SUBTOPIC',true).map(e=>e.src_id),'parents');
html+=relatedNodes('下级知识点',relevant(id,'HAS_SUBTOPIC').map(e=>e.dst_id),'children');
html+=relatedNodes('相关主题',[...relevant(id,'COVERS_TOPIC').map(e=>e.dst_id),...relevant(id,'COVERS_TOPIC',true).map(e=>e.src_id)],'topics');
html+=relatedNodes('已标注涉及此知识点的场景',relevant(id,'INVOLVES',true).map(e=>e.src_id),'scenes');
}else if(n.node_type==='Question'){
html+='<h4>原始题目</h4>'+paragraph(n.name);
if(p.normalized_question)html+='<h4>结合上下文补全的题干</h4>'+paragraph(p.normalized_question);
html+=relatedNodes('实际考察',relevant(id,'TESTS').map(e=>e.dst_id),'tests')+relatedNodes('明确依赖',relevant(id,'REQUIRES').map(e=>e.dst_id),'requires')+relatedNodes('场景归属',relevant(id,'HAS_QUESTION',true).map(e=>e.src_id),'scenes');
if(p.company||p.companies?.length)html+='<h4>企业（源记录）</h4>'+paragraph(p.company||p.companies);
if(p.roles?.length)html+='<h4>岗位（源记录）</h4>'+paragraph(p.roles);
if(p.context_refs?.length)html+='<details><summary>题干补全引用的上下文</summary>'+paragraph(p.context_refs)+'</details>';
html+='<h4>原始来源</h4>'+paragraph([p.source_repo,p.source_file,p.source_line?'行 '+p.source_line:null].filter(Boolean).join(' · '))+paragraph(p.source_locator);
html+=p.answer?'<details><summary>查看原始参考答案（未经标准答案验证）</summary><div class="prose answer">'+esc(readable(p.answer))+'</div></details>':'<p class="muted">源记录未提供参考答案。</p>';
}
if(profile.scope_boundary)html+='<h4>含义与适用边界</h4>'+paragraph(profile.scope_boundary);
if(profile.profile_basis)html+='<p class="muted">'+esc(profile.profile_basis)+'</p>';
if(profile.introduction&&p.definition&&p.definition!==profile.introduction)html+='<details><summary>查看索引库原定义</summary>'+paragraph(p.definition)+'</details>';
if(p.aliases?.length)html+=bulletSection('别名 / 原有名称',p.aliases);
if(n.node_type!=='Question'){
const qids=n.node_type==='Scene'?relevant(id,'HAS_QUESTION').map(e=>e.dst_id):relevant(id,'TESTS',true).map(e=>e.src_id);
html+=`<h4>${n.node_type==='Scene'?'本场景直接关联的真实题目':'直接考察此知识点的真实题目'} · ${new Set(qids).size}</h4>`;
html+=paginated('questions',[...new Set(qids)],qid=>`<p>${nodeLink(qid)} <span class="muted">${esc(nodes.get(qid)?.properties?.sample_id)}</span></p>`);
if(n.node_type==='Scene')html+=relatedNodes('已有标注支持的知识点',relevant(id,'INVOLVES').map(e=>e.dst_id),'concepts');
else html+=relatedNodes('以此知识点为前置依赖的题目',relevant(id,'REQUIRES',true).map(e=>e.src_id),'prerequisiteQuestions');
}
html+=`<details><summary>全部实际连边与依据 · ${es.length} 条（可分页）</summary><p class="muted">以下只展示已落图关系；上方典型流程与考察示例不会自动生成图边。</p>`+paginated('edges',es,e=>`<div class="evidence">${nodeLink(e.src_id)} <strong>—${esc(relNames[e.relation])}→</strong> ${nodeLink(e.dst_id)}${e.state==='draft'?'<span class="muted"> [草稿关系]</span>':''}${(e.evidence_refs||[]).map(ref=>paragraph(ref.evidence?.quote?'原文：'+ref.evidence.quote:null)+paragraph(ref.reason?'标注理由：'+ref.reason:null)+`<div class="muted">${esc([ref.sample_id,ref.evidence?.locator,ref.basis,ref.registry_id].filter(Boolean).map(readable).join(' · '))}</div>`).join('')}${e.evidence_count>3?`<p class="muted">本边共 ${e.evidence_count} 条证据，此处展示前 3 条；完整记录在 edges.jsonl。</p>`:''}</div>` )+'</details>';
const el=document.getElementById('detail');el.innerHTML=html;for(const button of el.querySelectorAll('[data-show-node]'))button.onclick=()=>showDetail(button.dataset.showNode);for(const button of el.querySelectorAll('[data-page-key]'))button.onclick=()=>{detailPages[button.dataset.pageKey]=Number(button.dataset.page);const opened=Array.from(el.querySelectorAll('details')).map(d=>d.open);showDetail(id);el.querySelectorAll('details').forEach((d,i)=>{d.open=opened[i]||false})};
}
function draw(){const root=anchor.value;if(!root)return;const cap=Number(budget.value);let middle=[],right=[];
if(mode.value==='kg'){middle=relevant(root,'INVOLVES').map(e=>e.dst_id).slice(0,cap);right=relevant(root,'HAS_QUESTION').map(e=>e.dst_id).slice(0,cap);for(const q of right){for(const e of relevant(q,'TESTS'))if(middle.length<cap&&!middle.includes(e.dst_id))middle.push(e.dst_id)}}
else{middle=relevant(root,'HAS_SUBTOPIC').map(e=>e.dst_id).slice(0,cap);const qs=[...relevant(root,'TESTS',true).map(e=>e.src_id),...middle.flatMap(id=>relevant(id,'TESTS',true).map(e=>e.src_id))];right=[...new Set(qs)].slice(0,cap)}
middle=[...new Set(middle)];right=[...new Set(right)];const height=Math.max(330,Math.max(middle.length,right.length)*92+94),pos=new Map([[root,{x:24,y:height/2-35}]]);middle.forEach((id,i)=>pos.set(id,{x:420,y:68+i*92}));right.forEach((id,i)=>pos.set(id,{x:850,y:68+i*92}));
svg.setAttribute('viewBox',`0 0 1220 ${height}`);let content='<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8796a6"/></marker></defs>';
content+='<text x="24" y="30" fill="#53657b">'+(mode.value==='kg'?'项目 / 场景':'知识入口')+'</text><text x="420" y="30" fill="#53657b">知识点（同一共享实体）</text><text x="850" y="30" fill="#53657b">原题</text>';
const allowed=new Set(mode.value==='kg'?['HAS_QUESTION','INVOLVES','TESTS','REQUIRES']:['HAS_SUBTOPIC','TESTS','REQUIRES','COVERS_TOPIC']);const es=data.edges.filter(e=>allowed.has(e.relation)&&pos.has(e.src_id)&&pos.has(e.dst_id));
for(const e of es){const s=pos.get(e.src_id),t=pos.get(e.dst_id),forward=s.x<t.x;const x1=s.x+(forward?340:0),x2=t.x+(forward?0:340),y1=s.y+34,y2=t.y+34;const offset=forward?58:-58;const path=`M${x1},${y1} C${x1+offset},${y1} ${x2-offset},${y2} ${x2},${y2}`;content+=`<path d="${path}" fill="none" stroke="#9baaba" stroke-width="1.3" ${e.state==='draft'?'stroke-dasharray="5 4"':''} marker-end="url(#arrow)"><title>${esc(relNames[e.relation])}</title></path>`;if(Math.abs(t.x-s.x)<600){content+=`<text x="${(x1+x2)/2}" y="${(y1+y2)/2-7}" text-anchor="middle" fill="#506579" font-size="12">${esc(relNames[e.relation])}</text>`}}
for(const [id,p] of pos){const n=nodes.get(id),palette=n.node_type==='Scene'?['#f0eaf9','#68479c']:n.node_type==='Question'?['#eaf5ef','#24704f']:['#e7f2f7','#22647f'];const chars=Array.from(n.name.replace(/\s+/g,' '));const lines=[];for(let i=0;i<Math.min(chars.length,38);i+=19)lines.push(chars.slice(i,i+19).join(''));if(chars.length>38)lines[lines.length-1]+='…';content+=`<g class="node" data-id="${esc(id)}" role="button" tabindex="0" aria-label="${esc(n.name)}"><rect x="${p.x}" y="${p.y}" width="340" height="68" rx="9" fill="${palette[0]}" stroke="#d6e0e8"/><text x="${p.x+12}" y="${p.y+23}" fill="${palette[1]}" font-size="14">${lines.map((s,i)=>`<tspan x="${p.x+12}" dy="${i?20:0}">${esc(s)}</tspan>`).join('')}</text><text x="${p.x+325}" y="${p.y+61}" text-anchor="end" fill="#586b7f" font-size="11">${n.state==='draft'?'草稿':n.node_type==='Question'?esc(n.properties?.sample_id):''}</text></g>`}
svg.innerHTML=content;for(const el of svg.querySelectorAll('[data-id]')){el.onclick=()=>showDetail(el.dataset.id);el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();showDetail(el.dataset.id)}}}document.getElementById('caption').textContent=`当前显示 ${pos.size} 个节点 / ${es.length} 条真实边。`+(mode.value==='kg'&&!right.length?' 此入口已登记，但本批标签没有该项目的直接题目，不补造示例。':'');showDetail(root)}
mode.onchange=anchors;anchor.onchange=draw;budget.onchange=draw;anchors();
</script></html>'''


def render(graph_dir, out):
    def rows(name):
        return [json.loads(line) for line in (graph_dir / name).open() if line.strip()]
    nodes = rows("nodes.jsonl")
    edges = rows("edges.jsonl")
    compact_nodes = []
    for node in nodes:
        p = node["properties"]
        compact_nodes.append({**{k: node[k] for k in ("id", "name", "state", "node_type")},
                              "properties": {k: p[k] for k in ("sample_id", "company", "companies", "roles", "definition", "detail_profile", "aliases", "match_when", "exclude_when", "source_file", "source_repo", "source_line", "source_locator", "normalized_question", "answer", "context_refs") if p.get(k)}})
    compact_edges = []
    for edge in edges:
        refs = edge["properties"]["evidence_refs"]
        compact_edges.append({**{k: edge[k] for k in ("src_id", "relation", "dst_id", "state")},
                              "evidence_count": len(refs), "evidence_refs": refs[:3]})
    data = {"nodes": compact_nodes, "edges": compact_edges,
            "mgAnchors": ["concept:" + cid for cid in ("redis", "cache", "mysql", "agent", "rag", "performance", "distributed", "llm", "java", "os")]}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    report = json.loads((graph_dir / "mapping_report.json").read_text())
    content = TEMPLATE.replace("__DATA__", payload)
    for key, value in {
        "__RECORD_COUNT__": report["annotation_count"],
        "__QUESTION_COUNT__": report["nodes_by_type"]["Question"],
        "__CONCEPT_COUNT__": report["nodes_by_type"]["Concept"],
        "__SCENE_COUNT__": report["nodes_by_type"]["Scene"],
    }.items():
        content = content.replace(key, str(value))
    content = content.replace("道项目原题", "道场景题").replace("没有该项目的直接题目", "没有该业务场景的直接题目")
    out.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    render(args.graph, args.out)
