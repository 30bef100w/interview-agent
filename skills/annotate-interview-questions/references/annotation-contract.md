# 标注输出协议 v1

本协议是新标注批次的输出约定，不是现有旧格式的别名。历史格式只有existing/proposed或concept_ids时，需要AI补充关系判断；不能靠格式转换伪造场景归属或前置依赖。

## 文件与版本

每批创建新目录，交付：

- `annotations.jsonl`：用户范围内每条源记录一行，按源顺序输出，包括非题目和待上下文记录。
- `node_proposals.jsonl`：仅在有新增知识点/场景时输出。提案经语义核查、合并后再形成新版注册表，不默认加入主图。
- `index_changes.jsonl`：有别名、合并、补父关系时输出明确增量；无变更可不生成。
- `manifest.json`：快照、索引版本、计划ID、实际完成范围与状态统计。

`corpus_id`标识固定题库快照，`sample_id`仅在该快照内唯一。不要假设不同批次的S0001是同一题。`registry_version`应引用固定索引版本，版本不明确时记录文件路径与哈希，不自行宣称最新正式版。

## 每条标注

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| schema_version | 字符串 | 固定 `1.0.0` |
| corpus_id、sample_id、registry_version、source_locator | 非空字符串 | 快照、源记录ID、索引版本、当前源记录定位 |
| record_status | 枚举 | `labeled`、`needs_context`、`not_question` |
| review_stage | 枚举 | `initial`、`review`；只有实际重新读题判断才写review |
| normalized_question | 字符串或null | 仅在有依据地补全/整理题干时填写，不替换原题；补全文字需有context_refs支持 |
| context_refs | 证据数组 | 实际读取的原文章节等，未读不写 |
| tests、requires | 关系数组 | 每项含concept_id、basis、evidence、reason |
| scenes | 关系数组 | 每项含scene_id、basis、evidence、reason |
| scene_concept_links | 关系数组 | 每项含scene_id、concept_id、basis、evidence、reason；只写独立核实的对应关系 |
| reason | 非空短中文 | 关键结论，尤其是无考点、待上下文、非题目、改动和提案 |

每个`evidence`和`context_refs`元素均为`{"locator":"可定位来源","quote":"短原文"}`。`basis`取`question`、`source_context`或`answer_clarification`。

`answer_clarification`用于原答案帮助澄清题意，不代表答案已验证。场景关系只允许`question`或`source_context`：回答里举例客服、电商，不足以证明这题属于这些项目。旧场景标签应作为待复核线索，不直接写成已确认关系。

`needs_context`、`not_question`记录的四类关系数组均留空；已经确定的一部分线索可在reason和历史标签中保留，待补足上下文后作为整体重新判断。`labeled`允许没有技术考点，例如行为题。它表示标注已完成，不表示新增节点已正式发布。

企业、年份、岗位、原题和原答案通过source_locator回到原记录，保持源属性不改；无需在每条标注中重复长答案。若用户授权纠正源属性，另外输出明确修正记录。

## 可校验的真实样例

以下来自当前题库S0001；无新增节点，无项目关联。源答案中提到客服、翻译等只是指标举例，不转成场景标签。

```json
{
  "schema_version": "1.0.0",
  "corpus_id": "2026-10-28-batch4-10000",
  "sample_id": "S0001",
  "registry_version": "2026-11-03.v02",
  "source_locator": "data/knowledge_index_pilot/2026-10-28-batch4-10000/sample.jsonl:1",
  "record_status": "labeled",
  "review_stage": "review",
  "normalized_question": null,
  "context_refs": [],
  "tests": [
    {
      "concept_id": "llm.prompt",
      "basis": "question",
      "evidence": {"locator": "sample.jsonl:1#question", "quote": "怎么对 prompt 做 A/B test？指标怎么定？"},
      "reason": "考察提示词方案的实验比较。"
    },
    {
      "concept_id": "ai.eval",
      "basis": "question",
      "evidence": {"locator": "sample.jsonl:1#question", "quote": "指标怎么定？"},
      "reason": "同时考察模型应用实验指标的设计。"
    }
  ],
  "requires": [],
  "scenes": [],
  "scene_concept_links": [],
  "reason": "复用已有考点；没有特定项目归属，不从答案举例补场景。"
}
```

## 新节点与索引变更

新节点提案一行一个，字段：`id`（临时ID，以`new:concept:`或`new:scene:`开头）、`node_type`（Concept/Scene）、`name`（中文）、`definition`（语义范围）、`aliases`（数组）、`parents`（现有或本批提案ID数组）、`evidence`。

Concept必须给出合理父节点；Scene作为入口，parents为空。多个父节点均应有语义依据，不按英文ID前缀猜父级。引用新节点的标签可以先用临时ID，但正式建图前必须完成提案核查、映射和新注册表发布。未解决提案不能静默成为正式节点。

索引变更记录字段：`operation`（add_alias / merge / add_parent）、`target_id`、`alias`或`source_id`或`parent_id`、`reason`、`evidence`。合并需确认语义等价，不因为题量少或共享一个上级就合并。新别名必须先查全局冲突；层级增量需检查环。下面的校验器只检查标注和新增提案，不应用index_changes，也不替代合并语义复核。

## 批次清单与恢复

manifest至少含schema_version、corpus_id、registry_version、source_file及其sha256、planned_sample_ids、completed_sample_ids、status_counts、review_stage_counts、proposal_count。未完成任务也应保存实际完成列表，并报告剩余范围。

先将提案在批内去重并统一引用，再运行：

```bash
python3 <skill目录>/scripts/validate_annotations.py \
  --annotations <批次目录>/annotations.jsonl \
  --registry <知识点注册表.json> \
  --scene-nodes <图的nodes.jsonl> \
  --manifest <批次目录>/manifest.json
```

有新增节点时加`--proposals <批次目录>/node_proposals.jsonl`。未完成批次恢复时加`--allow-partial`；最终交付不加此参数。校验器会报告提案引用数，不负责批准提案。

该命令检查字段、重复ID、关系引用、场景关系证据类型、父级环和计划覆盖；不能判断语义正确性、引文真假、原文是否真的被读取，也不验证source_file的哈希。AI需分别核对这些内容，不能把退出码0说成“题目全部标对”。
