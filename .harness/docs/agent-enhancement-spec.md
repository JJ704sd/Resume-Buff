# AI Agent 增强 Spec

> 适用项目: 简历帮  
> 日期: 2026-06-27  
> 状态: **Phase 1 ✅ + Phase 2 ✅ 已落地**(320 → 352 pytest 全绿,2026-06-27)  
> 目标: 在现有 Round 4 Agent MVP 基础上,把简历生成链路增强为可规划、可调用工具、可观测、可评测、可回退的本地单用户 Agent 工作流。

## 阶段落地状态

| Phase | 目标 | 状态 | 关键产物 |
|---|---|---|---|
| Phase 1 | Agent 编排层与工具注册 | ✅ 已完成(2026-06-27) | `core/agent_tools.py`(AGENT_TOOLS 4 个 + `execute_agent_tool`)+ `core/agent_workflow.py`(`build_task_graph` 确定性 + `run_agent_workflow` 失败降级)+ `enable_agent_workflow` 字段;320 pytest 全绿,283 老测试零回退 |
| Phase 2 | 结构化 trace 与回放 | ✅ 已完成(2026-06-27) | `log_agent_trace_jsonl` 写 `backend/logs/agent_trace.jsonl` 11 字段 schema + `scripts/replay_agent_trace.py` argparse CLI;352 pytest 全绿(+32 新);安全审查无 P0/P1 阻塞 |
| Phase 3 | 轻量 RAG evidence | ⏳ 未启动 | 等用户明确启动 |
| Phase 4 | Agent eval 报告 | ⏳ 未启动 | 等 Phase 3 完成后启动 |

---

## 1. 背景与现状

简历帮已经不是单纯的规则版简历生成器。当前主链路是:

```
素材库 facts + 目标岗位 role + 用户粘贴 JD
  -> JD 解析与 match_score
  -> build_sections 排序与素材选择
  -> LLM 智能改写
  -> 预览确认
  -> docx 生成
```

Round 4 已完成 Agent MVP:

| 能力 | 当前实现证据 | 对应 Agent 场景 |
|---|---|---|
| LLM 集成 | `backend/core/llm_rewriter.py` 使用 OpenAI 兼容 `chat/completions`,支持 `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | 主流 LLM 集成与应用范式 |
| Prompt 工程化 | `SYSTEM_PROMPT` v2 含 few-shot、显式 JSON schema、JD focus 约束、schema validation、retry | Prompt 工程化 |
| Function Calling | `TOOL_EVALUATE_SCHEMA` + `evaluate_bullet_jd_match` + `tools/tool_choice` 挂载 | 工具调用 / Function Calling |
| Agent Loop | `_call_with_agent_loop()` 以 `MAX_AGENT_STEPS=3` 执行 ReAct-style mini loop | Agent 编排 / 任务规划雏形 |
| Agent 记忆 | `backend/core/session.py` 进程内 `_SESSIONS: dict[str, deque(maxlen=10)]` | 短期记忆与上下文管理 |
| 可观测性 | `logger.log_agent_trace()` 写 `backend/logs/agent_trace.log` | Agent trace / 工具调用观测 |
| 效果评测与回归 | 283 个 pytest,其中 R4-F/R4-A/R4-M 覆盖 Function Calling、Agent Loop、Session | Agent 效果回归 |
| 安全与可信 | 无 key 静默降级、网络错误不 retry、日志不写完整请求体/session 内容 | AI 安全与可信 |

当前仍存在 4 个缺口:

1. Agent 工作流只覆盖“改写 bullet”局部,还没有统一的“意图解析 -> 任务分解 -> 工具调用 -> 结果聚合 -> 反馈呈现”编排层。
2. Skill/Tool 注册仍散在代码里,缺少统一接口、权限边界和可扩展工具目录。
3. trace 已有日志,但还不能形成会话回放、离线评测数据和 A/B 对照报告。
4. RAG 还未正式接入;当前是关键词检索 + borrowed pool,可以作为轻量检索基线,但还不是向量化或证据片段增强生成。

---

## 2. 目标

本 spec 的目标是建设 “Agent Enhanced Resume Workflow”,让简历帮具备更完整的 AI Agent 研发证明力:

1. 搭建 Agent 工作流: 意图解析 -> 任务分解 -> 工具调用 -> 结果聚合 -> 反馈呈现。
2. 为 Agent 接入 Skill/Tool: JD 解析、素材检索、简历评分、bullet 评估、结构化抽取、内容改写、docx 生成、结果保存。
3. 实现可靠性机制: schema 校验、重试/降级、错误分类、步骤上限、可回退、权限与隐私校验。
4. 搭建可观测与评估: trace 日志、session replay、离线评测、Function Calling on/off 对照实验、成本/延迟指标。

非目标:

- 不做自动投递、招聘网站爬取、HR 跟踪。
- 不把后端暴露公网,不加账号系统。
- 不把真实个人信息、完整 JD、完整简历内容写入日志。
- 不在本轮引入复杂云服务、Redis、向量数据库或长期多用户权限系统。

---

## 3. 用户场景

### 3.1 JD 定制简历

用户粘贴一份 JD,选择岗位方向和模板。Agent 自动:

1. 解析 JD 的硬性要求、加分要求和关键词。
2. 检索素材库中可支撑的事实。
3. 判断素材缺口与简历匹配度。
4. 调用 bullet 评估工具检查每条经历对 JD 的覆盖。
5. 改写项目亮点,但不得编造事实。
6. 聚合为预览结果,标注“命中/缺失/建议补充”。

### 3.2 外部简历诊断

用户上传已有简历并粘贴 JD。Agent 自动:

1. 调用外部简历解析工具读取 docx/pdf/txt。
2. 对比“已有简历 / 素材库 / JD 要求”三者。
3. 输出 have/need 关键词和建议补强方向。
4. 生成更贴合 JD 的版本,保留人工确认。

### 3.3 多轮调优

用户连续修改 JD、角色或模板时,Agent 使用短期 session:

1. 记住本轮用户偏好,如“更偏产品”“保守一点”“不要太学术”。
2. 下一次预览时把历史偏好拼进 LLM messages。
3. session 最多保留 10 条消息,FIFO 淘汰。
4. session 内容只在进程内存,不持久化。

---

## 4. 总体设计

### 4.1 Agent 工作流

新增一个轻量编排层 `core/agent_workflow.py`,作为 preview/generate 前的可选路径。默认仍保持旧路径稳定;只有请求中显式开启 `enable_agent_workflow=true` 时进入新流程。

```
Intent Parse
  -> Plan Tasks
  -> Execute Tools
  -> Aggregate Evidence
  -> Rewrite / Build Sections
  -> Present Preview
  -> Human Confirm
  -> Generate Docx
```

每一步都产出结构化 `AgentStep`:

```python
{
  "step": 0,
  "name": "parse_jd",
  "tool": "parse_jd",
  "input_ref": "jd_text",
  "output_ref": "jd_profile",
  "status": "success",
  "latency_ms": 18,
  "error_type": None,
}
```

### 4.2 编排策略

MVP 不让 LLM 自由规划所有步骤,采用“受控 Plan-and-Execute”:

1. 系统先根据请求字段生成固定候选任务图。
2. LLM 只在有限范围内决定是否需要某些工具,例如是否调用 `evaluate_bullet_jd_match`。
3. 每步工具调用都有 allowlist、schema、timeout、降级策略。
4. 最终结果必须回到现有 `preview_resume()` / `generate_resume_docx()` 的数据结构,保证上层 API 和前端不被大改。

推荐任务图:

| 阶段 | 工具 | 必选 | 输出 |
|---|---|---|---|
| 意图解析 | `parse_user_intent` | 是 | role/template/JD/session 参数归一化 |
| JD 理解 | `parse_jd`, `match_score` | 有 JD 时 | jd_profile, jd_focus, score |
| 素材检索 | `retrieve_materials` | 是 | candidate projects/skills/highlights |
| 外部简历理解 | `parse_external_resume` | 上传文件时 | external_resume_text, resume_perspective |
| 单条评估 | `evaluate_bullet_jd_match` | Function Calling 开启时 | matched/missing/suggestion |
| 内容生成 | `rewrite_highlights` | LLM 可用时 | rewritten bullets |
| 结果聚合 | `aggregate_preview` | 是 | preview sections + evidence |
| 保存/导出 | `render_docx`, `log_generation` | generate 时 | docx path + generation log |

---

## 5. Skill / Tool 设计

### 5.1 Tool 注册表

新增 `core/agent_tools.py`,集中描述工具:

```python
AGENT_TOOLS = {
    "parse_jd": {
        "callable": parse_jd,
        "permission": "read_jd_text",
        "pii_risk": "medium",
        "timeout_ms": 300,
    },
    "match_score": {
        "callable": match_score,
        "permission": "read_jd_and_materials",
        "pii_risk": "medium",
        "timeout_ms": 500,
    },
    "evaluate_bullet_jd_match": {
        "callable": evaluate_bullet_jd_match,
        "permission": "read_bullet_and_jd_focus",
        "pii_risk": "low",
        "timeout_ms": 300,
    },
}
```

工具调用统一走 `execute_agent_tool(tool_name, args, context)`:

- 校验 tool 是否在 allowlist。
- 校验 JSON schema / Python 参数。
- 检查请求上下文是否允许访问 materials/JD/external resume。
- 捕获异常并转成结构化 `ToolResult`。
- trace 只记录 tool name、latency、status、error_type,不记录原文内容。

### 5.2 Skill 分类

| Skill | 说明 | 首批映射 |
|---|---|---|
| 检索 | 从素材库、JD、外部简历中找候选证据 | `match_score`, `retrieve_materials` |
| 结构化抽取 | 把非结构文本变成字段 | `parse_jd`, `parse_external_resume` |
| 内容理解 | 判断 bullet 与 JD 的覆盖关系 | `evaluate_bullet_jd_match` |
| 生成与编辑 | 改写 bullet、调整语气、压缩长度 | `rewrite_highlights` |
| 发布/保存 | 生成 docx、写 generation log | `render_docx`, `log_generation` |

### 5.3 RAG 增强路径

MVP 先做“轻量 RAG”,不引入向量数据库:

1. 把 `materials.json` 中项目、技能、荣誉切成 evidence snippets。
2. 使用现有 `KEYWORD_GROUPS` + JD parsed keywords 做 lexical retrieval。
3. 每个 snippet 返回 `source_type`, `source_id`, `matched_keywords`, `confidence`。
4. LLM 改写只能引用 evidence snippets 中的事实。

P2 再考虑向量化:

- 本地 embedding cache。
- SQLite 存 snippet + embedding。
- role/JD query 向量检索 top-k。
- 与关键词召回合并 rerank。

---

## 6. 可靠性机制

### 6.1 重试与降级

沿用并扩展现有策略:

| 场景 | 当前策略 | 增强策略 |
|---|---|---|
| 无 LLM key | 原文返回,不抛异常 | 保持 |
| LLM 网络错误 | 不 retry,直接降级 | 保持,trace `network_error_fallback` |
| LLM schema 错误 | retry 1 次 | 保持,记录 `schema_retry` 计数 |
| tool_calls 无法解析 | 降级原文 | 转 `tool_parse_error`,允许进入 fallback path |
| Agent loop 不出结果 | `MAX_AGENT_STEPS=3` 后降级 | 保持,trace `max_step_exhausted` |
| 工具异常 | 当前局部捕获 | 统一 `ToolResult(status="error")` |

### 6.2 错误分类

新增标准 error_type:

| error_type | 含义 | 是否可重试 |
|---|---|---|
| `network_error` | LLM/API 网络失败 | 否 |
| `schema_invalid` | LLM 输出不符合 schema | 是,最多 1 次 |
| `tool_not_allowed` | 非 allowlist 工具 | 否 |
| `tool_args_invalid` | 工具参数缺失/类型错误 | 否 |
| `tool_runtime_error` | 工具内部异常 | 否,走 fallback |
| `privacy_violation` | 试图写入敏感内容日志或越权访问 | 否 |
| `max_step_exhausted` | Agent 循环达到上限 | 否 |

### 6.3 可中断与可回退

本地单用户 MVP 不做真正异步队列,但要保证“每一步可回退”:

- preview 阶段不写 output,失败只返回旧 preview 或原文 bullets。
- generate 阶段只有 docx 渲染成功后才写 generation log。
- Agent trace 写 append-only 本地日志;trace 写失败不能影响主流程。
- 请求级 `enable_agent_workflow=false` 一键回退到当前 R4 路径。

### 6.4 权限与安全校验

- 工具必须在 allowlist。
- `PUT /api/materials` 仍仅用于本地,不增加公网能力。
- trace 不写完整 JD、完整简历、完整 bullets、真实姓名、邮箱、电话。
- session 内容不持久化,不写日志。
- 生成内容必须保留“不得编造事实”的 prompt 约束和 schema 校验。

---

## 7. 可观测与评估

### 7.1 Trace 日志

扩展 `backend/logs/agent_trace.log` 为结构化 JSONL,每行一条 step:

```json
{
  "ts": "2026-06-27T19:30:00",
  "session_id": "s12345678",
  "request_id": "rabcdef12",
  "workflow": "preview",
  "step": 2,
  "tool": "match_score",
  "latency_ms": 41,
  "status": "success",
  "error_type": null,
  "input_size": 1234,
  "output_size": 812
}
```

注意:

- `input_size/output_size` 只记录长度,不记录原文。
- request_id 用短 uuid,用于串联一次 preview/generate。
- 保留现有纯文本 trace 兼容测试,新增 JSONL 可作为 P2 或新文件 `agent_trace.jsonl`。

### 7.2 会话回放

新增本地脚本 `scripts/replay_agent_trace.py`:

- 输入 request_id 或 session_id。
- 输出 markdown 摘要:步骤、工具、耗时、成功/失败、降级点。
- 不输出敏感原文,只输出摘要与指标。

### 7.3 离线评测

基于现有 `简历帮知识库/jd_samples.json` 和 `AI岗位JD库_v4_intern.json`:

1. 选 8-12 份 gold JD 作为固定 eval set。
2. 对比 `enable_function_calling=false` 与 `true`。
3. 记录 score、coverage、rewritten schema pass rate、fallback rate、latency。
4. 输出 `AI岗位JD库_agent_eval报告.md`。

核心指标:

| 指标 | 目标 |
|---|---|
| schema pass rate | ≥ 95% |
| fallback rate | ≤ 10% |
| match_score 推荐档准确率 | 保持当前 8/8 ground truth 不回退 |
| P95 preview latency | 本地无真实 LLM 时不劣化;真实 LLM 场景记录基线 |
| hallucination guard | 测试集中不得出现无证据关键词硬塞 |

### 7.4 回归测试

新增测试必须覆盖:

- Agent workflow 任务图生成。
- Tool allowlist 与未知工具拒绝。
- ToolResult 错误分类。
- JSONL trace 不含敏感内容。
- workflow 关闭时旧路径字节级一致。
- Function Calling on/off 的稳定 A/B 输出结构。

---

## 8. API 与前端变更

### 8.1 API 字段

在 `PreviewRequest` / `GenerateRequest` 增加可选字段:

```python
enable_agent_workflow: bool = False
agent_trace: bool = False
```

已有字段继续保留:

- `enable_function_calling`
- `session_id`
- `jd_text`
- `academic_layout`

### 8.2 Preview 响应

preview 响应可选增加:

```json
{
  "agent_summary": {
    "request_id": "rabcdef12",
    "steps": 5,
    "tools_used": ["parse_jd", "match_score", "evaluate_bullet_jd_match"],
    "fallback_used": false,
    "latency_ms": 320
  }
}
```

默认不强制前端展示。P1 只在高级信息区展示简短摘要:

- 工具调用数
- 是否降级
- 总耗时
- 缺失关键词数

---

## 9. 分阶段实施

### Phase 1: 编排层与工具注册 ✅ 已完成(2026-06-27)

目标:

- 新增 `core/agent_tools.py` 和 `core/agent_workflow.py`。
- 把现有 `parse_jd`, `match_score`, `evaluate_bullet_jd_match`, `rewrite_highlights` 纳入注册表。
- API 增加 `enable_agent_workflow` 字段,默认关闭。

验收:

- 旧路径所有测试保持通过(283 → 283,字节级一致)。
- 新增 workflow 单元测试覆盖任务图、工具调用、未知工具拒绝(20 新 pytest)。
- `enable_agent_workflow=false` 时输出结构不变。

**落地证据**:

- `core/agent_tools.py`: AGENT_TOOLS 4 个核心 + `execute_agent_tool` 入口(allowlist / 错误分类 / 隐私边界);`ToolResult` 不存 args/input 原文
- `core/agent_workflow.py`: `build_task_graph(has_jd, enable_function_calling, has_external_resume)` 确定性产任务图(LLM 不参与规划);`run_agent_workflow` 失败时降级到旧路径;`enable_agent_workflow=False`(默认)字节级一致
- `api/resume.py`: `PreviewRequest.enable_agent_workflow` / `GenerateRequest.enable_agent_workflow` 字段,默认 False
- 测试: `test_agent_tools.py`(14 case)+ `test_agent_workflow.py`(29 case,含 9 个 Phase 2 trace 行为)= **37 case 全绿**

### Phase 2: 结构化 trace 与回放 ✅ 已完成(2026-06-27)

目标:

- 新增 JSONL trace。
- 新增 replay 脚本。
- 将 step/tool/error_type/latency/request_id 串起来。

验收:

- trace 不包含 JD 原文、bullet 原文、姓名、邮箱、电话。
- replay 能根据 request_id 输出步骤摘要。
- trace 写失败不影响 preview/generate。

**落地证据**:

- `core/logger.py`: `log_agent_trace_jsonl(event)` 写 `backend/logs/agent_trace.jsonl`;11 字段稳定 schema(`JSONL_TRACE_FIELDS` tuple 常量)—— ts / request_id / session_id / workflow / step / tool / latency_ms / status / error_type / input_size / output_size;写入失败(IO/磁盘满/编码错)由 logger 内部 try/except 静默降级不影响主流程(spec §6.3)
- `core/agent_workflow.py`: `generate_request_id()` 短 uuid(前缀 "r");`run_agent_workflow` 每个 step(含本地步骤)写一条 JSONL trace;本地步骤 `status="skipped"`,`input_size/output_size=0`;`_estimate_input_size` / `_estimate_output_size` 用 `json.dumps(...).encode("utf-8")` 算字节长度,不存原文
- `scripts/replay_agent_trace.py`: argparse CLI `--request-id` / `--session-id` / `--path`;输出 markdown 摘要(顶部 metadata + 7 列表格 + 错误汇总);只渲染 schema 字段,不输出 event 整体 dict;坏行静默跳过,文件不存在返空
- 测试: `test_logger.py`(14 case,含 11 Phase 2)+ `test_agent_workflow.py`(29 case,含 9 Phase 2 trace 行为)+ `test_agent_trace_replay.py`(10 case 新增)= **53 case 涵盖 Phase 2**
- **安全审查无 P0/P1 阻塞**(JSONL 不存原文 PII / 写入失败不阻断 / replay 不输出敏感内容 / request_id+session_id 都是 uuid 短串无 PII)
- 旧 R4-A `log_agent_trace` / `agent_trace.log` 完全不动兼容共存

### Phase 3: 轻量 RAG evidence

目标:

- 将 materials 切为 evidence snippets。
- 用关键词召回 + role 权重生成 top-k evidence。
- LLM 改写时注入 evidence,并保持“只基于事实改写”。

验收:

- 单测覆盖 snippets 生成、top-k 稳定排序、无证据时不编造。
- JD-driven preview 中能返回 evidence summary。
- match_score ground truth 准确率不回退。

### Phase 4: Agent eval 报告

目标:

- 新增 `scripts/evaluate_agent_workflow.py`。
- 对固定 JD eval set 跑 Function Calling on/off 对照。
- 输出 markdown 报告。

验收:

- 报告包含 schema pass rate、fallback rate、latency、score 档位变化。
- eval 脚本不读取或输出真实私有素材。
- 可作为每轮收尾验证的一部分手动运行。

---

## 10. 验收总表

| 类别 | 验收标准 |
|---|---|
| 功能 | 能跑通 JD -> Agent workflow -> tools -> preview -> generate |
| 兼容 | 默认关闭增强路径,当前 R4 行为不变 |
| 可靠性 | 网络错误/schema 错误/tool 错误/max step 都有可测降级 |
| 安全 | 日志/session/eval 报告不泄露 PII |
| 可观测 | 每次 Agent workflow 有 request_id + step trace |
| 评估 | 有固定 eval set 与 on/off 对照报告 |
| 测试 | 后端 pytest 全绿,前端 vue-tsc/build 全绿 |

---

## 11. 简历表述映射

该增强完成后,项目可以更扎实地覆盖以下 AI Agent 研发能力:

| JD 能力点 | 项目表述 |
|---|---|
| 熟悉主流 LLM 集成与应用范式 | 基于 OpenAI 兼容协议接入 LLM 改写链路,支持无 key 降级、schema validation 和 prompt 版本化 |
| 掌握 Prompt 工程化 | 设计 few-shot + 显式 JSON schema + JD focus 约束,并以回归测试锁定输出结构 |
| Agent 编排 / 任务规划 / 工具调用 | 实现受控 Plan-and-Execute 工作流,接入 Function Calling 工具与 max_step Agent Loop |
| RAG 检索增强 | 基于素材库 evidence snippets 的轻量检索增强,约束生成只能引用已有事实 |
| Agent 记忆与上下文管理 | 进程内 session deque 上限 10,支持多轮偏好传递且不持久化敏感内容 |
| 多 Agent 协作 | `.harness` 中 orchestrator/developer/tester 分工与 round 流程可作为工程协作证明 |
| Agent 效果评测与回归 | 283 pytest 基线 + JD ground truth + Agent on/off 离线评测报告 |
| 推理链路优化 | max_step=3、单步单工具、网络错误不 retry、可统计 latency/fallback |
| Agent 可观测性 | agent_trace JSONL + request_id + replay script |
| AI 安全与可信 | 不编造事实、人工预览确认、PII 不入日志、本地单用户边界 |
| 智能编码 Copilot | 通过 `.harness` 多 agent 脚手架和开发流程沉淀 AI 协作工程实践 |

---

## 12. 开放问题

1. 是否需要在前端展示完整 trace,还是只展示高级摘要。
2. 轻量 RAG 是否停留在关键词召回,还是进入本地 embedding cache。
3. Agent eval 报告是否纳入 pre-push hook,或保持手动脚本避免耗时。
4. session 是否需要 TTL;当前进程退出即丢符合 MVP 隐私边界。

---

## 13. 推荐下一步

建议下一轮从 Phase 1 + Phase 2 开始:

1. 先做工具注册表和受控 workflow,把现有 R4 能力统一起来。
2. 同步做 JSONL trace 和 replay,让每次 Agent 行为可解释。
3. 暂不引入向量库,避免把本地单用户工具复杂化。

这样可以最小改动覆盖“Agent 工作流、Skill/Tool、可靠性、可观测”四个核心 JD 场景,并为后续 RAG 与评测报告留出干净接口。
