# 固定批次工作流：码道及其他文件型AI

## 文件入口

从仓库根目录运行。需要Python 3.10+，所有协作脚本只依赖标准库。先检查可用的`python3`/`python`/`py -3`版本，选择符合要求的命令；下文以`python3`为例，不假定原作者电脑的解释器路径。

用户会给完整协作数据包及任务编号，例如`B0001`。完整解压到仓库的`data/annotation_collaboration/2026-11-06-remaining-36033/`；不得只复制单个task.json。已有9,000条按源索引和原字段核对后排除，剩余36,033条分361批，前360批每批100条，最后一批33条。plan中初始`semantic_annotation_completed=false`说明准备流程没有做语义标注，后续进度按实际输出和复核记录统计，不改原计划伪造进度。不可把准备数据量报告成完成量。

每批目录`tasks/Bxxxx/`包含：

- `task.json`：固定范围、稳定F编号、版本、输入哈希和输出约定。
- `source.jsonl`：本批原题、完整原答案、企业、岗位、年份、来源；F编号按全库原行号确定，不重排、不改写源文件。
- `scene-registry.json`、`scene-catalog.md`：本批可维护的场景库快照。
- 知识点目录在共享的`catalog/concept-registry.json`。已含原图2,346个Concept及显式父节点，保留active/draft身份。草稿存在不表示已批准，但语义匹配时可复用其身份，不能再造同义节点。
- 共享`context/full-source.jsonl`保留全库原题、答案和来源，供有指代或来源歧义时定位真实上下文；不因同一文件或相邻行就机械继承场景。

task中的路径均相对于该task.json，不依赖用户名、操作系统或个人skill安装目录。若缺文件或哈希不同，先恢复完整数据包；不能删掉校验或改哈希来适配不明数据。

task.json和plan.json是固定的输入配置，不修改assignee、status或计划ID；分配由用户给出的批次编号或另行维护的分配表记录。完成进度写入输出与复核记录，不改输入配置。

## 先检查范围，再读题

```bash
python3 skills/annotate-interview-questions/scripts/check_collaboration.py inspect --task <本批目录>/task.json
python3 skills/annotate-interview-questions/scripts/check_collaboration.py catalog --task <本批目录>/task.json --parent agent
python3 skills/annotate-interview-questions/scripts/check_collaboration.py catalog --task <本批目录>/task.json --query Redis
```

catalog只是索引搜索，不生成标签。先读相关中文定义与父路径、同层节点，必要时全局查名称/别名，确认没有合适项才提案。没有定义的旧节点结合中文名、明确父级和原题判断；不能靠ID前缀认领域。禁止按关键词循环给全批补标签。

legacy_ids保留已明确合并的旧ID，仅用于查找同义项。输出使用返回项的id，不能把legacy_ids重新建成节点或继续作为新标签身份。

搜索默认返回前30项并标明total_matches和has_more；有后续结果时用--offset继续查看，或缩小领域。可用--node精确读取一个节点，不把截断结果说成“全局已无同义项”。

每次实际读25–50题，可按上下文大小调整。先判断题意再看旧线索；语义存在歧义时读取本行完整答案、source_file及必要原文引用。读取被截断则缩小批量重读，不把未展示内容算读过。工具可批量展示、写入和校验，不负责语义决策。

## 初标输出

每条按[annotation-contract.md](annotation-contract.md)写`annotations.jsonl`，严格沿源顺序，包括非题目和待上下文记录。初标的`review_stage=initial`、`review_scope=null`；不要把一次判断写成二次复核。`corpus_id`、`registry_version`从task读取。原有S编号不移植到新全库快照；使用本批F编号。

本批第n行的`source_locator`固定为`source.jsonl:n`。证据采用可核验的短原文：

- 题干：`source.jsonl:n#question`，必须本题本行，basis为question。
- 答案：`source.jsonl:n#answer`，仅澄清题意，不当已验证标准答案。
- 来源字段：`source.jsonl:n#source_file`，只作明确上下文线索，不从技术目录推业务归属。
- 全库其他行：`full-source.jsonl:n#question`/`#answer`/`#source_file`，n是全库行号，不能把本批行号套过去。

非题干依据必须同时记入context_refs；引文逐字来自实际读取的字段，不改写成自己概括的话。主标签tests与requires、场景、场景知识边分别判断，不做全连接。企业等源属性不重复猜填、不建公司节点。

新增Concept先复查全局目录与本批提案，只在确无等价节点时写`node_proposals.jsonl`，含定义、父级、别名和原文。同义合并/别名用`index_changes.jsonl`记录；不直接修改共享知识目录，不为消除草稿而批量确认。

新增场景先按现有业务定义复用；确为新完整业务任务时，经过AI语义去重，更新**本批**scene-catalog.md和scene-registry.json，写明介绍、适用与排除范围、别名、来源并提升版本，使用稳定scene ID。若先用了new:scene临时提案，另输出显式临时→稳定ID映射，统一本批关系再验收。旧描述只在可靠新题暴露真实遗漏时审慎补充。不改其他批次或共享场景库；整合者以后汇总各批变更，不能让并行AI互相覆盖。场景库版本变化不是批准所有知识草稿。

## 初标检查命令

```bash
python3 skills/annotate-interview-questions/scripts/check_collaboration.py manifest --task <本批目录>/task.json --annotations <本批目录>/annotations.jsonl --out <本批目录>/manifest.initial.json
python3 skills/annotate-interview-questions/scripts/check_collaboration.py check --task <本批目录>/task.json --annotations <本批目录>/annotations.jsonl --manifest <本批目录>/manifest.initial.json --out <本批目录>/validation.initial.json
```

有新节点时，两条命令均加`--proposals <本批目录>/node_proposals.jsonl`。中断检查可加`--allow-partial`，交付整批不得使用。只生成manifest不会补任何标签、完成标记或语义复核。

脚本现在核对任务覆盖、原始源哈希、知识索引哈希、场景版本、关系引用和每条引文是否在指定原字段中，禁止把别题题干作为本题question依据。它仍无法判断引文是否支持结论、标签是否漏标，以及AI是否真的阅读。

## 复核与协作提交

初标完成后，使用[review-interview-annotations](../../review-interview-annotations/SKILL.md)，优先开新AI会话，把task.json和初标输出交给它，不先提供“这些都对”的结论。另写reviewed_annotations.jsonl、reviews.jsonl和manifest.reviewed.json，保留初标原件。

报告分别列：计划条数、初标条数、实际复核条数、修改条数、labeled/needs_context/not_question条数、尚未解决事项。小标题或没有答案不等于缺上下文；能确认到宽主题就标宽主题。没有足够对象的套话才待上下文，页面噪声判非题目。不要为了零待处理而脑补。

协作者只处理自己被分配的批次。数据目录有意被.gitignore排除，源题库默认不进公开仓库；输出打包给分配者，别用git add -f上传全库。共享skill/工具改进可提交协作分支，注明影响范围。推送冲突时禁止force覆盖他人；先核对各自批次，由分配者协调共享索引的变更。
