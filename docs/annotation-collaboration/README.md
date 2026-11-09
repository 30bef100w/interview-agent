# 36,033 条题库协作标注包

这个压缩包是给协作者使用的完整题库协作数据，不是已经完成的标注结果。

## 下载

协作AI可以直接使用[完整自助下载与标注提示词](AI-PROMPT.md)，自行拉取数据并连续完成分配范围，无需人工逐个触发100题单元。

仓库：https://github.com/30bef100w/interview-agent

[直接下载36,033条题库ZIP](https://github.com/30bef100w/interview-agent/raw/refs/heads/main/docs/annotation-collaboration/interview-agent-annotation-remaining-36033.zip)。克隆仓库也会包含同目录数据包。校验 SHA-256：

```text
249a442be03af796b720588345cd3a612b53ffc09d593c2ef3f565c42ff0e120
```

## 解压位置

从仓库根目录解压，必须保留包内目录结构：

```text
data/annotation_collaboration/2026-11-06-remaining-36033/
```

包内包含 361 个批次（B0001–B0361）、每批 `source.jsonl` 和 `task.json`、知识点索引、场景库以及全量上下文。

## 每5,000题分配一次

按[macro-plan.json](macro-plan.json)分配宏批次，每个协作者只需接一个宏编号；AI自己按顺序完成内部单元并保存进度。

| 宏批次 | 内部单元范围 | 题数 |
| --- | --- | ---: |
| M01 | B0001–B0050 | 5,000 |
| M02 | B0051–B0100 | 5,000 |
| M03 | B0101–B0150 | 5,000 |
| M04 | B0151–B0200 | 5,000 |
| M05 | B0201–B0250 | 5,000 |
| M06 | B0251–B0300 | 5,000 |
| M07 | B0301–B0350 | 5,000 |
| M08 | B0351–B0361 | 1,033 |

```bash
python3 skills/annotate-interview-questions/scripts/macro_progress.py --macro M01 --stage initial
```

脚本核对真实文件和校验结果，返回`next_task`，可中断续做；它不会自动生成标签。每完成100题自动进入下一单元，不需要人工确认。平台的上下文/回合硬限制仍可能造成中断，届时按提示词的恢复指令续做，不宣称一次调用必然标完5,000题。

## 内部单元检查示例

```bash
python3 skills/annotate-interview-questions/scripts/check_collaboration.py inspect \
  --task data/annotation_collaboration/2026-11-06-remaining-36033/tasks/B0001/task.json
```

具体标注格式和验收命令见：

- `skills/annotate-interview-questions/SKILL.md`
- `skills/annotate-interview-questions/references/collaboration.md`
