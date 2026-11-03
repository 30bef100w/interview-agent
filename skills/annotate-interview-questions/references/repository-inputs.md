# 深问仓库输入定位

从用户指定仓库开始，使用`rg --files`和定向读取，不扫描用户无关目录。以下路径均相对interview-agent仓库根目录；它们是2026-11-03的已知基线，不是硬编码永久最新版。

| 用途 | 基线文件 |
| --- | --- |
| 三图总体思路 | `docs/MG-KG-TG三图设计与标注流程-2026-11-03.md` |
| 建图和标注规则 | `docs/MG-KG离线建图与题目标注规范-v1-2026-11-03.md` |
| 知识点ID、父级与路径 | `data/index_review/2026-11-03/registry.json` |
| 中文显示、全部索引类型 | `backend/data/knowledge_index_display_zh_v01.json` |
| 中文目录 | `docs/知识点完整索引-中文阅读版-2026-11-03.md` |
| 已整理的题目标签 | `data/index_review/2026-11-03/annotations_reviewed.jsonl` |
| 场景节点与已有关系 | `data/index_review/2026-11-03/nodes.jsonl`、`edges.jsonl` |
| 原题、原答案、来源 | `data/knowledge_index_pilot/2026-10-28-batch4-10000/sample.jsonl` |
| 历史索引合并决策 | `backend/data/semantic_concept_normalization_v01.json`、`semantic_index_review_v02.json` |
| 待处理记录 | `data/index_review/2026-11-03/quarantine.jsonl` |

registry.json是列表，含id、name、kind、parents、primary_path等。知识点标注使用列表中的裸ID，如`rag.retrieval`，而图节点使用`concept:rag.retrieval`；在输入边界明确转换，不把二者当成不同概念。场景沿用nodes.jsonl里的完整scene ID。

英文ID只作身份，不用它猜父级或直接给用户作中文解释。中文显示文件只是显示层，不能用显示名称替换稳定ID。registry中的review_status不表示逐题语义复核完成；实际完成情况见review_report.json。

全量题库ZIP或解压文件可能在用户另行指定位置。上述sample只是一份采样快照；S编号连续、文件名带10000，不表示10000题已标注，也不表示已完成全库。精确用source_index、source_line、source_repo、source_file等回到原文；找不到原文就说明缺失，不根据文件名编造章节。

旧`annotate_question_sample.py`包含规则匹配，不可用来替代本skill要求的AI逐题判断。旧`build_semantic_question_graph.py`和`review_semantic_index.py`有历史推断行为；本skill仅产出新协议，不能宣称这些脚本已修复或可直接兼容。

新输出建议放`data/semantic_annotations/<用户范围或批次名>/`。这些数据目录可能被gitignore；创建后分别报告源码与生成数据的位置，不自动改gitignore或强行提交题库。
