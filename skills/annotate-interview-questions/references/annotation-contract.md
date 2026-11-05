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
| review_scope | 字符串或null | 新复核记录必填：`full`、`concept_only`、`scene_only`、`status_only`；initial可省略或为null。旧review记录未提供时表示复核范围未声明，不默认完整复核 |
| normalized_question | 字符串或null | 仅在有依据地补全/整理题干时填写，不替换原题；补全文字需有context_refs支持 |
| context_refs | 证据数组 | 实际读取的原文章节等，未读不写 |
| tests、requires | 关系数组 | 每项含concept_id、basis、evidence、reason |
| scenes | 关系数组 | 每项含scene_id、basis、evidence、reason |
| scene_concept_links | 关系数组 | 每项含scene_id、concept_id、basis、evidence、reason；只写独立核实的对应关系 |
| reason | 非空短中文 | 关键结论，尤其是无考点、待上下文、非题目、改动和提案 |

每个`evidence`和`context_refs`元素均为`{"locator":"可定位来源","quote":"短原文"}`。`basis`取`question`、`source_context`或`answer_clarification`。

`answer_clarification`用于原答案帮助澄清题意，不代表答案已验证。场景关系只允许`question`或`source_context`：回答里举例客服、电商，不足以证明这题属于这些项目。若原答案直接定义本题系统的身份或实际用途，例如明确是帮助候选人回答而不是担任面试官，可作为`source_context`澄清角色，写入`context_refs`并引用准确原文；不能把这种依赖上下文的结论标成仅凭题干得出。旧场景标签应作为待复核线索，不直接写成已确认关系。

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
  "review_scope": "full",
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

2026-11-04场景规则补充：Scene提案还需`match_when`、`exclude_when`非空字符串数组；先查已有场景定义和批内提案，符合就复用，没有场景依据就留空，不新建通用兜底场景。详见[场景定义优先的标注方法](scene-labeling.md)。场景含义应解释业务对象和任务，不能只有名字。

2026-11-05场景粒度修正：KG按业务场景/完整应用任务复用入口，不以简历出现教程名为条件。黑马点评映射`scene:business:local_life`，苍穹外卖映射`scene:business:delivery`；原具名入口为停用历史ID。此映射是业务归类，不是项目身份的同义合并。项目名称、出处和实现差异仍保留在源记录/上下文；不得凭通用Redis、日志等知识点补业务场景。

索引变更记录字段：`operation`（add_alias / merge / add_parent）、`target_id`、`alias`或`source_id`或`parent_id`、`reason`、`evidence`。合并需确认语义等价，不因为题量少或共享一个上级就合并。新别名必须先查全局冲突；层级增量需检查环。下面的校验器只检查标注和新增提案，不应用index_changes，也不替代合并语义复核。

## 批次清单与恢复

manifest至少含schema_version、corpus_id、registry_version、source_file及其sha256、planned_sample_ids、completed_sample_ids、status_counts、review_stage_counts、proposal_count。未完成任务也应保存实际完成列表，并报告剩余范围。

`completed_sample_ids`表示文件中已有的输出记录，不等于已完成重标。新复核批次同时记录`reviewed_sample_ids`（全部review记录，含单项复核）、`full_reviewed_sample_ids`（仅review_scope=full）及`review_scope_counts`，校验时与实际文件核对。initial或仅复制底稿的记录不能计入完整复核；旧数据缺少复核范围不伪造补齐。即使标签无需改变，也必须实际读过并完成相应判断才能标记review。

使用场景定义库的新批次另记录`scene_registry_version`与`scene_registry_sha256`，固定本批场景语义。旧批次缺失这些字段不伪造补齐。

先将提案在批内去重并统一引用，再运行：

```bash
python3 <skill目录>/scripts/validate_annotations.py \
  --annotations <批次目录>/annotations.jsonl \
  --registry <知识点注册表.json> \
  --scene-registry <场景解释库.json> \
  --manifest <批次目录>/manifest.json
```

有新增节点时加`--proposals <批次目录>/node_proposals.jsonl`。未完成批次恢复时加`--allow-partial`；最终交付不加此参数。校验器会报告提案引用数，不负责批准提案。

针对本skill已知错标的回归检查，加`--regression-cases <skill目录>/references/semantic-regression-cases.json`。案例按corpus_id及源文件哈希绑定固定题库，只检查本次有review标记的案例，不按关键词自动生成任何标签。`forbidden_tests`、`forbidden_scenes`、`forbidden_scene_concept_links`拦截已确认的错关系；`required_tests`、`required_scenes`检查已确认必须保留的关系，防止删错后漏标。未列明的关系仍由AI核查。全量重标最终验收再加`--require-reviewed`：计划范围内所有记录必须是review；`labeled`必须是`review_scope=full`，`needs_context`/`not_question`可以是`status_only`，因为它们的交付结论是状态判断而非知识点语义挂载。结构检查的completed数始终只表示记录数。

深问场景解释库基线为`backend/data/scene_registry_v01.json`。兼容核查旧快照时仍可用`--scene-nodes <图的nodes.jsonl>`替代，二者不能同时提供；旧入口只检查存在性，不能证明具备解释或匹配边界。

该命令检查字段、重复ID、关系引用、场景关系证据类型、父级环和计划覆盖；不能判断语义正确性、引文真假、原文是否真的被读取，也不验证source_file的哈希。AI需分别核对这些内容，不能把退出码0说成“题目全部标对”。

校验结果中的`ancestor_overlap_count`和`ancestor_overlap_examples`是父子考点共现审计提示：共现不自动判错，但必须回看题干，确认父、子确实是两个独立考察对象；否则在下一版标注中删除泛化父节点，避免MG题目边和检索结果膨胀。
