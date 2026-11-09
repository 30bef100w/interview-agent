# 36,033 条题库协作标注包

这个压缩包是给协作者使用的完整题库协作数据，不是已经完成的标注结果。

## 下载

下载同目录的 `interview-agent-annotation-remaining-36033.zip`，并校验 SHA-256：

```text
249a442be03af796b720588345cd3a612b53ffc09d593c2ef3f565c42ff0e120
```

## 解压位置

从仓库根目录解压，必须保留包内目录结构：

```text
data/annotation_collaboration/2026-11-06-remaining-36033/
```

包内包含 361 个批次（B0001–B0361）、每批 `source.jsonl` 和 `task.json`、知识点索引、场景库以及全量上下文。

## 开始某一批

```bash
python3 skills/annotate-interview-questions/scripts/check_collaboration.py inspect \
  --task data/annotation_collaboration/2026-11-06-remaining-36033/tasks/B0001/task.json
```

具体标注格式和验收命令见：

- `skills/annotate-interview-questions/SKILL.md`
- `skills/annotate-interview-questions/references/collaboration.md`
