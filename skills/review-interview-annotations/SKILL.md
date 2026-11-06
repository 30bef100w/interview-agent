---
name: review-interview-annotations
description: 对已完成的深问题库标注逐题语义复核并核验源引用、索引复用、场景归属与计划覆盖，修正后输出独立复核记录。用于标注后的验收，不把脚本通过当作语义正确。
---

# 深问题库标后复核

适用于华为云码道及能读写文件、运行Python的AI。与仓库相邻的`annotate-interview-questions`一起分发；不依赖Codex接口。入口是用户分配批次的task.json和annotations.jsonl，优先使用新的AI会话，不预设初标是对的。

## 先读取

1. [固定批次工作流](../annotate-interview-questions/references/collaboration.md)定位源题、版本、知识索引与场景库；运行其中inspect命令。若没有task.json，按[标注协议](../annotate-interview-questions/references/annotation-contract.md)固定用户给出的范围，不能换用本机旧目录。
2. [语义判例](../annotate-interview-questions/references/semantic-examples.md)、[场景规则](../annotate-interview-questions/references/scene-labeling.md)以及任务实际使用的目录。历史固定ID回归只适用于绑定的旧快照，不能套到新F编号。
3. [复核日志格式](references/review-output.md)。

## 逐题复核

先看原题和必要的原答案/准确上下文，独立判断领域、对象、机制、业务任务，再对照初标。每次读适量题目，未展示或截断的部分先补读。脚本只能展示和核验，不能按关键词推断标签或给全批自动盖pass。

- **状态与上下文：** 真问题、行为题、材料标题、页面噪声分别判断；能确定到宽主题就正常保留，不因缺答案而搁置。省略题有真实依据才补题干；仍缺必要对象时needs_context，不编题。
- **考点与依赖：** 题干明确并列问的对象是否漏掉；是否跨语言/同名误挂；可选解法和原答案举例是否被当作考点；requires是否确为所问机制的前置依赖。需要新增节点的技术题不得用空考点假装完成。
- **索引复用：** 查中文定义、父路径、同层及全局别名和本批提案；同义项复用同一ID，多父不复制实体。父子同时挂载要确认分别考察，不能机械补祖先。题量少不是删节点理由，draft不能机械升active。
- **场景与边：** 按完整业务对象/任务，不按订单、日志、技术栈拆项目；通用Redis/秒杀不证明电商或外卖。题干未写项目名时仍检查准确业务上下文；答案泛举场景不算归属。场景→知识点每项需独立证据，禁止笛卡尔积。
- **库与引文：** 新场景必须有本批MD介绍和JSON定义/边界、版本和显式ID映射；旧场景不为迁就单题随意扩范围。所有引用须逐字支持结论，不能只看字符串恰好存在。企业、年份、岗位留在源记录，不猜填。

发现一种错法时，定向复查本批同类决策，不能只修一个示例ID。保留正确的并列标签，不以删空所有细标签的方式消除风险。

## 输出与验收

保留annotations.jsonl，另写reviewed_annotations.jsonl。实际重新阅读并全项判断的labeled记录写review_stage=review、review_scope=full；非题目/仍待上下文可写status_only。每条写reviews.jsonl，给出具体结论、检查项、短原文、必要的修改前后差异。未完成时只输出已实际复核范围，不倒填全量完成。

然后运行：

```bash
python3 skills/annotate-interview-questions/scripts/check_collaboration.py manifest --task <本批目录>/task.json --annotations <本批目录>/reviewed_annotations.jsonl --out <本批目录>/manifest.reviewed.json
python3 skills/annotate-interview-questions/scripts/check_collaboration.py check --task <本批目录>/task.json --annotations <本批目录>/reviewed_annotations.jsonl --manifest <本批目录>/manifest.reviewed.json --review-log <本批目录>/reviews.jsonl --reviewed --out <本批目录>/validation.reviewed.json
```

有新节点时两条均加`--proposals <本批目录>/node_proposals.jsonl`。只有中断检查可用--allow-partial；最终--reviewed验收必须覆盖整个分配范围。保留初标，不把新结果覆盖旧文件。

交付时区分“范围/格式/引用检查通过”和“AI已逐题语义复核”。报告实际读题数、改动数、状态统计、索引/场景提案及待解决问题；没有完成全批、已知错误未修、场景只有名字没有定义时，不宣布验收完成。这个skill不发布生产图，不替他人推送，也不修改共享索引。
