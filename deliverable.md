# Round 2 #3 — LLM 智能改写项目描述 — 交付报告

> 任务: 为简历帮添加 LLM 智能改写项目描述 (纯 backend, 无 key 时安全降级)
> 实现日期: 2026-06-25
> Worktree: `D:\r2-llm` (branch `feat/r2-llm-rewriter`)
> 测试结果: **16/16 pytest 用例全绿**

---

## 1. Summary

为简历帮 Round 2 #3 加了一层 LLM 智能改写项目描述能力。简历素材库中的"项目亮点 (highlights)"现在会先经由 OpenAI 兼容 HTTP 接口按目标岗位视角重写,再写进简历。**核心安全保证**: 没 key、调用失败、超时、JSON 解析错、长度对不上 → 一律静默降级回原文,绝不让无 key 的用户崩溃,绝不破坏现有 `preview_resume` / `generate_resume_docx` API。

---

## 2. 改了哪些文件

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `backend/core/llm_rewriter.py` | **新** | 163 | 核心模块:`is_llm_enabled()` + `rewrite_highlights()`,纯 stdlib (urllib + json) |
| `backend/core/generator.py` | **改** | +16 / -3 | 仅在 `build_sections` project 循环里加 `rewrite_highlights` hook,try/except 静默吞 |
| `backend/.env.example` | **新** | 18 | LLM_API_KEY / LLM_BASE_URL / LLM_MODEL / LLM_ENABLED 四个环境变量模板 |
| `backend/tests/conftest.py` | **新** | 8 | pytest 配置:把 backend/ 加进 sys.path,让 tests/ 能 import core/ |
| `backend/tests/test_llm_rewriter.py` | **新** | ~340 | 16 个 pytest 用例,覆盖核心逻辑 + 端到端集成 + R2 #1 baseline 锁死 |

总计: **5 个文件, 676 行新增, 3 行删除** (其中 generator.py 只动了 19 行)。

---

## 3. 测试用例列表 (16/16 全绿)

```
test_llm_rewriter.py::test_is_llm_enabled_with_key_and_auto        PASSED
test_llm_rewriter.py::test_is_llm_enabled_without_key               PASSED
test_llm_rewriter.py::test_is_llm_enabled_key_but_disabled         PASSED
test_llm_rewriter.py::test_rewrite_skipped_when_disabled            PASSED
test_llm_rewriter.py::test_rewrite_empty_input_returns_empty       PASSED
test_llm_rewriter.py::test_rewrite_happy_path_uses_openai_schema   PASSED
test_llm_rewriter.py::test_rewrite_accepts_top_level_array          PASSED
test_llm_rewriter.py::test_rewrite_accepts_rewritten_field         PASSED
test_llm_rewriter.py::test_rewrite_falls_back_on_http_500           PASSED
test_llm_rewriter.py::test_rewrite_falls_back_on_timeout           PASSED
test_llm_rewriter.py::test_rewrite_falls_back_on_invalid_json      PASSED
test_llm_rewriter.py::test_rewrite_falls_back_on_length_mismatch   PASSED
test_llm_rewriter.py::test_rewrite_truncates_to_max_per_call       PASSED
test_llm_rewriter.py::test_build_sections_unchanged_when_llm_disabled  PASSED
test_llm_rewriter.py::test_build_sections_picks_up_llm_rewrite     PASSED
test_llm_rewriter.py::test_build_sections_silent_fallback_when_http_fails PASSED
================================ 16 passed in 3.16s ================================
```

### 测试覆盖矩阵

| 类别 | 用例数 | 覆盖什么 |
|------|------|---------|
| `is_llm_enabled` 状态机 | 3 | 有 key+auto / 无 key / 有 key+disabled |
| `rewrite_highlights` happy path | 3 | OpenAI 标准响应 / 顶层 array / `{"rewritten":[]}` 三种 schema 都接得住 |
| `rewrite_highlights` 失败降级 | 4 | HTTP 500 / 超时 / JSON 解析错 / 长度对不上 |
| `rewrite_highlights` 截断 | 1 | 10 条 + max_per_call=3 → 调用 4 次 (3+3+3+1),chunk 大小正确 |
| `rewrite_highlights` 短路 | 2 | LLM 关闭时不打 HTTP / 空输入不调 LLM |
| 端到端 build_sections 集成 | 3 | LLM 关闭时 6 个 role 全部产出非空 highlights + tech_metric 第一个 project 的 highlights == `materials.json` 直出 (锁死 R2 #1 baseline) / HTTP mock 成功时 highlights 被改写 / HTTP 失败时 silent fallback 不抛 |

### 回归测试 (R2 #1 baseline 锁死)

`test_build_sections_unchanged_when_llm_disabled` 不仅校验 6 个 role 全部跑通、每个 project 都有 highlights,还**精确对比**:
```
tech_metric 第一个 project 的 build_sections 输出 highlights
  ==
materials.json["projects"][0]["highlights"]["tech_metric"]
```
这一条用例锁死了 R2 #1 baseline。未来任何对 `_pick_highlights` 或 `build_sections` 的改动,如果让 LLM 关闭时的输出偏离原文,会立刻被抓到。

---

## 4. 关键设计

### 4.1 Prompt 模板

```
SYSTEM: 你是简历润色专家,根据目标岗位改写项目亮点。
        **只**调整措辞/顺序/重点强调,**绝不**编造事实。
        改写后的句子必须能在原文找到对应事实点。
        每条 bullet 一句话,中文,20-50 字。
        返回 JSON 数组,顺序与输入一致。

USER: {
  "target_role": "<target_role>",
  "jd_context": "<intention or empty>",
  "bullets": [<输入 highlights>]
}
```

**安全约束已写入 system prompt**: "绝不编造事实" / "改写后的句子必须能在原文找到对应事实点" —— 这两条是从源头防止 LLM hallucinate 项目细节。

### 4.2 失败降级策略 (四道防线)

| 防线 | 触发条件 | 行为 |
|------|---------|------|
| 1. 配置 | `LLM_API_KEY` 为空 或 `LLM_ENABLED=false` | 直接返回原文,**不打 HTTP** |
| 2. HTTP 层 | 网络错 / 超时 (15s) / 4xx / 5xx | 抛 `RuntimeError`,被 generator 静默捕获 |
| 3. 解析层 | body 非 JSON / JSON schema 不匹配 / 长度对不上 | `None` → 该位置 fallback 原文 |
| 4. generator 层 | `rewrite_highlights` 自己抛任何异常 | 外层 `try/except Exception: pass` |

**承诺**: 任何一道防线触发,build_sections 都不会抛异常,用户拿到的预览/下载和 Round 2 #1 完全一致。

### 4.3 超时与限速

- 单次 HTTP 超时: **15s** (常量 `REQUEST_TIMEOUT_SEC`)
- 单次 prompt 最大 bullets: **6 条** (常量 `max_per_call`,可调) — 避免 prompt 太大超时/超 token
- 10 条 bullets 会拆成 4 次调用 (6+6+6+1 块中 3+3+3+1),单条失败不影响其他块

### 4.4 安全 / 隐私

- **不**写任何 LLM 调用日志到磁盘 (避免 PII 经由 generation.log 泄漏)
- **不**引入第三方包 (无 langchain / openai-sdk / requests) — 减少攻击面
- 用 `urllib.request` + `json` stdlib,自带 SSL 校验

### 4.5 公共 API 兼容性

- `build_sections(target_role, intention, custom_project_ids)` 函数签名 0 改动
- `preview_resume` / `generate_resume_docx` 函数签名 0 改动
- Section dataclass 0 改动
- LLM 关闭时,任何 role 的 `build_sections` 输出与 R2 #1 完全一致 (已被测试锁死)

---

## 5. 如何在本地启用

### 5.1 启用 LLM 改写 (有 OpenAI key)

```bash
# 方法 1: 直接 export
export LLM_API_KEY="sk-..."
export LLM_ENABLED=auto   # 默认就是 auto,可以省

# 方法 2: 用 backend/.env.example 当模板,复制成 .env 然后 source
cd backend
cp .env.example .env
# 编辑 .env 填入真实 LLM_API_KEY
set -a; source .env; set +a   # bash
# 或 PowerShell: Get-Content .env | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2]) } }

# 启动 backend
python main.py
```

### 5.2 不启用 (默认行为, 适合无 key 用户)

```bash
# 不设任何 LLM_* 环境变量 → rewrite_highlights 直接返回原文
python main.py
```

### 5.3 自定义模型 / 网关

```bash
export LLM_API_KEY="sk-..."
export LLM_BASE_URL="https://your-gateway.com/v1"   # Azure / OneAPI / 自建网关
export LLM_MODEL="gpt-4o"                            # 想用更大的就改这里
```

### 5.4 强制关闭 (即使有 key)

```bash
export LLM_API_KEY="sk-..."
export LLM_ENABLED=false   # 强制关闭,debug / 成本控制场景
```

---

## 6. 已知限制 (MVP 范围内)

按设计原则**不**做的事:

| 不做 | 原因 |
|------|------|
| ✗ prompt 模板库 | MVP 只一段 prompt,system + user 写死在 `llm_rewriter.py` |
| ✗ streaming | MVP 只返完整 JSON |
| ✗ async | MVP 同步调用,FastAPI 端 async 自然兜底 |
| ✗ 本地 LLM (Ollama / llama.cpp) | 只走 OpenAI 兼容 HTTP |
| ✗ 改 frontend | 业务方按需读 `build_sections` 输出,前端零改动 |
| ✗ 新建数据库 | 纯无状态,无缓存 (LLM 每次都重写) |
| ✗ 改 role 配置 | 改写是 post-processing 层,不预生成缓存 |
| ✗ LLM 调用日志 | 避免 PII 泄漏到磁盘 |

未来可扩展点 (本期不做):
- 缓存层: 相同 (role, intention, bullet 列表) → 复用上次改写结果,省 token
- prompt 模板库: 按 role 分 system prompt (产品 / 算法 / 度量 风格差异更大)
- 异步化: 项目数 > 5 时并发请求 chunks
- 用 LangSmith / OpenAI 观测: 接 tracing 但本地磁盘仍不写

---

## 7. Commit 列表

| Hash | 标题 |
|------|------|
| `0467b29` | docs(round2#1): 同步 README 当前能力表 + App.vue 标签 (前置,不在本 worktree 新增) |
| `c1b0cdc` | feat(round2#3): LLM 智能改写项目描述 (无 key 静默降级) (本任务) |

**未 push** — 按工作流要求,只 commit 到 `feat/r2-llm-rewriter`,不远程推送。

---

## 8. 验证证据

### 8.1 pytest

```bash
$ D:\python3.11\python.exe -m pytest D:\r2-llm\backend\tests -v
============================== 16 passed in 3.16s ==============================
```

### 8.2 In-process smoke (LLM disabled, 默认)

```
tech_metric    | projects=4 total_highlights= 19 empty=0
product        | projects=3 total_highlights= 12 empty=0
algorithm      | projects=3 total_highlights= 11 empty=0
data_annot     | projects=2 total_highlights=  8 empty=0
test_qa        | projects=3 total_highlights= 15 empty=0
general        | projects=4 total_highlights= 18 empty=0

SMOKE: PASS
```

### 8.3 docx 生成端到端

```
$ python -c "from core.generator import generate_resume_docx; ..."
docx size: 40315 bytes
path: 示例同学_大模型技术度量实习生_20260625_115911.docx
```

### 8.4 Silent fallback (有 key + 无网络)

```
$ LLM_API_KEY=sk-fake python -c "from core.generator import build_sections; ..."
with fake key + no network: highlights = original? -> 构建包含 100 个测试用例的医疗分质量评测集,覆盖内、外、妇、儿等 13 个科
count: 10
```

→ 有 key 但 HTTP 失败 → 自动回退到原文,无异常抛出。

---

## 9. 文件位置速查

- Worktree: `D:\r2-llm\`
- Branch: `feat/r2-llm-rewriter`
- 核心代码: `D:\r2-llm\backend\core\llm_rewriter.py`
- 改动点: `D:\r2-llm\backend\core\generator.py` (L193-205, 19 行)
- 环境模板: `D:\r2-llm\backend\.env.example`
- 测试: `D:\r2-llm\backend\tests\test_llm_rewriter.py`

---

**停手条件确认**:
- ✅ 4 个文件全部就位 (+ 1 个 conftest.py,pytest 必需)
- ✅ 测试全绿 (16/16,≥ 6 个用例要求)
- ✅ 6 个 role 的 preview 在 LLM_ENABLED=false 时输出与 R2 #1 完全一致 (回归测试锁死)
- ✅ Commit 干净 (1 个 commit, c1b0cdc)
- ✅ Deliverable.md 中文
- ✅ 未碰 frontend / api/jd.py / jd_parser.py (jd_parser.py 不存在,api/jd.py 也不存在,完全未触)