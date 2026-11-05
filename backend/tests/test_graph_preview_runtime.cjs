/* Run the standalone viewer against an inert DOM; no browser/network required. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
const payload=html.match(/<script id="graph-data" type="application\/json">([\s\S]*?)<\/script>/)[1];
const script=html.match(/<script>\n([\s\S]*?)<\/script>/)[1];
const data=JSON.parse(payload);
class Element {
 constructor(value=''){this.value=value;this.innerHTML='';this.textContent='';this.children=[];this.dataset={};this.open=false}
 append(v){this.children.push(v)}
 setAttribute(){}
 querySelectorAll(selector){
  const attribute={'[data-show-node]':['data-show-node','showNode'],'[data-page-key]':['data-page-key','pageKey']}[selector];
  if(!attribute)return [];
  const result=[];
  for(const match of this.innerHTML.matchAll(/<button\b([^>]+)>/g)){
   const a=match[1].match(new RegExp(attribute[0]+'="([^"]*)"'));
   if(!a)continue;
   const el=new Element();el.dataset[attribute[1]]=a[1].replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&');
   const page=match[1].match(/data-page="([^"]*)"/);if(page)el.dataset.page=page[1];
   result.push(el);
  }
  this.lastButtons=result;return result;
 }
}
const elements=Object.fromEntries(['mode','anchor','budget','graph','caption','detail','graph-data'].map(k=>[k,new Element()]));
elements.mode.value='kg';elements.budget.value='6';elements['graph-data'].textContent=payload;
const context=vm.createContext({document:{getElementById:k=>elements[k],createElement:()=>new Element()}});
vm.runInContext(script,context);
assert(elements.graph.innerHTML.includes('智能客服系统'));
assert(elements.detail.innerHTML.includes('业务介绍'));
assert(elements.detail.innerHTML.includes('主要参与者'));
assert(elements.detail.innerHTML.includes('典型业务流程（示例）'));
assert.equal(data.nodes.filter(n=>n.node_type==='Scene'&&n.properties.detail_profile).length,39);
assert.equal(data.nodes.filter(n=>n.node_type==='Concept'&&n.properties.detail_profile).length,64);
elements.mode.value='mg';elements.mode.onchange();
assert(elements.graph.innerHTML.includes('Redis'));
elements.budget.value='16';elements.budget.onchange();
vm.runInContext('showDetail("concept:ai.eval")',context);
assert(elements.detail.innerHTML.includes('如何定义任务成功与失败'));
assert(elements.detail.innerHTML.includes('上级知识点'));
assert(elements.detail.innerHTML.includes('第 1 /'));
const next=elements.detail.lastButtons.find(b=>b.dataset.pageKey==='questions'&&b.dataset.page==='1');
assert(next,'question pagination button must be wired');next.onclick();
assert(elements.detail.innerHTML.includes('第 2 /'));
const links=elements.detail.querySelectorAll('[data-show-node]');
assert(links.length>0);
// Re-render restores actual click handlers on related-node links.
vm.runInContext('showDetail("concept:ai.eval")',context);
const related=elements.detail.querySelectorAll('[data-show-node]').find(b=>b.dataset.showNode.startsWith('question:'));
vm.runInContext(`showDetail(${JSON.stringify(related.dataset.showNode)})`,context);
assert(elements.detail.innerHTML.includes('原始题目'));
assert(elements.detail.innerHTML.includes('原始来源'));
const answered=data.nodes.find(n=>n.node_type==='Question'&&n.properties.answer);
vm.runInContext(`showDetail(${JSON.stringify(answered.id)})`,context);
assert(elements.detail.innerHTML.includes('查看原始参考答案'));
vm.runInContext(`nodes.set('unsafe', {id:'unsafe',name:'<img src=x onerror=alert(1)>',node_type:'Question',state:'active',properties:{answer:'</div><script>alert(1)</script>',source_file:'<b>source</b>'}});showDetail('unsafe')`,context);
assert(!elements.detail.innerHTML.includes('<script>'));
assert(!elements.detail.innerHTML.includes('<img'));
assert(elements.detail.innerHTML.includes('&lt;script&gt;'));
assert(!payload.includes('</script>'));
elements.mode.value='kg';elements.mode.onchange();elements.anchor.value='scene:business:local_life';elements.anchor.onchange();
assert(elements.caption.textContent.includes('没有该业务场景的直接题目'));
assert(elements.detail.innerHTML.includes('商户数据缓存与热点访问'));
console.log('PASS: KG/MG, all scene profiles, concept explanations, detail pagination, original answers, escaping, empty-scene state');
