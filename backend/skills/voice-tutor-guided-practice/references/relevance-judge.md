## 用户问题
{{query}}

## 知识库检索结果
{{rag_context}}

## 任务

判断检索结果和用户问题的相关性：

- `full`：内容能够直接回答问题。
- `partial`：属于同一主题、设备、工艺或安全场景，但信息不够完整。
- `none`：内容明显不属于同一主题。

资料不完整但相关时优先判为 `partial`，不要仅因不完整就判为 `none`。

只输出 JSON：

```json
{"relevance": "full|partial|none"}
```
