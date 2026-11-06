# 逐题复核输出

reviews.jsonl每条至少如下；sample_id使用本批真实F编号，引用行号是本批source.jsonl行号，不是F编号数值。

```json
{"sample_id":"F000001","decision":"pass","checked_fields":["status","context","tests","requires","scenes","scene_concept_links"],"reason":"比较Agent记忆与RAG，保留两个考点；题干无业务归属。","evidence":[{"locator":"source.jsonl:1#question","quote":"Agent memory 和 RAG 有什么区别？"}]}
```

这个例子仅在原题确为该内容时成立，不能复制结论到其他记录。decision取pass、fixed、needs_context、not_question。labeled需覆盖全部六个checked_fields；非题目/待上下文至少检查status、context。fixed另写changes数组，每项含field、before、after及简短reason，实际修改必须与初标/复核文件一致；修正状态时可使用相应状态结论并解释差异。

reviewed_annotations.jsonl继续采用相同标注协议和源ID，不重排。完整复核labeled记录为review/full，其他允许review/status_only。初标记录原封保留，不通过批量改review字段伪造二次阅读。

review_report.md简要列出本批范围、实际复核数量、改动数量及错误类别、三种状态数量、新节点/场景变更和未解决事项。需要上下文的合理隔离记录不等于整个批次未处理，但不能报告成全部已成功挂图。报告可声明AI语义复核已执行，不能宣称脚本证明语义准确率100%。
