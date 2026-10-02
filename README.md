# 知库 · Google Drive 文档问答

基于 FastAPI 的中文网页聊天与 RAG API。只有一条组合式流程：

```text
Google Drive → 按页解析 → LlamaIndex Document / SentenceSplitter
             → LlamaIndex OpenAIEmbedding → ChromaVectorStore → Chroma

问题 + 服务端历史 → LangChain 必要的独立问题改写
                 → LlamaIndex aretrieve（一次问题向量化、一次检索）
                 → NodeWithScore → LangChain Document → 编号上下文
                 → LangChain ChatPromptTemplate / ChatOpenAI → 答案 + 来源
```

LlamaIndex 负责节点、分块、Embedding、向量索引和异步检索；不使用 QueryEngine 生成答案。LangChain 负责消息、追问改写、提示词和普通/流式生成；没有第二套检索器。FastAPI 负责接口、认证、会话与静态网页。没有 Agent、LangGraph 或可切换的多套 RAG 后端。

## 安装与配置

使用 Python **3.12** 或兼容的新版本（锁定依赖要求最低 3.12）。本次在 Python 3.12.11 验证。运行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c requirements.lock
cp .env.example .env
```

`requirements.txt` 锁定直接依赖；`requirements.lock` 锁定实际测试环境的传递依赖。核心版本：langchain-core 0.3.86、langchain-openai 0.3.35、llama-index-core 0.12.52、llama-index-embeddings-openai 0.3.1、llama-index-vector-stores-chroma 0.4.2、chromadb 1.5.9。只安装需要的框架组件；LlamaIndex 的 workflows 是传递依赖，应用没有调用工作流或 Agent。

`.env` 中配置 `OPENAI_API_KEY`、`GOOGLE_DRIVE_FOLDER_ID`（多个文件夹用逗号分隔）。保留现有 `.env` 时，手动加入新配置，不要覆盖凭证。

| 配置 | 默认值 / 含义 |
|---|---|
| OPENAI_CHAT_MODEL | gpt-4o-mini |
| OPENAI_EMBEDDING_MODEL | text-embedding-3-small |
| OPENAI_EMBEDDING_DIMENSIONS | 1536；导入和检索必须一致 |
| VECTOR_STORE_DIR | data/chroma_v2；新目录避免打开生产旧库 |
| CHROMA_COLLECTION | google_drive_llama_v1；首次迁移使用新集合 |
| CHUNK_SIZE / CHUNK_OVERLAP | 768 / 100，按 tokenizer token 计数 |
| EMBEDDING_BATCH_SIZE | 64 |
| RETRIEVAL_TOP_K | 5 |
| CONTEXT_MAX_CHARS | 16000，检索上下文字符预算 |
| HISTORY_MAX_TURNS / HISTORY_MAX_CHARS | 6 / 8000；只取有限完整历史轮次 |
| REQUEST_TIMEOUT | 90 秒，覆盖问题改写、检索、生成 |
| MAX_OUTPUT_TOKENS | 2000 |
| SESSION_DB | data/sessions.sqlite3 |
| SESSION_TTL_SECONDS | 604800，浏览器 Cookie 身份有效期 |
| COOKIE_SECURE | false，本地 HTTP；HTTPS 部署应设 true |
| API_BASIC_AUTH_USERNAME / PASSWORD | 均为空时不启用 Basic Auth；必须同时配置 |

旧 `CHUNK_MIN_TOKENS`、`CHUNK_MAX_TOKENS`、`CHUNK_OVERLAP_TOKENS` 已删除，改用上表新名称。首次分块可能下载 tiktoken 的 cl100k_base 编码表；不会调用模型或产生模型费用。离线环境先缓存编码表；不使用会导致跨环境分块漂移的静默 fallback。

## Google Drive 认证和导入

1. 在 Google Cloud 项目启用 Drive API，配置 OAuth 同意屏幕和 **Desktop app** OAuth 客户端。
2. 将客户端文件保存为 `credentials.json`，或者设置 `GOOGLE_OAUTH_CREDENTIALS_FILE`。
3. 设置 `GOOGLE_DRIVE_FOLDER_ID`；登录账号必须能读取对应文件夹。
4. 首次导入在本机浏览器完成只读授权，令牌保存在 `token.json`，可通过 `GOOGLE_OAUTH_TOKEN_FILE` 改路径。后续复用并刷新。

`app/services/drive_auth.py` 存在，脚本直接导入 `get_drive_service`。支持 PDF、DOCX、TXT，分页读取文件列表，支持共享云端硬盘。PDF 按物理页保留页码；DOCX/TXT 页码为 null。扫描 PDF 不含可提取文本时不生成节点；目前不做 OCR、Google Docs 原生格式导出、子文件夹递归或云端删除同步。

**首次迁移需要重新分块与向量化，可能产生 OpenAI API 费用。** 脚本必须显式传入费用确认参数；本次开发没有运行真实导入。

```bash
python scripts/ingest_drive.py --help
# 审核 .env 的新目录、新集合及费用后才执行：
python scripts/ingest_drive.py --confirm-cost
```

每页创建 LlamaIndex Document，使用 SentenceSplitter。节点保存 `chunk_id`、`file_id`、`file_name`、`source_link`、`page_number`、`chunk_index`、`content_hash`、`chunk_version` 和完整文件版本 `version`。Chroma 内部使用 0 表示未知页码，API 转回 null。

稳定 ID 包含文件身份、完整文件内容与来源元数据、分块版本/参数和位置。相同输入重复导入不新增节点、不重复向量化。文件内容、来源元数据或分块参数变更会生成新版本，整份文件需要重新向量化。

### 文件更新与失败恢复

再次执行同一导入命令即可。先写入新版本全部节点并核对 ID，再通过 `versions.sqlite3` 的事务发布该文件新版本。检索通过 LlamaIndex metadata filter 只查询已发布版本。失败时旧版本保持有效；部分暂存节点不参与检索，下次可补齐。旧版本停用但保留磁盘数据，本次没有自动物理清理功能，不会误删其他文件。

本地文件锁保证多个导入进程串行写入，读取不等锁；已开始的请求使用其读取时的版本快照。发布后的新请求只看到新版本。备份/恢复应把整个 Chroma 目录（包括 `versions.sqlite3`）一起处理，不能单独丢弃版本清单。文件解析失败或没有文本时保持旧版本，不把空结果当作删除指令。无需在合并到 master 后重复删除旧代码：必要删除已包含在开发分支提交中。

### 新集合切换与旧集合回退

首次默认使用 `data/chroma_v2` / `google_drive_llama_v1`，保留原 `data/chroma` / `google_drive_docs`。也可在单独测试副本里指定其他新集合名。不要将新导入指向旧集合。

旧集合可通过同一组合流程查询：停止服务，先备份旧目录（建议复制到回退目录，避免新 Chroma 版本打开旧数据时升级格式），将 `VECTOR_STORE_DIR` 指向副本、`CHROMA_COLLECTION=google_drive_docs`，设置旧库实际使用的 Embedding 模型/维度后重启。旧 schema 适配由 LlamaIndex ChromaVectorStore 提供；旧集合没有可靠的模型元数据，必须人工确认配置。导入程序拒绝写入旧 schema 集合。

回退旧代码时也应使用原备份目录与原版本依赖；本次不删除原代码备份分支。切回新集合只需恢复新目录/集合配置后重启。不要将旧集合当作新 schema 声明或自行修改集合元数据。

## 启动和网页

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 [聊天页面](http://127.0.0.1:8000/)，可流式聊天、追问、查看引用来源、新建对话和停止生成。Enter 发送，Shift+Enter 换行。页面支持手机布局，使用纯 HTML/CSS/JavaScript，文本通过 `textContent` 渲染，不执行模型 HTML；原文链接仅接受 http/https。

配置 Basic Auth 后，浏览器访问首页会触发原生登录框，后续调用同源 API。API Key、Google 凭证和令牌不传到前端。未启用 Basic Auth 时，只适合本机/可信网络：访客可查询知识库，但每个浏览器获得服务端生成、登记、到期校验的 HttpOnly/SameSite Cookie，不能凭其他人的 conversation_id 读取历史。启用 Basic Auth 后会话绑定认证用户名。同一用户名代表同一用户。未配置模型密钥时首页与健康检查仍可访问，聊天返回明确 503。

会话和成功轮次持久化在 SQLite；服务重启后保留。当前网页不自动恢复上次打开的对话，可通过 API 获取指定会话近期历史。Cookie 到期后匿名用户无法访问原身份的历史。历史仅用于问题理解，生成业务结论必须依赖本次检索资料。同一会话并发请求返回 409，避免交错历史；不同会话可并行。

## API 与流协议

旧请求仍可仅发送 `question`：

```bash
curl -c /tmp/rag-cookie.txt -b /tmp/rag-cookie.txt \
  -H 'Content-Type: application/json' \
  -d '{"question":"申请需要哪些材料？"}' http://127.0.0.1:8000/chat
```

启用认证时增加 `-u '用户名:密码'`，不要将真实密码写进共享脚本或版本库。续聊时将响应中的 `conversation_id` 放入请求；匿名调用需保留 Cookie。

- `POST /conversations`：创建并返回 conversation_id。
- `GET /conversations/{id}`：当前用户可见的有限近期成功轮次。
- `POST /chat`：answer、conversation_id、request_id、sources、latency_ms，以及可获取的 usage 和分阶段耗时。
- `POST /chat/stream`：SSE 流。
- `GET /health`：进程存活及模型是否配置，**不表示**远程 API/知识库端到端可用。

每个来源包含 `citation_id`、`chunk_id`、`file_name`、`file_id`、`source_link`、`page_number`、`snippet`。来源编号从 1 开始；snippet 取实际提供给模型的片段预览，最多 500 字符。

SSE 保留旧 `{"token":"..."}` 与成功结束的 `[DONE]`，新增消息忽略未知字段即可兼容：

```text
data: {"type":"start","conversation_id":"...","request_id":"...","validated":false}

data: {"type":"sources","sources":[...],"validated":false}

data: {"token":"需要身份证。","validated":false}

data: {"type":"complete","answer":"需要身份证。[1]","sources":[...],"validated":true,"latency_ms":321,...}

data: [DONE]
```

错误使用 `event: error` 和 JSON `type/error code/detail/request_id/validated:false`，不发送 complete 或 `[DONE]`。普通接口以 HTTP 状态及 detail.code/message/request_id 返回。有效引用检查要求至少一个 `[数字]`，且每个编号都在本次来源中；它只检查引用格式/范围，**不证明事实正确或引用支持结论**。资料不足时模型应说明缺失并引用已检查的相关资料。

空知识库/缺密钥返回 503；无权限或不存在的会话返回 404；会话忙返回 409；超时 504；限流 429；引用错误或上游异常 502。流响应已开始后通过 SSE 报错。流式文字在 complete 前都是待验证内容，页面明确标记错误/中断。取消会关闭异步生成流并尽可能取消上游；失败和未完成回复不写入成功历史。同步 Chroma 查询和数据库操作移出 FastAPI 事件循环；已经在线程执行的本地操作不能被强行中止。

日志记录 request_id、检索/生成/改写/总耗时、错误类型，模型可返回的 Token 用量直接记录，否则 null。失败时没有完成的阶段指标可为 null。默认不记录完整提示词、文档正文或密钥，不启用 LangSmith tracing。反向代理须关闭 SSE 缓冲，转发正确的同源 host/scheme；跨站写入请求被拒绝。

## Docker

```bash
docker build -t rag-ai-knowledge-assistant .
docker run --rm -p 8000:8000 --env-file .env \
  -v "$PWD/data:/app/data" rag-ai-knowledge-assistant
```

`.dockerignore` 排除 `.env`、Google 凭证、令牌、知识库及本地输出，不将其复制进镜像。API 容器查询已导入的向量时无需挂载 Google 凭证。导入应先在本机完成 OAuth，之后单独挂载令牌和客户端文件：

```bash
docker run --rm --env-file .env -v "$PWD/data:/app/data" \
  -v "$PWD/credentials.json:/app/credentials.json:ro" \
  -v "$PWD/token.json:/app/token.json" \
  rag-ai-knowledge-assistant python scripts/ingest_drive.py --confirm-cost
```

当前方案面向单机本地 Chroma 与 SQLite；多机部署需要独立存储服务。本次已尝试 Docker 构建，但 Docker Hub 的 python:3.12-slim 元数据拉取超时，尚未完成容器构建/运行验证；也没有真实 Google/OpenAI 端到端验证。

## 测试与人工验收

```bash
python -m pytest -q
python -m pip check
```

自动化使用模拟聊天/Embedding、临时 Chroma 集合、临时 SQLite，不依赖生产数据。覆盖页码、稳定 ID、去重、文件版本更新/失败保留/隔离、旧集合查询保护、适配元数据、普通/流式请求、追问改写、引用错误、会话持久化/隔离、超时/服务失败、认证和静态页面安全。

实际浏览器检查（额外需要 Node 与 Playwright）：

```bash
# 终端一：仅本机离线测试服务，临时会话库
python tests/ui_server.py
# 终端二：在临时 npm 环境安装 playwright 并缓存 Chromium
node tests/browser.cjs
```

可设置 `PLAYWRIGHT_MODULE` 指向外部已安装的 playwright 模块，避免给应用增加前端依赖。脚本验证发送、Enter/Shift+Enter、流式待验证状态、来源卡片、新对话、恶意 HTML 安全显示、引用失败、取消不写历史与手机布局；截图输出到 `/tmp/rag-chat-desktop.png` 和 `/tmp/rag-chat-mobile.png`。

真实模型验收问题示例见 [docs/evaluation.md](docs/evaluation.md)。需要配置真实凭证并明确同意 API 费用后再运行。自动化不评判模型答案逐字一致，也不代替业务事实核验。

## 官方 API 参考

实现参考 [LlamaIndex SentenceSplitter](https://developers.llamaindex.ai/python/framework-api-reference/node_parsers/sentence_splitter/)、[ChromaVectorStore](https://developers.llamaindex.ai/python/framework-api-reference/storage/vector_store/chroma/)、[OpenAIEmbedding](https://developers.llamaindex.ai/python/framework-api-reference/embeddings/openai/) 与 [LangChain ChatOpenAI](https://docs.langchain.com/oss/python/integrations/chat/openai)。官方页面可能随版本更新；本项目安装版本另经本地实际 API 和集成测试验证。
