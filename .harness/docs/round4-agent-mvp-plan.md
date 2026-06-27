# Round 4 — Agent MVP(补 AI Agent R&D JD 缺口)

> 状态: ✅ 完成 (2026-06-27) — 4 commit (`a4c9156` + `ac90e13` + `c5ec652` + `ba536df`),PR #1 已合并(8e2ce91),283 passed,0 skipped
> 父 ROADMAP: `.harness/docs/ROADMAP.md` 1. P1 段
> Round 标签: `feat(round4): agent-mvp`(3 步合一:`R4-F` Function Calling + `R4-A` Agent Loop + `R4-M` Session Memory)
> 工作量: 中(预计 ~500 行核心改动 + ~30 个 pytest)
> 设计原则: **MVP 优先,先打 JD 痛点再扩;每步独立 commit + 全量绿**

---

## 0. 背景(为什么开这一轮)

用户对照 AI Agent R&D JD,识别出 4 个项目目前的**结构性缺口**:

| 缺口 | 严重度 | 当前实现 | JD 期望 |
|---|---|---|---|
| **Function Calling / MCP** | 高 | LLM 走裸 `chat/completions`,无 `tools` 字段;工具是进程内 Python 函数 | OpenAI tools / Anthropic tool_use / MCP 协议栈 |
| **Agent Loop** | 高 | 单轮 LLM 调用,无 ReAct / Plan-and-Execute | 多轮推理循环,LLM 主动调用工具 |
| **Session 记忆与上下文管理** | 中 | 每次 generate 是无状态函数,无会话内上下文 | 短期 memory + 长期 memory(基础) |
| **可观测 / trace** | 中 | 仅有 `generation.log` 6 字段,无 LLM 推理链路 | 推理 trace + 工具调用日志 + 会话回放基础 |

**当前 252 个 pytest + 0 skipped 已稳**,这是改 agent 能力的好时点 — 新增功能必须守住 baseline。

---

## 1. MVP 范围决策(ROI 矩阵)

按"对 JD 信号 + 改动成本"做 ROI 排序,选 **3 个 backend round + 1 个可选 UI round**:

| 候选 round | JD 信号 | 改动成本 | 风险 | MVP 决策 |
|---|---|---|---|---|
| **R4-F: Function Calling 改造** | ★★★★★ | 中(~150 行) | 低(协议扩展,旧路径保留) | ✅ **必做** |
| **R4-A: Agent Loop(单工具,≤3 步)** | ★★★★★ | 中(~120 行) | 中(循环逻辑,需 max_step 防死循环) | ✅ **必做** |
| **R4-M: Session 记忆(进程内 dict)** | ★★★ | 小(~60 行) | 低(不持久化,无外部依赖) | ✅ **必做** |
| **R4-T: Trace 日志(推理链路可视化)** | ★★★ | 小(~40 行) | 极低(纯加日志) | ✅ **必做**(并入 R4-A) |
| **R4-C: Chat UI 组件(对话面板)** | ★★ | 中(~200 行) | 中(用户偏好 GUI 暂停) | ⏸️ **可选**(默认不动) |
| **R4-X: MCP server 接入** | ★★★★ | 大(~400 行) | 中(需新增 SDK) | ❌ **不做**(改 Function Calling 已能展示协议) |
| **R4-V: 完整会话回放** | ★★ | 中 | 中(需前端配合) | ❌ **不做**(trace log 已能定位) |

**结论**:MVP 范围 = R4-F + R4-A(含 trace)+ R4-M,R4-C 留作可选 next round。

---

## 2. R4-F:Function Calling 改造(MVP 第 1 步)

### 2.1 目标

把现有 `llm_rewriter.py` 改成"**LLM 主动调用工具**"模式:把 `match_score` 暴露为 OpenAI `tools` schema,改写时 LLM 可主动请求"先评估这段 bullet 跟 JD 的匹配度,再决定改写方向"。

### 2.2 设计要点

- **向后兼容**:`tools=None` 时,旧路径字节级一致(252 测试不破)
- **工具集** MVP 只暴露 1 个 — `evaluate_bullet_jd_match(bullet, jd_focus) -> {match_keywords, missing_keywords, suggestion}`(基于现有 `match_score` 内部逻辑)
- **协议层**:`_build_request_payload` 加 `tools` 字段(OpenAI function calling schema)+ `_extract_rewritten` 加 `tool_calls` 解析分支
- **触发条件**:`jd_focus is not None` 时才挂 tools(空 jd_focus 走老路径)— 跟现有 jd_focus 注入逻辑一致,不开新边界

### 2.3 改动文件

| 文件 | 改动 |
|---|---|
| `backend/core/llm_rewriter.py` | +`TOOL_EVALUATE_SCHEMA` 常量 + `_build_request_payload` 加 tools 字段 + `_extract_rewritten` 加 tool_calls 分支 + 顶层 `rewrite_highlights` 加 `enable_function_calling: bool = False` 参数(默认关) |
| `backend/core/jd_parser.py` | +`evaluate_bullet_jd_match(bullet: str, jd_focus: dict) -> dict` 导出(从 match_score 内部抽 surface 扫描逻辑) |
| `backend/api/resume.py` | `PreviewRequest` / `GenerateRequest` 加 `enable_function_calling: bool = False` 字段 |
| `tests/test_llm_rewriter.py` | +`TestFunctionCalling` 5 case(锁 tools 字段结构 / tool_calls 解析 / 旧路径字节级一致 / 失败降级 / jd_focus=None 不挂 tools) |

### 2.4 验收标准

- `cd backend && D:\python3.11\python.exe -m pytest tests/ -v` → **252 + 5 = 257 passed, 0 skipped**
- `cd frontend && npx vue-tsc --noEmit` → 0 error
- `cd frontend && npm run build` → 成功
- 端到端冒烟:`POST /api/resume/preview` 带 `enable_function_calling=true & jd_text=...` → 响应正常,日志显示 tools 已挂载

### 2.5 commit 风格

- `feat(round4-f): Function Calling 协议接入(tools schema + 旧路径字节级一致)`

---

## 3. R4-A:Agent Loop(单工具,≤3 步,MVP 第 2 步)

### 3.1 目标

把单轮 LLM 调用升级为 **ReAct-style mini loop**:LLM 可多轮推理,每轮可决定"调用工具" / "输出改写" / "放弃返回原文"。**严格 max_step=3 防死循环,严格 max_tokens 防爆**。

### 3.2 设计要点

- **Loop 流程**:
  ```
  for step in range(max_step):  # max_step=3
      resp = LLM(messages + tools, ...)
      if resp 有 tool_calls:
          tool_result = execute(tool_calls[0])
          messages.append(tool_result)
          continue  # 让 LLM 看工具结果再决定
      else:  # LLM 决定输出最终改写
          extracted = _extract_rewritten(resp, expected_count)
          if extracted: return extracted
          break  # 失败 → 降级原文
  return highlights  # 全失败降级
  ```
- **关键约束**:
  - `max_step=3` 硬上限(防止 LLM 一直调工具不输出)
  - 单步只能调 1 个工具(防止单轮 token 爆)
  - 网络错误不进入 loop(直接降级,不浪费 token)
  - Trace 写入 `logs/agent_trace.log`(独立日志,跟 `generation.log` 分离)— step / tool_name / latency_ms / outcome
- **向后兼容**:`enable_function_calling=False` 时,完全不走 loop(字节级一致,旧测试不破)

### 3.3 改动文件

| 文件 | 改动 |
|---|---|
| `backend/core/llm_rewriter.py` | +`MAX_AGENT_STEPS = 3` + `_call_with_agent_loop()` 新函数(包装 `_call_with_retry`,加循环 + trace 写入)+ `rewrite_highlights` 在 `enable_function_calling=True` 时调新函数 |
| `backend/core/logger.py` | +`log_agent_trace(session_id, step, tool_name, latency_ms, outcome)` 函数(写 `logs/agent_trace.log`) |
| `tests/test_llm_rewriter.py` | +`TestAgentLoop` 8 case(锁 max_step 上限 / 工具执行成功路径 / 工具失败回退原文 / 连续 3 步仍无 output 降级 / trace 日志写入 / 网络错误不进 loop / max_step=0 走老路径 / 单步单工具约束) |
| `tests/test_logger.py`(新建,小) | +3 case 锁 `log_agent_trace` 写入格式 + 文件创建 + 字段完整性 |

### 3.4 验收标准

- `pytest` → **257 + 8 + 3 = 268 passed, 0 skipped**
- 端到端冒烟:模拟 LLM 返 tool_calls(用 mock)→ 看到 trace 日志 3 行(step 1/2/3)+ 最终改写成功
- 端到端冒烟:模拟 LLM 3 步都返 tool_calls → 第 4 步被 max_step 截断,降级原文

### 3.5 commit 风格

- `feat(round4-a): Agent Loop (max_step=3) + 单工具约束 + trace 日志`

---

## 4. R4-M:Session 记忆(MVP 第 3 步)

### 4.1 目标

加进程内 **session 字典**:`session_id -> deque(maxlen=10) of {role, content, tool_calls?}`。**不持久化,进程退出即丢**(MVP 够用,JD 写"短期 memory"即可)。

### 4.2 设计要点

- **存储**:`_SESSIONS: dict[str, deque]`,纯进程内
- **API**:
  - `create_session() -> session_id`(uuid 短串)
  - `get_messages(session_id) -> list[dict]`
  - `append_message(session_id, role, content, tool_calls=None)`
  - `clear_session(session_id)`
- **集成**:`rewrite_highlights` 接受 `session_id: str | None = None`,挂上后 LLM messages 累积
- **隐私**:`session_id` 由前端生成(不存任何 PII),后端不写 session 内容到日志(只写 session_id + 步数)— 跟现有 PII 约束一致
- **过期**:MVP 不做 TTL(进程退出即丢,够了)

### 4.3 改动文件

| 文件 | 改动 |
|---|---|
| `backend/core/session.py`(新建,~60 行) | `_SESSIONS` 字典 + 4 个 API + 单测 friendly(无外部依赖) |
| `backend/core/llm_rewriter.py` | `rewrite_highlights` 加 `session_id: str | None = None` 参数,挂上后从 session 拉历史 messages 拼到 LLM messages 头部 |
| `backend/api/resume.py` | `PreviewRequest` / `GenerateRequest` 加 `session_id: str | None = None` 字段 |
| `tests/test_session.py`(新建) | +8 case(锁 create/append/get/clear/上限 10/None 走无 session 路径/session_id 唯一/线程不安全标记) |
| `tests/test_llm_rewriter.py` | +`TestSessionIntegration` 3 case(锁 session_id 拼接到 LLM messages / session=None 不拼接 / 多轮同 session 累积) |

### 4.4 验收标准

- `pytest` → **268 + 8 + 3 = 279 passed, 0 skipped**
- 端到端冒烟:同 `session_id` 连续 3 次 preview → LLM messages 累积到 3 条 user + 3 条 assistant
- 端到端冒烟:不同 `session_id` → 各自独立

### 4.5 commit 风格

- `feat(round4-m): Session 记忆(进程内 deque,上限 10) + 隐私隔离`

---

## 5. (可选)R4-C:Chat UI 组件

> **本 round 默认不启动** — 用户偏好"GUI 实施任务默认暂停"。待 R4-F/A/M 全量绿 + 用户明确启动后再开。

### 5.1 范围(预留)

- `frontend/src/components/AgentChatPanel.vue`(~150 行) — 展示推理 trace
- `App.vue` 顶部加"高级 / Advanced"折叠面板,默认收起
- 展示 LLM 推理 step / 工具调用 / 输出,3 个 trace 卡片(step-by-step)

### 5.2 触发条件

- 用户说"启动 R4-C"
- 或发现 backend trace 信息没出口,需要 UI 看

---

## 6. MVP 收尾验证清单(R4 整体)

| 项 | 命令 / 证据 |
|---|---|
| 全量 pytest 绿 | `cd backend && D:\python3.11\python.exe -m pytest tests/ -v` → **279 passed, 0 skipped** |
| 旧 baseline 不破 | R3-G/R3.5/R3-M.2/R3-M.3/R3-P 关键 case 全部保留 |
| 6 role `_BASELINE_HASHES` 锁死 | 改 default 排序路径时,baseline hash 仍有效(`enable_function_calling=False` 老路径字节级一致) |
| 前端类型检查 | `cd frontend && npx vue-tsc --noEmit` → 0 error |
| 前端构建 | `cd frontend && npm run build` → 成功 |
| 端到端冒烟 | 启 backend + frontend,3 个 role 跑 preview/generate,功能不退化 |
| trace 日志可见 | `backend/logs/agent_trace.log` 有内容(开 Function Calling 时) |
| README 当前能力表 | 加 1 段"Agent MVP(R4-F/A/M):Function Calling + Agent Loop + Session 记忆" |
| AGENTS.md 测试数 | 252 → 279 更新,锁 3 个新锁点(`R4-FunctionCalling` / `R4-AgentLoop` / `R4-Session` / `R4-LoggerTrace`) |
| 冗余测试清理 | tester 跑完审视 — 删重复 / 薄 wrapper / mock 自指 |

---

## 7. 风险与回退

| 风险 | 触发条件 | 回退策略 |
|---|---|---|
| Function Calling 协议差异(非 OpenAI 提供方) | `_http_post_json` 返非标准 tool_calls 格式 | 解析失败 → 降级老路径,trace 记一行 "tool_parse_fallback" |
| Agent Loop 死循环 | LLM 一直返 tool_calls 不输出 | 硬上限 max_step=3 + 单步单工具 + 第 4 步强制 break 降级 |
| Session dict 内存膨胀 | 长期运行 + 大量 session_id | MVP 不处理;P2 加 LRU + TTL |
| 前端 session_id 冲突 | 用户开 2 个 tab 共享 session | MVP 不处理;P2 加 cookie 隔离 |
| pytest baseline hash 漂移 | _en 字段 / 新参数 / default 改动 | `_BASELINE_HASHES` 在 R4-F 末尾重算固化 |

---

## 8. 后续 P2 候选(本 round 不做)

- **R4-X: MCP server 接入**(替换 Function Calling 为 MCP 协议,JD 信号高,但 ~400 行,改 SDK 风险大)
- **R4-V: 完整会话回放**(把 `agent_trace.log` 做成可读 markdown,带时间轴)
- **R4-Eval: 离线评测脚本扩 agent 维度**(ground truth 加 5 份 Function Calling 启用 vs 关闭的对照 case)
- **R4-C: Chat UI 组件**(用户明确启动才开)
- **R4-Persist: Session 持久化**(sqlite / JSON,跨进程)— 触发条件:用户用着发现进程退出丢上下文

---

## 9. 与 JD 强映射(给简历/项目描述用)

| 改动 | 对应 JD 关键词 | 证据 |
|---|---|---|
| R4-F | "掌握 Function Calling / MCP 开发经验" | `tools` schema + tool_calls 解析 + 旧路径兼容 |
| R4-A | "有 Agent 编排 / 任务规划 / 工具调用开发经验" | max_step=3 ReAct-style loop + 单工具约束 + trace |
| R4-M | "熟悉 Agent 记忆与上下文管理" | 进程内 deque 上限 10 + 短期 memory 拼接到 LLM |
| R4-A(trace) | "Agent 可观测性" | `logs/agent_trace.log` step 级别记录 |
| R4-F/A 失败降级 | "可靠性机制:重试/降级/错误分类" | 函数级 retry 1 次 + 3 步上限硬截 + 网络错误不 retry + 失败降级原文 |
| R4-M 隐私隔离 | "AI 安全与可信" | session 内容不写日志,只写 session_id + 步数 |

---

_本 plan 由 orchestrator 在 2026-06-27 R3-P 收尾后起草,等用户确认后启动。_
