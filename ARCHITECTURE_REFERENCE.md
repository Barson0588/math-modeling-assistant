# Math Modeling Assistant — 架构与技术特性参考手册

> 学习用途：每个组件用到的技术特性、设计模式、库和架构决策的详细拆解。

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [后端核心架构](#2-后端核心架构)
3. [LLM 交互层](#3-llm-交互层)
4. [论文生成流水线](#4-论文生成流水线)
5. [学术检索系统](#5-学术检索系统)
6. [AST 安全的论文改写引擎](#6-ast-安全的论文改写引擎)
7. [引用验证 Agent](#7-引用验证-agent)
8. [后台任务系统](#8-后台任务系统)
9. [数据库与存储](#9-数据库与存储)
10. [认证与安全](#10-认证与安全)
11. [前端架构](#11-前端架构)
12. [实时通信机制](#12-实时通信机制)
13. [部署与运维](#13-部署与运维)
14. [完整路由表](#14-完整路由表)

---

## 1. 整体架构概览

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| **Web 框架** | Flask 3.1.3 | 轻量 WSGI 框架，适合中小型项目 |
| **WSGI 服务器** | Gunicorn + Gevent | 生产环境并发（`gevent` worker 支持异步 I/O） |
| **AI 模型** | DeepSeek Chat (via OpenAI SDK) | 兼容 OpenAI 协议，成本低、支持 function calling |
| **前端** | Vanilla JavaScript (ES6+) | 无框架依赖，~5400 行 |
| **CSS** | 纯 CSS + CSS 自定义属性 | 暗色模式通过 `[data-theme="dark"]` 切换 |
| **Markdown 渲染** | markdown-it (CDN) | 浏览器端 Markdown → HTML |
| **数学公式渲染** | KaTeX (CDN) | 浏览器端 LaTeX 渲染，支持 `$$` / `$` / `\[` / `\(` |
| **数据库** | SQLite (本地) / Turso (云端) | 通过 Adapter 模式统一接口 |
| **部署** | Railway (PaaS) | 自动从 GitHub 部署 |
| **桌面打包** | PyInstaller | 跨平台 macOS .app + Windows .exe |

---

## 2. 后端核心架构

### 2.1 Flask 应用骨架 (`app.py`)

| 特性 | 实现细节 | 用到的技术 |
|------|---------|-----------|
| **应用工厂** | 单文件 `app.py`，直接创建 Flask 实例 | `Flask(__name__)` |
| **蓝图 (Blueprint)** | 3 个蓝图模块：auth、history、context_hint | `flask.Blueprint` + `app.register_blueprint()` |
| **CORS** | 仅允许生产域名 + 携带 credentials | `flask_cors.CORS` + `origins=[...]` |
| **限流** | 每个端点独立配置速率限制，存储在内存 | `flask_limiter.Limiter` + `@limiter.limit()` |
| **请求体大小限制** | 5MB | `app.config['MAX_CONTENT_LENGTH']` |
| **调试模式** | 文件变更自动重载 | `debug=True` + Watchdog (fsevents) |
| **错误处理** | try/except 包装所有 API 端点，返回结构化 JSON 错误 | `{"error": "..."}` |
| **全局超时** | `_run_with_timeout()` 用 ThreadPoolExecutor 加硬超时 | `concurrent.futures.ThreadPoolExecutor` |

### 2.2 语言检测与双语输出

| 特性 | 实现 | 位置 |
|------|------|------|
| **语言检测** | 统计中文字符占比 > 30% 判定为中文 | `app.py:_detect_language()` |
| **双语指令生成** | 英文内容输出时注入 `=== ENGLISH ===` / `=== 中文对照 ===` 块标记 | `app.py:_get_bilingual_instruction()` |

**设计决策**：用字符级统计而非 NLP 库，零依赖、毫秒级响应。

---

## 3. LLM 交互层

### 3.1 核心客户端 (`src/llm_client.py`)

| 特性 | 实现细节 | 模式 |
|------|---------|------|
| **SDK** | OpenAI Python SDK (`openai==2.45.0`) | 指向 `api.deepseek.com` |
| **超时** | 客户端级别 120s | `OpenAI(timeout=120.0)` |
| **重试策略** | 指数退避：2s → 4s → 8s，最多 3 次 | **Retry Pattern** (Exponential Backoff) |
| **重试条件** | 仅对 `APIConnectionError` / `APITimeoutError` / `RateLimitError` 重试 | 选择性重试，避免重复无效请求 |
| **温度** | 固定 `temperature=0.3` | 平衡创意与一致性 |
| **模型** | `deepseek-chat` | |

### 3.2 三种调用模式

| 模式 | 函数 | 返回值 | 适用场景 |
|------|------|--------|---------|
| **同步生成** | `generate_response()` | `str` | 评分、推荐、摘要精修等快速工具 |
| **流式生成** | `generate_stream()` | `Generator[str]` | 论文生成、报告生成等长文本 |
| **Function Calling** | `run_tool_loop()` | `str` | 引用验证 Agent（多轮 tool use） |
| **单次 Tool Call** | `generate_with_tools()` | `ChatCompletionMessage` | 需要单次工具调用的场景 |

### 3.3 Agentic Tool-Use Loop

```
run_tool_loop() 流程：
┌─────────────────────────────────┐
│ 1. 发送 system + user + tools   │
│ 2. LLM 决定是否调用工具         │
│ 3. 如果 tool_calls 不为空：     │
│    → 执行工具，结果加入历史     │
│    → 回到步骤 2（最多 max_turns 轮）│
│ 4. 返回最终文本回复             │
└─────────────────────────────────┘
```

**关键设计**：
- 完整的对话历史管理（`messages` 列表累积 system/user/assistant/tool 消息）
- 工具执行错误不中断流程（捕获异常返回 `"Tool error: {e}"`）
- `max_turns` 限制防止无限循环

---

## 4. 论文生成流水线

### 4.1 多步流水线 (`src/paper_pipeline.py`)

| 步骤 | 名称 | 输入 | 输出 | 用到的技术 |
|------|------|------|------|-----------|
| **Step 0** | Blueprint | 竞赛题目 + 要求 | JSON 建模蓝图 | `generate_response()` + JSON 解析（正则提取 code fences） |
| **Step 1** | Math Core | Blueprint + 题目 | 第 4-6 节（模型、求解、结果） | `generate_stream()` 流式输出 + `<analysis>` 标签 Chain-of-Thought |
| **Step 2** | Literature | Blueprint 关键词 | APA 格式参考文献列表 | Semantic Scholar API 搜索 + 去重 + 排序 |
| **Step 3** | Final Assembly | Math Core + References | 完整论文（10 节） | `generate_stream()` 流式输出 + `[CONTENT_RESET]` 标记 |
| **Post** | Validation | 完整论文 | JSON 验证报告 | `generate_response()` 非阻塞错误检查 |

### 4.2 流式输出协议 (SSE)

```
data: [STAGE:分析问题结构...]

data: [STAGE:生成建模蓝图...]

data: **Blueprint generated.**
data: 
data: ---
data: 

data: [CONTENT_RESET]

data: [STAGE:撰写摘要与引言...]

data: ## Abstract
data: ...

data: [DONE]
```

**SSE 标记类型**：

| 标记 | 含义 | 前端行为 |
|------|------|---------|
| `[STAGE:...]` | 阶段变更 | 更新进度卡片 |
| `[CONTENT_RESET]` | 清空缓冲区 | 清空 `fullContent` 和 DOM |
| `[DONE]` | 完成 | 移除光标、触发后续注入 |
| `[ERROR]` | 错误 | 抛出异常、渲染错误信息 |

### 4.3 防止幻觉的设计

| 技术 | 实现 |
|------|------|
| **真实文献注入** | Step 2 通过 Semantic Scholar API 检索真实论文，注入 Step 3 prompt |
| **引用白名单** | `USER_PAPER_FINAL` 明确要求「仅使用 Verified Reference List」 |
| **数据标注** | 要求 LLM 标注 `[MODEL OUTPUT]` / `[CITATION NEEDED]` / `[STATISTIC NEEDED]` |
| **CoT 验证** | 每节写入前用 `<analysis>` 标签验证推导正确性 |
| **后验证** | Post-Validation 检查 LaTeX 配对、公式编号、引用一致性、变量一致性、量纲齐次 |

---

## 5. 学术检索系统

### 5.1 双源检索 (`src/scholar.py`)

| 特性 | Semantic Scholar | Crossref |
|------|-----------------|----------|
| **API Key** | 无需 | 无需 |
| **速率限制** | ~100 req / 5min | ~50 req/s |
| **优势** | 引用计数、摘要 | 出版商信息、期刊名 |
| **超时** | `urlopen(timeout=15)` | `urlopen(timeout=15)` |
| **重试** | 1 次（仅 429） | 2 次（仅 429） |

### 5.2 合并与去重

| 步骤 | 技术 |
|------|------|
| **并行查询** | 先 Semantic Scholar，再 Crossref（顺序执行） |
| **去重** | 标题规范化比较（去除非字母数字字符 + 小写） |
| **排序** | 按 `citationCount` 降序 |
| **截断** | 返回 Top-N（默认 10） |
| **APA 格式化** | 作者截断（>5 → et al.）、DOI 链接 |

### 5.3 关键词搜索策略

```python
search_by_keywords(keywords, limit=10):
    1. 只用前 2 个关键词（控制响应时间）
    2. 每个关键词搜索 5 条
    3. 合并去重
    4. 按引用数降序
    5. 返回前 10 条
```

**设计决策**：限制关键词数量防止 API 调用爆炸。

---

## 6. AST 安全的论文改写引擎

### 6.1 核心思路 (`src/dedup_ast.py`)

```
问题：LLM 改写论文时可能破坏公式、代码、表格、图片
解决：用 Markdown AST 将文档拆分为"受保护块"和"文本段"

流程：
Markdown 文本
    ↓ markdown-it-py 解析
Token Tree (AST)
    ↓ 遍历 tokens
提取 Text Segments (纯文本段落)
    ↓ 发送给 LLM 改写
LLM Rewrites
    ↓ 按 segment id 匹配回去
重新组装 Token Tree
    ↓ 序列化为 Markdown
输出改写后的完整文档
```

### 6.2 受保护内容类型

| 类型 | 检测方式 | 占位符 |
|------|---------|--------|
| **代码块** | Fence tokens (` ``` `) | 跳过整个 block |
| **图片** | `![]()` 语法 | `⟨⟨PROTECTED_N⟩⟩` |
| **行内公式** | `$...$` | `⟨⟨PROTECTED_N⟩⟩` |
| **块级公式** | `$$...$$`, `\[...\]` | `⟨⟨PROTECTED_N⟩⟩` |
| **表格** | Table tokens | 跳过整个 block |
| **行内代码** | `` `...` `` | `⟨⟨PROTECTED_N⟩⟩` |
| **LaTeX 环境** | `\begin{...}...\end{...}` | 跳过整个 block |
| **水平线** | `---`, `***` | 跳过整个 block |

### 6.3 设计模式

| 模式 | 实现 |
|------|------|
| **Visitor 模式** | 递归遍历 markdown-it token tree，提取/替换文本 |
| **占位符模式** | `⟨⟨PROTECTED_N⟩⟩` 作为不可变令牌传递给 LLM |
| **序列化器模式** | `TokenMarkdownRenderer` 将 token tree 还原为 Markdown 文本 |
| **批处理** | 每批 5 个 segment 发送给 LLM，带进度心跳 |

### 6.4 关键技术点

- **markdown-it-py**：与前端 markdown-it (JS) 同源的 Python 实现，确保 AST 结构一致
- **inline token 分解**：将行内 token 拆分为"文本片段 + 受保护片段"的交替序列
- **循环引用检测**：`_find_inline_in_block()` 递归查找时用 `seen` 集合避免无限循环

---

## 7. 引用验证 Agent

### 7.1 架构 (`src/citation_grounding.py`)

```
完整流程：
输入：论文 Markdown
    ↓
Phase 1: extract_references()
    正则匹配 References 节 + [N] 格式引用
    提取：ref_id, ref_text, inline_markers, context_passages
    ↓
Phase 2: build_verification_prompt()
    将所有引用及其上下文构建为结构化 prompt
    ↓
Phase 3: run_tool_loop() (LLM Agent)
    LLM 自主调用 search_academic_paper 工具
    逐条验证：real / hallucinated / uncertain
    对 hallucinated 引用找真实替代
    ↓
Phase 4: parse_verification_response()
    解析 LLM 返回的 JSON 数组
    ↓
Phase 5: apply_corrections()
    在论文中替换引用文献
    ↓
输出：修正后论文 + 修正日志
```

### 7.2 引用提取的正则策略

| 模式 | 正则 | 示例 |
|------|------|------|
| **Reference 节头** | `(?:References?\|参考文献\|Bibliography)` | `## References` |
| **方括号引用** | `\[(\d+)\]\s+(.+?)` | `[1] Author. Title. Journal. 2020.` |
| **数字引用** | `(\d+)\.\s+(.+?)` | `1. Author. Title. Journal. 2020.` |
| **行内引用标记** | `\[(\d+(?:,\s*\d+)*)\]` | `[1]`, `[1,3,5]` |
| **上下文提取** | 引用标记前后 100 字符 | — |

### 7.3 Function Calling 工具定义

```python
SEARCH_ACADEMIC_PAPER_TOOL = {
    "type": "function",
    "function": {
        "name": "search_academic_paper",
        "parameters": {
            "query": "string (paper title or keywords)",
            "search_purpose": "verify_existence | find_replacement"
        }
    }
}
```

**设计决策**：工具返回 JSON 字符串而非直接操作数据库 — LLM 自行判断相关性。

---

## 8. 后台任务系统

### 8.1 TaskManager (`app.py`)

| 特性 | 实现 |
|------|------|
| **线程模型** | `threading.Thread(daemon=True)` |
| **任务注册** | UUID hex 12 位作为 task_id |
| **进度更新** | 线程安全（`threading.Lock` 保护共享状态） |
| **状态查询** | `GET /api/tasks/<task_id>` 返回 `{status, progress, stage, result, error}` |
| **自动清理** | `cleanup_old(3600)` 清除 1 小时前的任务 |
| **心跳动画** | `_heartbeat_progress()` 每 1.2s 更新一次进度，产生平滑动画 |

### 8.2 心跳进度机制

```
_start_pct ──────────────────────────── _end_pct
    │                                        │
    │  1.2s → update → 1.2s → update → ...  │  持续 duration_sec
    │                                        │
    └── threading.Event 可用作停止信号 ───────┘
```

**设计决策**：心跳线程是 daemon 线程，不会阻塞主线程退出。

### 8.3 硬超时保护

| 函数 | 用途 | 位置 |
|------|------|------|
| `_run_with_timeout(fn, timeout_sec)` | 用 `ThreadPoolExecutor(1)` 执行 fn，`future.result(timeout=...)` 强制超时 | `app.py` |

```python
result, error = _run_with_timeout(generate_response, 180, ...)
if error:
    return partial_results  # 超时后返回已有结果，不阻塞 UI
```

### 8.4 前端任务恢复

| 存储机制 | 用途 |
|---------|------|
| `sessionStorage['mma-tasks']` | 存 `{taskId, progress, stage, _tabId}` |
| `_runningTasks` 全局对象 | 内存中的任务状态 |
| 页面加载时 `resumePolling()` | 遍历 `sessionStorage`，恢复所有 running 任务的轮询 |

**设计决策**：`sessionStorage` 天然 tab 隔离，页面刷新可恢复，比 Cookie/URL 参数更安全。

---

## 9. 数据库与存储

### 9.1 数据库架构 (`src/db.py`)

| 特性 | 实现 |
|------|------|
| **双后端** | SQLite (本地) + Turso (云端 libsql) |
| **适配器模式** | `_TursoConnection` / `_TursoCursor` / `_TursoRow` 模拟 sqlite3 接口 |
| **WAL 模式** | SQLite 启用 WAL（Write-Ahead Logging）提升并发 |
| **外键** | `PRAGMA foreign_keys = ON` |
| **幂等建表** | `CREATE TABLE IF NOT EXISTS` |

### 9.2 表结构

| 表 | 字段 | 用途 |
|----|------|------|
| `user` | id, email, password_hash, encrypted_api_key, created_at | 用户信息 + 加密存储的 API Key |
| `history` | id, user_id, contest_type, problem_type, problem_text, result_content, content_type, starred, tags, created_at, updated_at | 论文生成历史（支持收藏和标签） |
| `session` | id, user_id, token, expires_at | 登录会话（7 天有效期） |

### 9.3 前端存储

| 机制 | 用途 |
|------|------|
| `localStorage` | API Key（加密前）、历史记录、草稿、登录状态、暗色模式偏好 |
| `sessionStorage` | 后台任务状态、侧栏 tab 元数据、AI 对话历史 |
| `Cookies` | `mma_session`（登录 token，HttpOnly） |
| **Service Worker Cache** | 静态资源 (v3 cache)，参考数据 API 响应 |

---

## 10. 认证与安全

### 10.1 认证系统 (`src/auth.py`)

| 特性 | 技术 |
|------|------|
| **密码哈希** | `werkzeug.security.generate_password_hash()` / `check_password_hash()` |
| **会话管理** | 服务端 `session` 表 + 客户端 `mma_session` cookie（7 天） |
| **API Key 加密存储** | `cryptography.fernet.Fernet` 对称加密 |
| **加密密钥** | `ENCRYPTION_KEY` 环境变量，开发时用 fallback |
| **装饰器保护** | `@login_required` → 检查 cookie → 查数据库 → 注入 `g.current_user` |
| **API Key 解析优先级** | 1. `Authorization` header → 2. 服务端存储（登录用户）→ 3. 环境变量 |

### 10.2 安全措施

| 措施 | 实现 |
|------|------|
| **API Key 验证** | `/api/check-key` 发送测试请求到 DeepSeek 验证 `sk-` 前缀 |
| **速率限制** | 每个端点独立配置（生成类 2-5/min，查询类 10/min） |
| **请求体限制** | 5MB 上限防止内存攻击 |
| **CORS 白名单** | 仅允许生产 Railway 域名 |
| **XSS 防护** | `escapeHtml()` 工具函数 + `innerText` 优于 `innerHTML` |

---

## 11. 前端架构

### 11.1 技术栈

| 层 | 选型 | 说明 |
|----|------|------|
| **框架** | 无（Vanilla JS） | 零构建步骤，ES6+ 直接运行 |
| **CSS** | 纯 CSS + 自定义属性 | 暗色模式通过 `[data-theme="dark"]` 切换 |
| **Markdown** | markdown-it (CDN) | browser 端渲染 |
| **数学公式** | KaTeX (CDN) | browser 端渲染 LaTeX |
| **字体** | Inter + JetBrains Mono + Noto Sans SC | Google Fonts |
| **PWA** | Service Worker + manifest.json | 离线缓存、可安装 |
| **图标** | Emoji + CSS shapes | 零依赖图标方案 |

### 11.2 核心架构概念

| 概念 | 实现 | 模式 |
|------|------|------|
| **6 Tab 布局** | Generator → Paper → Models → Problems → Guide → Roles | 单页应用 (SPA) |
| **侧栏工具** | `.result-sidebar` 滑入面板，每个工具独立 tab | **Tab 隔离模式** |
| **AbortController** | 每个侧栏 tab 独立的 `_sidebarAbortController` | 防止竞态条件 |
| **增量渲染** | SSE 流到达时 `insertAdjacentHTML()` 追加，不解析整个文档 | 性能优化 |
| **TaskRegistry** | `_runningTasks` + `sessionStorage` | **状态持久化模式** |

### 11.3 卡片式结果渲染

```javascript
_renderToolResultCard({
    title: '论文评审报告',
    icon: '🏆',
    meta: '按 COMAP 标准评分',
    sections: [
        { type: 'markdown', content: '...' },
        { type: 'warning', title: '...', content: '...' },
        { type: 'suggestion', title: '...', content: '...' },
        { type: 'code', language: 'python', content: '...' },
        { type: 'score', label: '创新性', value: 85, max: 100 },
    ],
    actions: [{ text: '应用修正', onClick: fn }],
})
```

### 11.4 DOM 安全操作

| 操作 | 实现 | 安全性 |
|------|------|--------|
| **文本节点替换** | `TreeWalker` + `NodeFilter.SHOW_TEXT` | 不触碰公式/代码/图片等非文本节点 |
| **英文内容提取** | `_extractEnglishContent()` | 4 级优先级：`<apply>` 标签 → `=== ENGLISH ===` 块 → ASCII 比率 → 段落分割 |
| **Diff 预览** | 红色删除 + 绿色新增的 GitHub 风格 diff | 替换前可视化确认 |
| **代码注入防护** | `escapeHtml()` 包装所有用户输入 | 防止 XSS |

### 11.5 AI Teammate (`static/js/ai-teammate.js`)

| 特性 | 实现 |
|------|------|
| **UI** | 可拖拽玻璃态气泡面板 (`position: fixed`) |
| **分角色对话** | 建模手 / 写手 / 教练 各自的对话历史 |
| **对话持久化** | localStorage 存储最近 50 条消息 |
| **自动提示** | 基于 `context_hint` API 的上下文感知建议 |
| **打字指示器** | CSS 动画三点跳动 |

---

## 12. 实时通信机制

### 12.1 两种通信模型

| 模型 | 方向 | 协议 | 用途 |
|------|------|------|------|
| **SSE (Server-Sent Events)** | 服务器 → 客户端 | `text/event-stream` + `ReadableStream` | 论文生成、工具流式响应 |
| **轮询 (Polling)** | 客户端 → 服务器 | HTTP `GET` 每 3s | 后台任务进度查询 |

### 12.2 SSE 实现细节

**后端**：
```python
return Response(
    stream_with_context(generate()),
    mimetype="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
)
```

**前端**：
```javascript
const reader = res.body.getReader();
const decoder = new TextDecoder();
// 按行解析 SSE: "data: ..." → 提取内容
// 空行 → 消息边界
```

### 12.3 流控策略

| 策略 | 参数 | 说明 |
|------|------|------|
| **增量渲染节流** | 每 50-80 字符或遇到 `\n\n` 时渲染 | 避免频繁 DOM 操作 |
| **安全断点** | 在段落边界 (`\n\n`) 处分割 | 避免截断 markdown 语法 |
| **流式光标** | `<span class="streaming-cursor-el">` 闪烁光标 | 视觉反馈 |
| **Gunicorn 超时** | `--timeout 120` | 长连接保护 |

---

## 13. 部署与运维

### 13.1 部署架构

| 环境 | 方式 | 配置 |
|------|------|------|
| **生产 (Railway)** | `gunicorn app:app -w 1 --timeout 120 --preload` | Procfile |
| **本地开发** | `python app.py` (Flask 内置服务器 + debug) | `debug=True` |
| **桌面 macOS** | PyInstaller `.app` bundle + `launcher.py` | macOS DMG |
| **桌面 Windows** | PyInstaller `.exe` + `launcher_win.pyw` | `.pyw` 无控制台窗口 |

### 13.2 CI/CD (GitHub Actions)

| Workflow | 触发 | 操作 |
|----------|------|------|
| `dependency-update.yml` | 每周一 | pip-check-updates → 自动 PR |
| `stale-issues.yml` | 每日 | 标记 30 天无活动 issue、45 天无活动 PR |
| `security-scan.yml` | 每周二 | Safety + pip-audit 安全扫描 |

### 13.3 PWA 离线策略

| 资源类型 | 缓存策略 | Service Worker 实现 |
|---------|---------|-------------------|
| 静态资源 (CSS/JS/字体/图标) | **Cache First** | 命中缓存直接返回 |
| 参考数据 API (models/problems/guide) | **Network First** | 网络失败时回退缓存 |
| 生成类 API | **Network Only** | 不缓存（实时性要求） |
| 离线回退 | 展示 `offline.html` | — |

---

## 14. 完整路由表

### 14.1 页面路由

| 路径 | 模板 | 功能 |
|------|------|------|
| `GET /` | `index.html` | 主应用 (SPA) |
| `GET /login` | `login.html` | 登录 |
| `GET /register` | `register.html` | 注册 |

### 14.2 论文生成 API

| 路由 | 方法 | 模式 | 速率限制 | 功能 |
|------|------|------|---------|------|
| `/api/generate` | POST | 同步 | 5/min | 论文框架生成 |
| `/api/generate/stream` | POST | SSE | 3/min | 论文框架生成（流式） |
| `/api/generate-paper/stream` | POST | SSE | 2/min | 完整论文流水线（3 步） |
| `/api/generate-paper/latex` | POST | SSE | 3/min | LaTeX 源码生成 |
| `/api/ai-report` | POST | 同步 | 10/min | AI 使用报告 |
| `/api/ai-report/stream` | POST | SSE | 8/min | AI 使用报告（流式） |

### 14.3 论文质量工具 API

| 路由 | 方法 | 模式 | 功能 |
|------|------|------|------|
| `/api/verify-math` | POST | 同步 | 数学推导验证 |
| `/api/verify-math/stream` | POST | SSE | 数学推导验证（流式，含 `[ERROR]`/`[FIX]` 对） |
| `/api/verify-references` | POST | 同步 | 参考文献真实性验证 |
| `/api/check-plagiarism` | POST | 同步 | 原创性/查重分析 |
| `/api/check-plagiarism/stream` | POST | SSE | 查重（流式） |
| `/api/deduplicate` | POST | 同步 | AI 降重改写 |
| `/api/deduplicate/stream` | POST | SSE | 降重（流式） |
| `/api/deduplicate-ast` | POST | 同步 | AST 安全降重 |
| `/api/deduplicate-ast/stream` | POST | SSE | AST 降重（流式 + 批进度） |
| `/api/refine-abstract` | POST | 同步 | 摘要精修 |
| `/api/refine-abstract/stream` | POST | SSE | 摘要精修（流式） |
| `/api/generate-sensitivity` | POST | 同步 | 敏感性分析代码生成 |
| `/api/score-paper` | POST | 同步 | COMAP 评分 |
| `/api/suggest-figures` | POST | 同步 | 图表建议 + matplotlib 代码 |
| `/api/compare-papers` | POST | 同步 | 论文版本对比 |
| `/api/mock-review` | POST | 同步 | 模拟 COMAP 评审 |
| `/api/analyze-paper` | POST | 同步 | PDF 论文分析 (PyPDF2) |

### 14.4 后台任务 API

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/tasks/<task_id>` | GET | 查询任务状态与进度 |
| `/api/tasks/deduplicate-ast` | POST | 创建 AST 降重任务 |
| `/api/tasks/check-plagiarism` | POST | 创建查重任务 |
| `/api/tasks/ground-citations` | POST | 创建引用验证任务 |
| `/api/tasks/rag-check` | POST | 创建统一 RAG 检验任务（查重 + 引用验证） |

### 14.5 数据与工具 API

| 路由 | 方法 | 功能 |
|------|------|------|
| `/api/roles` | GET | 团队角色信息 |
| `/api/models` | GET | 模型库（支持筛选：category, mcm_type, difficulty, search） |
| `/api/models/<name>` | GET | 单个模型详情 |
| `/api/problems` | GET | 历年真题库（支持筛选：contest, year, type） |
| `/api/guide` | GET | 竞赛指南（时间线、工具、清单、代码标准、可视化模板） |
| `/api/latex` | GET | LaTeX 模板 |
| `/api/scholar/search` | GET | 学术搜索 |
| `/api/scholar/references` | POST | 批量 APA 格式化 |
| `/api/explain` | POST | 通俗解释论文段落 |
| `/api/explain/stream` | POST | 通俗解释（流式） |
| `/api/recommend-models` | POST | 智能模型推荐（基于题目） |
| `/api/check-key` | GET | 验证 DeepSeek API Key |

### 14.6 认证与数据 API（Blueprint）

| 路由 | 方法 | 认证 | 功能 |
|------|------|------|------|
| `/api/auth/register` | POST | 无 | 注册 |
| `/api/auth/login` | POST | 无 | 登录 |
| `/api/auth/logout` | POST | 无 | 登出 |
| `/api/auth/me` | GET | 无 | 当前用户状态 |
| `/api/auth/save-key` | POST | 需要 | 保存 API Key |
| `/api/auth/get-key` | GET | 需要 | 获取 API Key |
| `/api/history` | GET | 可选 | 历史记录列表 |
| `/api/history` | POST | 需要 | 保存历史记录 |
| `/api/history/<id>` | PUT | 需要 | 更新历史记录 |
| `/api/history/<id>` | DELETE | 需要 | 删除历史记录 |
| `/api/history/import` | POST | 需要 | 从 localStorage 导入 |
| `/api/context-hint` | POST | 无 | 上下文感知提示 |

---

## 15. 关键设计决策速查

| # | 决策 | 理由 |
|----|------|------|
| 1 | **无前端框架**（Vanilla JS） | 项目规模可控，避免构建步骤，直接开发迭代 |
| 2 | **SSE 而非 WebSocket** | 单向数据流（服务器→客户端）足够，实现简单 |
| 3 | **后台任务用 Thread 而非 Celery** | 单用户场景，无需消息队列，daemon 线程足够 |
| 4 | **sessionStorage 而非 URL 参数** | Tab 隔离、刷新恢复、不污染 URL |
| 5 | **AST 保护而非正则替换** | 正则无法可靠区分数学公式和普通文本 |
| 6 | **双源检索而非单一 API** | Semantic Scholar（引用计数）+ Crossref（期刊信息）互补 |
| 7 | **结构化双语块标记** (`=== ENGLISH ===`) | 前端可精确提取英文替换内容 |
| 8 | **字符级语言检测而非 NLP 库** | 零依赖、毫秒级、准确率足够（中文字符占比 > 30%） |
| 9 | **Adapter 模式统一 SQLite/Turso** | 本地 SQLite 开发，生产环境无缝切换到 Turso 云数据库 |
| 10 | **PWA 三级缓存策略** | 静态资源 cache-first，参考数据 network-first，生成 API network-only |
