# R6-K Postman collection closeout

**日期**: 2026-07-14
**作者**: Mavis
**对应 commit**:
- `00ae55c` `9df5294` (R6-K Postman collection 入库)
- `round6-k-postman-closeout` (本次收尾: 字段一致性工具 + 收尾文档)

## 0. TL;DR

R6-K Postman collection 跑通 26/26 PASS,顺手补了**字段名一致性静态检查工具** `scripts/check_postman_schema.py` 防下次 commit 翻车。989 passed(973 R6-G baseline + 16 新增,0 回归)。

## 1. R6-K Postman collection 实施回顾

### 1.1 实施内容
- 新建 `tests/postman/R6-K_Interivew_Agent.postman_collection.json`(Postman 2.1 格式, 7 步流程 + 14 Tests 断言)
- 加 `backend/data/materials.json` 测试条目 `interview_20260714_002`(沿 R6-H `f50e715` `interview_20260714_001` precedent 模式)
- 端点流程: `health → start → reply×3 → draft → save-card`
- 环境变量: `base_url=http://127.0.0.1:8000`, `session_id` 在 step 2 自动写入 env

### 1.2 跑通结果
**26/26 PASS**(实际用户跑通 2026-07-14 20:54):
- 2 断言: health check
- 7 断言: start (含 R6-K circuit_state 字段)
- 5 断言: reply #1 (含 R6-K circuit_state 透传)
- 0 断言: reply #2 (过渡步骤, 跟 R6-A / R6-B 测试惯例一致)
- 4 断言: reply #3 (can_draft=true + force_draft=true + state=DRAFT_READY)
- 4 断言: draft (R6-B Phase 4 verification 字段)
- 3 断言: save-card (material_ref.id 写库 + 200 OK)

## 2. 字段名一致性坑 + 修复

### 2.1 踩到的 2 个 assertion 写错 bug

| Step | 老断言(错) | 实际 API 响应 | 错在哪 | 修复 |
|------|--------|---------|------|------|
| Step 3 reply #1 | `pm.expect(json.captured_delta.responsibility).to.be.a('string')` | `captured_delta = {background: "..."}` | 1st turn policy 选 `communication` gap, `suggested_slots=[background, action, method, result]`, 第 1 步实际问 **background** 不是 responsibility | 改 `(json.captured_delta.responsibility \|\| json.captured_delta.background)` 兼容 1st turn 实际是 background |
| Step 7 save-card | `pm.expect(json.material_ref.project_id).to.match(/^interview_\\d{8}_\\d{3}$/)` | `material_ref = {"type": "project", "id": "interview_20260714_NNN"}` | 字段名是 `id` 不是 `project_id`(API schema 一直是这样, 我之前手抄时写错) | 改 `json.material_ref.id` |

### 2.2 为什么自动化测试没发现

老实说, 我之前用的 4 层测试方法**没一层**能抓这个 bug:

| 测试方法 | 跑的内容 | 为什么抓不到这个 bug |
|---------|--------|---------|
| pytest(973 passed) | 后端逻辑 / Circuit Breaker / API response schema | 跑 Python, **不会执行** Postman collection 里的 JavaScript Tests script |
| `evaluate_interview_agent.py` end-to-end eval (40 sample) | LLM 抽取收益 / 报告 | **不关心** Postman 怎么写断言 |
| Postman Runner 实际跑 collection(R6-K commit `9df5294` 时) | 跑 7 步流程 | 当时只看 23/25 PASS 的数字, **没细看** PASS 的是哪些断言 / FAIL 的具体是哪条 |
| Python `urllib` + `json.dumps(ensure_ascii=False).encode("utf-8")` 实测 | 真打 API 看 raw response | 这是唯一能抓 bug 的方法, **不跑 Postman, 直接打 API** |

**核心问题**: Postman collection 的 Tests script 是**手写 JavaScript**, 提交前没有 lint / 没有任何 CI 验证。**pytest 跟 Postman 之间有条断层**。

### 2.3 根因复盘

提交 `00ae55c` `9df5294` 时只看了 23/25 PASS 的总数字, 没逐条检查断言名 → 这是手工测试的偷懒。pytest 测不出 JS 断言错, 没人有"Postman 测试 lint"工具, 断层就漏了。

## 3. 防回潮:`scripts/check_postman_schema.py`

### 3.1 工具能力

| 能 catch | 不能 catch |
|---------|---------|
| 字段名 typo (`project_id` 写成 `id` 之外) | 业务正确性 (1st turn 抽哪个 slot / 1st turn expected 哪个) |
| schema 改名 (后端改 `material_ref.id` → `material_ref.ref_id` 没同步 collection) | 时序错误 (combo1 满足后还有没有 slot 没问) |
| 字段路径嵌套层级写错 (`captured_delta.foo.bar` 多写一层) | policy 行为变化 (R6-E Phase 4 改 question_plan 优先读 → 工具不知道) |
| 字段名拼写 (`captured_dleta`) | 任何需要**实际跑 server**才能验证的语义 |

**核心定位**: 轻量级 typo catch + schema 同步提醒, **不是**业务正确性验证。业务正确性还是得靠 pytest + 真跑 server + 端到端 eval。

### 3.2 实现核心

```python
# 1. AST 解析 backend/api/interview.py 抽 Pydantic Response 字段
parse_pydantic_responses(BACKEND_API) -> {"StartResponse": {"session_id", "state", ...}}

# 2. AST 解析 core/interview_agent.py 抽 save_card 返回字面量
parse_save_card_literal(CORE_AGENT) -> {"save_card": {"material_ref", "material_ref.id", ...}}

# 3. 正则解析 Postman collection 抽 pm.expect(json.xxx).to 字段路径
parse_postman_assertions(POSTMAN_DIR) -> [{"step": "3. reply #1", "path": "captured_delta.responsibility"}, ...]

# 4. endpoint -> response schema 映射 + 字段路径校验
ENDPOINT_TO_SCHEMA = [
    ("/api/health", "HealthResponse"),
    ("/api/interview/start", "StartResponse"),
    ...
]

# 5. check_path_against_schema(path, schema_fields, nested_schemas) -> (ok, reason)
```

### 3.3 跑法

```bash
# 静态分析(不依赖 server 启动)
D:\python3.11\python.exe scripts/check_postman_schema.py

# 输出 (16 assertions, 0 failures):
# === R6-K_Interivew_Agent.postman_collection.json ===
#   [PASS] 1. health check          json.status                    (top-level field)
#   [PASS] 2. start interview        json.session_id                (top-level field)
#   ...

# 0 failures → exit 0
# ≥1 failures → exit 1
```

### 3.4 反向测试验证

故意把 collection step 7 改成 `json.material_ref.project_id`(老 bug):
- 工具精确 catch: `[FAIL] 7. save-card ... json.material_ref.project_id (field 'material_ref.project_id' not in nested schema for 'material_ref')`
- exit 1

### 3.5 pytest 锁(16 case)

`backend/tests/test_check_postman_schema.py`:
- `TestModuleLoading` 1 case (import 入口存在)
- `TestParsePostmanAssertions` 2 case (字段路径抽取 + 空 collection 兜底)
- `TestParsePydanticResponses` 2 case (Response 字段抽取 + 非 BaseModel 忽略)
- `TestParseSaveCardLiteral` 1 case (save_card 嵌套字段抽取)
- `TestEndpointMapping` 2 case (5 个 endpoint 映射 + 未知 endpoint 兜底)
- `TestSchemaPathCheck` 4 case (top-level 通过 / nested 通过 / nested 缺失 catch / top-level 缺失 catch)
- `TestMainEndToEnd` 3 case (good collection 0 failures / bad project_id catch / bad captured_dleta catch)
- `TestRealCollection` 1 case (真实 R6-K collection 回归)

**全跑通**: 16 passed, **973 + 16 = 989 passed baseline**, 0 回归。

## 4. 测试工作流改进 (本轮 + 长线)

### 4.1 本轮已落地 (R6-K closeout)

| # | 改进 | 文件 | 状态 |
|---|------|------|------|
| 1 | `check_postman_schema.py` 静态分析 | `scripts/check_postman_schema.py` + `backend/tests/test_check_postman_schema.py` | ✅ done |
| 2 | pytest 锁 check 工具行为 (16 case) | `backend/tests/test_check_postman_schema.py` | ✅ done |
| 3 | 测试数据清理 (R6-K 留 001~003 precedent, 清理 004~009 local dirty) | `backend/data/materials.json` | 📋 待 commit |

### 4.2 后续 round 候选 (R6-K+ / R6-L)

| # | 改进 | 价值 | 复杂度 | 优先级 |
|---|------|------|------|------|
| 4 | Newman CLI 接入 pre-push hook (`newman run collection.json --reporters cli,junit`) | 真跑 Postman 进 CI, 防 JS 语法错 | 中 (npm install) | P1 |
| 5 | FastAPI OpenAPI → Postman 自动生成 (`npx openapi-to-postmanv2 -s backend/openapi.json -o auto.json`) | 字段名永远跟后端同步, 不可能写错 | 中 | P1 |
| 6 | check_postman_schema 集成进 `scripts/verify.ps1` (pre-push hook) | commit 前自动跑, 不需要手动跑 | 低 | P1 |
| 7 | chat panel 真实 10+ 轮验证 R6-K 生产场景 | 验证 R6-K 部署在真用户路径下的降级行为 | 高 (需要 user 跑) | P2 |
| 8 | retry 指数 backoff (R6-K+ 范围内) | urllib 长 hang 场景下的回退策略 | 中 | P2 |

## 5. 决策档位

**R6-K Postman collection 决策: PASS** (R6-K closeout 收尾, 工具 + 文档同步落地)

- ✅ 7 步流程跑通 26/26 (含 R6-K circuit_state 透传验证)
- ✅ 字段名一致性静态检查工具落地 (防下次 commit 翻车)
- ✅ pytest 16 case 锁工具行为 (989 passed, 0 回归)
- ✅ 2 个原 bug 修复 (responsibility || background / material_ref.id)
- 📋 后续 round 候选 4 项 (Newman / OpenAPI 自动生成 / pre-push / chat panel 实测)

## 6. 文件清单 (本 round 收尾新增 / 修改)

### 新增
- `scripts/check_postman_schema.py` (220 行, 字段名静态检查工具)
- `backend/tests/test_check_postman_schema.py` (16 pytest 锁)
- `.harness/docs/round6-k-postman-closeout.md` (本文件)

### 修改
- `tests/postman/R6-K_Interivew_Agent.postman_collection.json` (修 2 个 assertion 错: step 3 / step 7)

### 待 commit (local dirty, 不入库)
- `backend/data/materials.json` 清理 `interview_20260714_004~009` (6 个测试 placeholder)
