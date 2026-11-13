# MG/KG 离线图快照与演示

更新：2026-11-05。当前版本：`2026-11-05-mgkg-9000-v3`。

**已实现：题目标注、确定性建图与离线浏览。2026-11-06已新增纯图检索模块、语义重排及主链路适配，代码默认启用；TG第一版已接入主链，支持真实触发建边和有限正向召回。** 当前仍使用 JSON 开发存储，真实用户数据和生产化迁移持续积累。草稿审批暂缓，不因本次公开而更改状态。

## 查看图

- [演示 HTML](index.html)：下载原始文件后用浏览器打开，完全离线，无需账号、后端或外部脚本。GitHub文件页显示源码，不会直接执行HTML。文件约15MB，包含完整浏览数据。
- [完整图快照 ZIP](mgkg-9000-v3.zip)：包含MG/KG视图、统一节点/边、来源归档、报告、清单和同一份HTML。
- [机器可读快照摘要](snapshot_summary.json)与[文件校验和](SHA256SUMS)。
- [当前检索架构与实现](../MG-KG图检索架构与实现-v1-2026-11-06.md)、[历史检索方案](../MG-KG检索方案-v1-2026-11-05.md)、[迭代计划](../MG-KG迭代计划-2026-11-03.md)、[场景解释库](../KG场景库解释与标注规则-2026-11-04.md)、[标注 skill](../../skills/annotate-interview-questions/SKILL.md)。

演示可切换KG场景和MG知识入口，调整每栏数量；点击节点查看业务/概念介绍、上下级、实际题目、原答案及关系证据。图形展示有限子图，详情中的题目和关系可分页。原答案只作来源参考，不是已验证标准答案。

## 本次规模

| 内容 | 数量/状态 |
| --- | --- |
| 已处理源记录 | 9000 |
| 入图题目 | 8704 |
| 非题目 / 待上下文 | 272 / 24，归档而不入图 |
| 知识点 | 2346，263 active、2083 draft |
| 场景入口 | 39，其中34个在本批有关系 |
| 真实边 | 16023 |
| 新增详细介绍 | 39个场景、64个常用知识点 |
| 结构检查 | 无悬空引用、非法关系端点、层级环和重复边三元组 |

MG与KG共享知识点和题目身份，不复制两套Redis节点。KG按业务/完整应用任务作为入口，不按订单、日志等模块拆分；黑马点评归本地生活服务，苍穹外卖归外卖服务。当前本地生活及外卖入口没有本批直接题，浏览器明确显示为空，不补造示例。

## 压缩包内容

解压后根目录为`mgkg-9000-v3/`：

| 文件 | 用途 |
| --- | --- |
| `nodes.jsonl`、`edges.jsonl` | 统一实体图及全部明确关系，边保留证据 |
| `mg_nodes.jsonl`、`mg_edges.jsonl` | MG视图：知识目录、题目、考点与依赖 |
| `kg_nodes.jsonl`、`kg_edges.jsonl` | KG视图：场景及其直接关联知识点/题目 |
| `source_records.jsonl` | 本批9000条源记录与处理状态，原题、原答案、来源属性保留 |
| `excluded_records.jsonl` | 非题目及待上下文记录 |
| `entity_redirects.json` | 显式别名/合并/场景归类映射 |
| `graph_issues.jsonl` | 103条导航节点被用作语义目标的关系提示，状态保留为draft |
| `mapping_report.json` | 数量、检查结果、来源标注校验及边界 |
| `graph_manifest.json` | 输入/输出哈希、原构建路径、版本与状态 |
| `detail_enrichment_audit.json` | 本轮补充解释的范围及未更改图关系的检查 |
| `preview.html` | 与仓库单独演示HTML相同 |

本次仅按用户要求公开这一离线试验快照，不包含完整生产题库、所有历史标注批次或完整原始构建输入。manifest中的绝对路径为构建时来源定位，不要求克隆仓库后存在相同本机目录。生成输出和源归档可直接读取；从头重建需要另行提供匹配哈希的原标注批次、源采样和索引输入。

## 使用与验证

在仓库根目录解压、重新生成浏览器：

```bash
python3 -m zipfile -e docs/graph-demo/mgkg-9000-v3.zip /tmp/deepask-graph
python3 backend/scripts/render_annotation_graph_v2.py \
  --graph /tmp/deepask-graph/mgkg-9000-v3 \
  --out /tmp/deepask-graph/preview.html
```

在有完整构建输入的环境中，使用明确路径创建新图，避免覆盖历史快照：

```bash
python3 backend/scripts/build_annotation_graph_v2.py \
  --batch <标注批次目录> --index-dir <索引快照目录> --out <新的输出目录>
```

相关检查：

```bash
python3 -m unittest discover -s backend/tests -p test_build_annotation_graph_v2.py
python3 -m unittest discover -s skills/annotate-interview-questions/scripts -p test_validate_annotations.py
node backend/tests/test_graph_preview_runtime.cjs docs/graph-demo/index.html
```

当前13项建图测试、15项标注校验测试及演示页面逻辑检查通过。页面检查覆盖切换、详情分页、答案、文本转义和空场景状态，不是浏览器视觉验收或检索效果验收。

## 下一步

已实现项目KG/MG双路有界召回、动态名额回流和结构排序，八股采用MG叶子题池随机抽样。四组受控盲评已完成，结果见[报告](../MG-KG四组检索与LLM重排评测-2026-11-06.md)；主链路接入见[记录](../MG-KG主链路接入记录-2026-11-06.md)。下一步验证真实简历自动种子和部署模型延迟。现阶段不宣称图检索效果已优于旧方案，草稿及已记录语义问题继续保留。
