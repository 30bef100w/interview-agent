# 知识库（本地自备，不随仓库分发）

八股召回、企业原题、参考答案都读这个目录。仓库只放格式说明，不放题。

缺文件时服务仍能启动，但规划阶段题库为空，八股会偏空或改由模型现编（体验明显变差）。

## 需要的文件

| 文件 | 用途 |
|---|---|
| `questions_dedup.jsonl` | 去重后的面试题（一行一条 JSON） |
| `knowledge.jsonl` | 参考答案 / 讲解原文块（可选，评分讲解用） |

## `questions_dedup.jsonl` 字段

```json
{"question": "HTTP 和 HTTPS 有什么区别？", "answer": "HTTPS 在 HTTP 上叠加 TLS。", "category": "bagu", "company": "tencent", "roles": ["java_backend"], "business_scene": [], "tech_scene": ["auth"], "era": "2026", "source_repo": "local", "source_file": "example.md"}
```

常用字段：

- `question` / `answer`：题干与参考答
- `category`：`bagu` 或 `project`
- `company`：`companies.json` 里的 id，没有就 `null`
- `roles`：`job_roles.json` 里的 role_id 列表
- `business_scene` / `tech_scene`：场景 id 列表
- `era`：如 `"2026"`，检索会按时效加权

## `knowledge.jsonl` 字段（可选）

```json
{"id": "local_0", "source_file": "example.md", "category": "bagu", "type": "knowledge", "roles": ["java_backend"], "title": "HTTPS", "content": "……讲解原文……"}
```

准备好后把文件放进本目录即可，不用改代码。
