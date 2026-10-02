# 组合式 RAG 实施记录

目标：保留 Google Drive、Basic Auth、FastAPI 和 Docker；仅实现 LlamaIndex 检索 + LangChain 生成，增加中文流式网页。

架构决策：LlamaIndex SentenceSplitter 按页分块、OpenAIEmbedding 向量化、ChromaVectorStore 持久化。每文件版本在 SQLite 清单中原子切换，检索只过滤有效版本；失败暂存和旧版本保留但不可检索。新目录/集合默认不触碰旧库。LangChain 只改写追问和生成。SQLite 保存浏览器身份及成功对话轮次。

约束：不调用真实模型、不导入生产资料、不改凭证、不删备份分支。现有未跟踪网页先备份到 /tmp；无关未跟踪文件不提交。

- [x] 导入：页码/稳定 ID/去重/更新失败/文件隔离测试；替换 chunker、vector_store、ingest_drive，删除旧 embedding 包装。
- [x] 对话：适配 NodeWithScore、历史改写、上下文限额、引用检查；LangChain 替换旧 llm 包装。
- [x] API：SQLite 所有权、旧请求、SSE token/[DONE]、超时/错误/取消、耗时及 token 用量。
- [x] 网页：同源认证、安全渲染、来源卡片、流式未验证状态、新会话及移动端。
- [x] 验证：完整 pytest、浏览器检查、依赖兼容检查、脚本导入；中文 README 和依赖锁定；引用检查后删除旧实现并提交。

重点复核：并发导入、切换失败、取消时历史写入、过期 Cookie、恶意链接及 HTML、旧库回退。正式上线前仍需真实 Google/OpenAI 验证与备份恢复演练。

验证记录：Python 3.12.11，31 项 pytest 通过；pip check 通过；实际 LangChain/LlamaIndex 客户端以 httpx.MockTransport 验证普通与流式调用。Playwright 桌面/手机测试通过。独立审查发现保存线程跨过请求超时仍写历史的边界问题，已新增两个失败回归并修复提交前截止时间/取消检查；引用失败日志保留已完成阶段耗时。Docker 构建尝试因 Docker Hub 基础镜像元数据拉取超时失败，尚未验证容器运行。无真实模型/Drive调用。

最终复测补充：获取会话锁阶段超时不遗留忙碌状态；Uvicorn/uvloop 使用相对剩余时长避免不同时钟基准；新增对应回归测试。
