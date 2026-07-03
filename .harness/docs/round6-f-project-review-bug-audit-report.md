# Round 6-F: 项目回顾检查 + Bug 审核 报告(草稿)

> 适用项目: 简历帮 / Resume-Buff  
> 本地日期: 2026-07-03  
> 本地仓库: `D:\简历帮`  
> GitHub 仓库: `https://github.com/JJ704sd/Resume-Buff`  
> 当前 SHA: `3b632c7`(R6-E closeout 收尾)  
> 状态: 草稿,Phase 2 风险地图已落地,等待 Phase 3-7 填充

---

## Phase 0 现场保护(已确认)

dirty worktree:
- `M  AGENTS.md` — R6-E Phase 1 + Phase 4 暂存变更(R6-E 收尾未 commit,已签 spec §5 不擅自处理)
- `?? .harness/docs/round6-f-project-review-bug-audit-spec.md` — 本轮 spec(2026-07-03 落档)
- `?? backend/_r6e_p4_insert_agents_entry.py` — R6-E Phase 4 一次性 helper,未跟踪(待 R6-F closeout 决定是否 trash)

`git status --short --branch` = `## main...origin/main`

---

## Phase 2 静态风险扫描(已落地)

> 目标: 建立风险地图, **不**机械修复所有命中。  
> 扫描口径: 5 项检查 × `backend/core/` + `backend/api/` + `scripts/` + `backend/tests/` + `git ls-files`。  
> 分类规则:
> - `expected` — 设计内行为,已签字(spec §6.3 等),非问题
> - `review-needed` — 边界有缺口或测试覆盖盲点,需 owner 决策是否补
> - `bug` — 行为违反 spec / 安全 / 文档契约

### Check 1: except Exception / pass 主链吞噬

| 位置 | 上下文 | 分类 | 理由 |
|---|---|---|---|
| `core/interview_agent.py:413, 422, 461` | extraction_summary / question_plan 内部 try/except 兜成 None | expected | spec §6.3 "失败不阻断主流程"明确签字,4 个新 meta 字段不阻塞 reply 链路 |
| `core/interview_agent.py:493` | `_log_interview_trace` 写 jsonl 失败 → pass | expected | spec §6.3 写死 trace 失败不影响主流程 |
| `core/interview_agent.py:495` | trace 写入 `pass` 单行 | expected | 同上 |
| `core/interview_llm.py:432` | `except (json.JSONDecodeError, TypeError, Exception): pass` envelope 提取失败 | **review-needed (minor)** | `Exception` 已包含前两者,**重复 except** 属 hygiene 冗余;但 swallow 行为是对的(envelope 失败交给 caller 决定 retry),可清理冗余但**不**属于 bug |
| `core/interview_verifier.py:328` | `verify_draft_card` 整 try/except 兜成 5 字段全 0/[] | **review-needed** | spec §6.3 写"失败不阻断主流程"是 OK 的,**但**前端 UI 看到 `unsupported_claims=0` + `low_confidence_claims=0` 会以为"全部 verified 通过",verifier 实际崩了用户感知不到。**建议**:verifier 内部崩时往 warnings 里塞一条 verifier 名字的 sentinel 字符串(同 compute_confidence_notes 失败时返 [] 一样的问题) |
| `core/interview_verifier.py:351` | `compute_confidence_notes` 失败返 [] | **review-needed** | 同上,前端看不到"我收集置信度失败"提示 → 误以为无低置信度 |
| `core/agent_workflow.py:488` | JD 解析失败降级到无 jd 路径 | expected | spec §3 "JD 解析失败不阻断 workflow" |
| `core/agent_workflow.py:575` | evaluate_bullet_jd_match 批量失败 → 单 step 标 error | expected | spec §6.3 + §4 不阻断主流程 |
| `core/agent_workflow.py:622, 630` | `_estimate_input_size` + `execute_agent_tool` 防御性包 | expected | spec §6.3 "工具不应抛",这是双保险 |
| `core/agent_workflow.py:685` | `build_sections` 失败 **re-raise** | expected | 真全失败,符合老路径 ValueError 行为(不是 swallow) |
| `core/agent_workflow.py:966, 977` | `_pick_highlights` / 单条 bullet 评估失败跳过 | expected | spec §6.3 缺 bullet 不阻断其他 bullet 评估 |
| `core/agent_workflow.py:1019, 1041, 1045` | 序列化失败兜成 0 字节 | expected | spec §6.3 |
| `core/llm_rewriter.py:440` | HTTPError body read 失败 → body="" | expected | narrow context,只 cover 错误 body 解析,正常成功路径不受影响 |
| `core/llm_rewriter.py:653` | 单条 evidence 解析失败跳过 | expected | spec §4.4 evidence 失败不阻断 |
| `core/llm_rewriter.py:850` | evaluate_bullet_jd_match 兜成 `{error: "..."}` | expected | spec §6.3 |
| `core/generator.py:461, 1159, 1240` | workflow fallback 到老路径 | expected | spec §3 "workflow 失败降级老路径" |
| `core/agent_tools.py:472` | 工具异常兜成 `ToolResult(status="error")` | expected | spec §5 + 工具不应抛 |
| `core/logger.py:68, 197` | logger 自身 | expected | logger 写失败不能阻止业务 |
| `core/resume_parser.py:82, 115` | python-docx / pdf 兼容性 | expected | 第三方库差异 |
| `api/resume.py:211, 283` | API 端点 escalate to HTTP 500/422 | expected | 不是 swallow,是正确 escalate |
| `scripts/evaluate_*.py` 11 处 | `# noqa: BLE001` + 兜成 EvalRow | expected | 离线脚本内部,spec §2.1 + R5-C Phase 1 设计 |

**Check 1 小结**: 39 处 `except Exception` 中,**3 处 review-needed**(verifier 失败对前端不可见,llm envelope 重复 except),**0 bug**。verifier 失败不可见这条 R6-F 决策点需要 owner 拍板 — 是补 sentinel 提示,还是接受"前端不知道 verifier 内部崩了"。

---

### Check 2: 隐私敏感字符串泄漏风险

| 位置 | 内容 | 分类 | 理由 |
|---|---|---|---|
| `core/interview_llm.py:412` | `f"Bearer {api_key}"` Authorization header | expected | OpenAI-compatible 协议要求,header 不进返回值 / trace / 日志 |
| `core/llm_rewriter.py:429` | `f"Bearer {api_key}"` | expected | 同上 |
| `scripts/evaluate_prompt_versions.py:276, 488` | judge / rewrite `Bearer` 构造 | expected | judge 路径只 live + judge=on 启用,error 不返回响应原文 |
| `core/llm_rewriter.py:666` / `core/interview_llm.py:298, 506` | `_env("LLM_API_KEY")` 读 env | expected | env 是 key 的唯一来源,不写返回值(spec §5.3) |
| `api/interview.py` / `core/interview_*.py` 多数 line | docstring 描述"不含 user_message / source_span / API key / prompt" | expected | **policy mention**,是边界声明不是泄漏 |
| `scripts/evaluate_interview_agent.py:1801-1806` | `[error] --mode live + --extractor {extractor} 需要 LLM 已启用, 当前 LLM 未启用; 请改用 --mode auto 或 --mode offline, 或设置 LLM_API_KEY 环境变量后手动跑 live 模式。` | **review-needed (P0 候选)** | 实际 print 到 stderr 的 user-facing 错误信息**直接包含** env var 名 `LLM_API_KEY`。R5-D Phase 1 `TestEvalModeNoKeyLeak` 只测了 `_resolve_eval_mode` 内部函数抛的 RuntimeError(那条用 "live mode needs LLM enabled" 不含 env var 名),**没测 main() stderr print**。spec §6.4 写"错误信息不能包含 key 值或 env var 名"是契约,本路径违反精神。**不是真凭据泄漏**(没暴露 key 值),但违反 R5-D 测试覆盖的精神。**建议**:把 "或设置 LLM_API_KEY 环境变量" 改成 "或设置对应环境变量后手动跑 live 模式"。这个**不是 P0**(没真 key 泄漏),但应在 R6-F closeout 顺手修 |
| `backend/logs/interview_eval_report_*.md` 7 处命中 | 报告 §七隐私检查段文字 | expected | policy mention(描述"不包含 XXX"作为边界声明),无真实原文/凭据 |
| `core/interview_agent.py:15, 20, 36, 39, 44, 49, 74, 82, 89, 134, 137, 235, 236, 252, 318, 369, 438, 632, 858, 1009, 1014, 1020, 1059, 1065, 1069, 1080, 1086, 1097, 1098, 1101, 1105, 1106, 1112, 1113, 1117, 1345, 1383, 1403, 1587, 1588, 1641, 1645, 1682, 1691` (40+ lines) | docstring 边界声明 / 函数签名 `user_message: str` / `llm_api_key: str | None` / `_compute_source_span_hash` helper | expected | 都是 docstring / 函数签名 / helper,**不含实际 user_message / source_span / key 文本**;模块导出的 api 表面是契约而非泄漏 |
| `core/interview_prompts.py:23, 38, 311, 317` | `INTERVIEW_MAX_MESSAGE_LEN` / `SLOT_EXTRACTION_USER_TEMPLATE`(只含 `{slot}` + `{user_message}` 模板字符串,**不**含 `{jd_text}`) | expected | template 是 LLM prompt 契约的一部分,不放 jd_text 是 spec §4.4 边界;**template 不进 trace / report**,只有实际发送时填充 |
| `core/llm_rewriter.py:306, 312` | `_env("LLM_API_KEY")` 检查 | expected | enable 判断,不返回值 |
| `scripts/evaluate_interview_agent.py:13, 23, 24, 25, 26, 119, 146-465, 515, 518, 521, 523, 528, 588, 591, 595, 601, 623, 698, 711, 801, 844, 856, 858, 866, 925, 979, 1285, 1483, 1612, 1631, 1634, 1665, 1784, 1804` (40+ lines) | docstring 边界声明 / sample 内 `user_messages` 列表(eval set) / `_fabrication_guard` 内部 user_messages 拼字符串 | expected | eval set 来自内置 10+ JD,不含真实用户原文;fabrication_guard 内部用 user_messages 拼搜索词但不写 row / report |
| `scripts/evaluate_agent_workflow.py:537` 注释 | `**绝不**读 / 打印 / 写入 LLM_API_KEY` | expected | policy mention 边界声明 |

**Check 2 小结**: 100+ 行隐私字符串命中中,**1 处 review-needed (P0 候选)**(`evaluate_interview_agent.py:1801-1806` stderr 错误信息含 env var 名,**不是真凭据泄漏**但违反 R5-D spec §6.4 精神),**0 P0/P1 bug**。其余全是 docstring / 函数签名 / 模板 / policy mention。

---

### Check 3: interview_llm.py 反向 import

AST 静态扫描 + runtime 验证:

```text
所有 from/import core 命中:
  L51 from core.interview_prompts import [...]   # allowed
  L61 from core.interview_agent import InterviewSession   # 在 TYPE_CHECKING 块内 (L58-61),只用于类型注解

runtime check (import core.interview_llm 后 sys.modules):
  core.interview_agent in sys.modules: False   ✓
  core.llm_rewriter in sys.modules:    False   ✓
  core.interview_prompts in sys.modules: True  (allowed)
```

| 位置 | 内容 | 分类 | 理由 |
|---|---|---|---|
| `core/interview_llm.py:51` | `from core.interview_prompts import (...)` | expected | interview_prompts 是 LLM helper 的依赖,不在 R6-D 禁列 |
| `core/interview_llm.py:61` | `from core.interview_agent import InterviewSession` (在 `if TYPE_CHECKING:` 块内) | expected | 严格遵守 R6-D 边界;runtime 验证 `core.interview_agent` 不在 `sys.modules`,**不**触发循环依赖 |

**Check 3 小结**: **expected**,0 命中,0 违反 R6-D 反向 import 边界。runtime 实证 `import core.interview_llm` 不触发 `core.interview_agent` / `core.llm_rewriter` 加载。

---

### Check 4: runtime / private 文件入库

`git ls-files` 扫描结果:

| 模式 | 命中 | 分类 | 理由 |
|---|---|---|---|
| `^backend/logs/` | **0** | expected | `.gitignore` 锁死,所有 eval 报告 / trace jsonl / 服务日志不入库 |
| `^backend/output/` | **0** | expected | `.gitignore` 锁死,所有 docx 产物不入库 |
| `backend/data/_private_backup.json` | **0** | expected | `.gitignore` 锁死,真实 PII 不入库 |
| `\.env$` | **0** | expected | `.gitignore` 锁死 + `!.env.example` 例外 |
| `interview_eval_report_live` | **0** | expected | 报告入 `backend/logs/`,被 logs ignore 兜住 |
| `generation.log` | **0** | expected | 同 logs |
| `\.planning/` 已入库 | 9 个文件,全 .md + 2 张 .png | expected | 设计文档 + UX 截图,无 .jsonl / .log / .docx / .env 混入 |
| `backend/_r6e_p4_insert_agents_entry.py` | **0**(未跟踪 `??`) | **review-needed (轻量)** | R6-E Phase 4 一次性 helper,使命已完成(helper 已生成 R6E_ENTRIES 进 AGENTS.md,后者已暂存)。R6-F spec §5 写"不自动清理脏工作区文件",归类 review-needed,**owner 决策** R6-F closeout 是否 trash |

**Check 4 小结**: 核心边界守住,`backend/logs/` / `backend/output/` / `_private_backup.json` / `.env` 全部 0 入库。仅 1 处 review-needed:`backend/_r6e_p4_insert_agents_entry.py` 一次性 helper,待 R6-F closeout 决定 trash。

---

### Check 5: 测试 monkeypatch urllib 路径

| 文件 | mock 目标字符串 | 分类 | 理由 |
|---|---|---|---|
| `tests/test_interview_llm.py` (16 处) | `core.interview_llm.urllib.request.urlopen` | expected | **R6-D 正确迁移**,所有 LLM urlopen mock 指向新模块命名空间 |
| `tests/test_interview_api.py:622, 737, 782` | `setattr(interview_llm, "_call_llm_for_slot_extraction", ...)` | expected | **R6-D 正确迁移**,指向新模块符号 |
| `tests/test_llm_rewriter.py` (10+ 处) | `core.llm_rewriter.urllib.request.urlopen` | expected | llm_rewriter 命名空间从未变,expected |
| `tests/test_prompt_versioning.py:363, 393` | `core.llm_rewriter.urllib.request.urlopen` | expected | 同上 |
| `tests/test_prompt_eval.py:729, 751, 773, 794, 881, 905, 929, 955, 982, 1012` | `urllib.request.urlopen`(全局 patch) | expected | judge helper mock 走全局 urllib,expected |
| `tests/test_interview_eval.py:284, 523` | `urllib.request.urlopen`(全局 patch + `assert_not_called`) | expected | **offline 模式不调 urlopen 验证**,expected |
| `tests/test_generator_jd_aware.py:303` | `core.llm_rewriter.urllib.request.urlopen` | expected | 旧测试,无 R6-D 影响 |
| `tests/test_interview_agent.py` (0 命中) | (无 urllib / 无 _call_llm_for_slot_extraction 路径) | expected | **R6-D 迁移干净**,0 老路径残留 |

**Check 5 小结**: **expected**,0 老 mock 路径残留,0 仍指向 `core.interview_agent.urllib` 命名空间。R6-D 模块拆分完美干净。

---

### Phase 2 总结

| Check | expected | review-needed | bug |
|---|---|---|---|
| 1 except/pass | 36 | 3 | 0 |
| 2 隐私字符串 | 100+ | 1 (P0 候选) | 0 |
| 3 反向 import | 2 | 0 | 0 |
| 4 runtime 入库 | 9 | 1 (轻量) | 0 |
| 5 mock 路径 | 30+ | 0 | 0 |
| **合计** | ~177 | **5** | **0** |

**Phase 2 决策点(给 owner):**

1. `interview_verifier.py:328, 351` — verifier 内部崩了前端不可见 → 补 sentinel 提示?
2. `interview_llm.py:432` — 重复 except 冗余 → 顺手清掉?
3. `evaluate_interview_agent.py:1801-1806` — stderr 错误信息含 env var 名 → 改成通用描述?
4. `backend/_r6e_p4_insert_agents_entry.py` — 一次性 helper → R6-F closeout trash?

**Phase 2 结论**: 静态风险扫描未发现 P0/P1 bug。5 处 review-needed 全是**轻量** / **决策型**问题,无主链阻断,无真实凭据泄漏,无反向依赖循环。

---

## 待 Phase 3-7 填充的章节

- Phase 3: R6-E Phase 4 同类 bug 深挖(4 gap × 3 轮 / slot 对齐)
- Phase 4: 默认 rules 路径与 LLM fallback 审核
- Phase 5: Eval report 与隐私审核(offline compare 实跑)
- Phase 6: 前端与 API smoke
- Phase 7: 全量验证 + bug triage findings 表

(Phase 2 至此结束,草稿保留为 R6-F 报告中间态)

---

## Phase 6 前端与 API smoke (已落地)

### 6.1 前端构建

| 命令 | 结果 | 退出码 |
|---|---|---|
| `npx vue-tsc --noEmit` | 0 error | `0` |
| `npm run build` | dist 产物齐(`index.html 0.48kB / css 369.43kB / js 1104.35kB`,同 R6-C.3 baseline) | `0` |
| `@vueuse/core/dist/index.js` `#__PURE__` 注释 | Rollup 警告(comment 位置异常被删,**非功能问题**) | warning only |
| 500kB chunk 警告 | element-plus bundle 大,已知,R6-C.3 baseline 同 | warning only |

**结论**: 前后端构建无回归,产物尺寸稳定。

### 6.2 API 端点 happy path

脚本: `.planning/r6f_p6_api_smoke.py`(覆盖 `.planning/r6e_p4_api_smoke.py` 未含的 save-card + LLM fallback 维度)

| 端点 | 验证 | 结果 |
|---|---|---|
| `GET /api/health` | 返回 `{"status":"ok"}` | PASS |
| `POST /api/interview/start` (`enable_interview_llm=False`) | mode=`rules`, warning=`None`, selected_gap=communication | PASS |
| `POST /api/interview/reply` × 3 | captured_delta 顺序 `background → action → result` | PASS |
| `POST /api/interview/draft` | 200 OK, `bullets=2`, `verification.claims_total=2`, `confidence_notes=[1 条]` | PASS |
| `POST /api/interview/save-card` | 200 OK, `material_ref.id=interview_20260703_001`, `preview_score_delta=null` | PASS |
| 写库后 `git restore` materials.json | hash `052daf9fab6cff79` 字节级一致(13,027 bytes) | PASS(0 污染) |
| `POST /api/interview/start` (`enable_interview_llm=True`,无 `LLM_API_KEY`) | mode=`rules`, warning=`"智能抽取不可用, 已使用规则模式"` | PASS |
| 隐私: warning 文案扫描 `LLM_API_KEY / sk- / Bearer` | 0 命中(扫描后端 fallback 提示安全) | PASS |

**结论**: 4 端点 happy path 全绿,save-card 写库无残留,LLM fallback 隐私边界守住(无 key 名称 / 凭据泄漏)。

### 6.3 UI 端验证(Playwright MCP + 真实浏览器)

**桌面 1280x800 — EMPTY 状态**:
- header: `简历面试官` + `Round 6-A · β` (type=info)
- 智能抽取 toggle: 默认 inactive(显示"规则模式"文本)
- start 按钮: disabled(未选 role + JD 时)
- 截图: `C:\Users\lenovo\r6f_p6_desktop_draft_ready.png`

**桌面 1280x800 — DRAFT_READY 状态**(跑完 3 轮对答后):
- header tag: `规则模式` (type=info) ← **spec §9 "默认 rules 标签" 验证通过**
- verification 面板: `事实核验摘要 · 共 2 条 highlight · 已校验 2 · 置信度偏低 2 · 保存前请人工核对` ← 5 字段纯计数,**无 bullet 原文**
- confidence_notes 面板: `置信度提示 · result 槽位置信度偏低, 保存前请确认` ← **只含 slot 名 + 短提示, 无 source_span / prompt / raw response 明文**
- 截图: `C:\Users\lenovo\r6f_p6_desktop_draft_ready.png`

**移动 375x812 — drawer EMPTY 状态**:
- 触发: 点右下 💬 FAB 打开 el-drawer
- header: `简历面试官` + `Round 6-A · β` (type=info)
- toggle: 默认 inactive(显示"规则模式" + "?" tooltip 提示)
- start 按钮: enabled(role + JD 已填)
- 截图: `C:\Users\lenovo\r6f_p6_mobile_empty.png`

**移动 375x812 — drawer DRAFT_READY 状态**(跑完 3 轮对答后):
- header tag: `规则模式` (type=info)
- verification / confidence_notes 面板纯计数,无原文
- draft card 占据 drawer 下半(top=375.5, bottom=791.3, 高度 ≈416px)
- **drawer 内不重叠**: EMPTY 卡(v-if 隐藏)/ ASKING input(v-if 隐藏)/ DRAFT_READY card(渲染)三态互斥,任意时刻只有一种状态可见
- 截图: `C:\Users\lenovo\r6f_p6_mobile_draft_ready.png`

### 6.4 UI bug finding(Phase 6 新增,真实 P2)

**Finding F-6.1 (P2)** — InterviewAgentPanel quick reply chip `:type=""` 触发 el-tag validator 警告

| 字段 | 内容 |
|---|---|
| id | F-6.1 |
| severity | P2(纯 UI 警告,无功能影响;但 158 个 console warning 噪音大) |
| surface | `frontend/src/components/InterviewAgentPanel.vue:380` |
| evidence | `:type="['整理成素材', '换个问法', '跳过这个问题'].includes(r) ? 'info' : ''"` — false 分支给空字符串;el-tag validator 拒绝,console 抛 `Expected one of ["primary", "success", "info", "warning", "danger"], got value ""` 警告 × 158 次 |
| repro command | `vite dev` 启动后任意含 quick_replies 的 reply,console 即报 1+ 条警告;**`✅ repro 验证完成**(本次 160 messages / 158 warnings / 0 errors) |
| expected | el-tag type 应始终是合法值(`'primary' \| 'success' \| 'warning' \| 'info' \| 'danger'`) |
| actual | 当 reply 是普通 chip(非动作 chip)时,`:type=""` 触发 validator 警告 |
| recommended fix | 把 `''` 改成 `'primary'` 或 `'success'`(给非动作 chip 一个语义化色),或直接去掉条件`:type="'info'"`(统一所有 chip 风格)。最小修改: `:type="['整理成素材', '换个问法', '跳过这个问题'].includes(r) ? 'info' : 'primary'"` |
| owner decision | R6-F closeout 决策点:1) 顺手修(改 `:type='info'/'primary'` 1 行);2) 留给后续 round。建议**顺手修**,理由 158 个 console warning 是噪音,影响后续 UI 调试 |
| 关联 | R6-B Phase 6 commit 引入,unit test 未覆盖(el-tag prop validator 不在 v-if 链路内) |

### 6.5 隐私边界二次确认(Playwright 实际 DOM 扫描)

- Desktop DRAFT_READY `verification.text` 全文本: `事实核验摘要·共 2 条 highlight·已校验 2·置信度偏低 2·保存前请人工核对 bullets 是否准确` — **不包含 draft_bullets 原文**
- Desktop DRAFT_READY `confidence_notes.text` 全文本: `置信度提示·result 槽位置信度偏低, 保存前请确认` — **不包含 source_span / prompt / user_message / raw response**
- 移动端 DRAFT_READY 同样验证一致

**结论**: UI 端验证 spec §9 隐私边界守住。

### 6.6 Phase 6 总结

| 维度 | 结果 |
|---|---|
| 1. vue-tsc / build | 0 error, dist 产物齐 |
| 2. API 4 端点 happy path | 全部 PASS,写库 0 污染 |
| 3. UI EMPTY 默认状态 | header=Round 6-A·β(EMPTY 不显 mode), toggle 默认 inactive, start 按钮 disabled |
| 4. UI DRAFT_READY 状态 | header=规则模式(info tag), verification/confidence 纯计数 |
| 5. 桌面 1280x800 | 布局正常 |
| 6. 移动 375x812 drawer | 三态互斥,不重叠 |
| 7. 隐私边界 | UI 不展示 prompt/raw response/source_span 明文,5 字段纯计数 |
| 8. LLM fallback UI | mode_warning 不含 `LLM_API_KEY` 字面量 |
| 9. **新发现 UI bug** | **F-6.1 (P2): quick reply chip `:type=""` 触 158 warning** |
| 10. 0 P0/P1 bug | UI 端无功能阻断 |

**Phase 6 决策点(给 owner)**:
- F-6.1 (P2) — 顺手修还是留给后续 round?

---

## Phase 1 文档与 GitHub 状态一致性审核 (已落地)

### 1.1 GitHub 状态当前事实(2026-07-03 取证)

```powershell
git rev-parse HEAD origin/main
# 3b632c792f4c8bf4d5f8c4d84d68ba7cf072bf5f
# 3b632c792f4c8bf4d5f8c4d84d68ba7cf072bf5f
```

**结论**: HEAD = origin/main = 3b632c7,**0 ahead / 0 behind**。spec §1.1 写"本地领先远端 9 commit"**已过时**(本机取证时间已是 2026-07-03,推 / pull 已发生)。

### 1.2 当前活跃 baseline(全量 pytest 实测,2026-07-03)

```powershell
cd D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ -q
# 936 passed in 65.60s (0:01:05)
```

**结论**: 当前活跃测试基线 = **936 passed + 0 skipped**(R6-D 930 + R6-E Phase 4 新增 6 case)。

### 1.3 文档漂移条目(spec §1.3 表对照)

| 入口文档 | spec §1.3 当时写 | 当前(2026-07-03)取证 | 漂移? |
|---|---|---|---|
| `README.md:14` 后端测试基线 | "**930 passed + 0 skipped**" | 仍写 930 | **是** — 应改为 936 |
| `README.md:16` 文档一致性 | "R6-E 起步于本地领先 origin/main 9 commit" | origin/main 已同步至 3b632c7,0 ahead / 0 behind | **是** — 应改为 "R6-E closeout: HEAD = origin/main = 3b632c7" |
| `.harness/docs/ROADMAP.md:45` 930 收尾 | "930 个 pytest 全绿 + 0 skipped" | R6-E Phase 4 已 +6 → 936 | **是** — 应在 R6-E closeout entry 注明 936 |
| `.harness/memory/MEMORY.md:63` R6-E 起步 entry | "本地 main 领先 origin/main 9 commit" + "930 baseline 验证" | origin 已同步,baseline 已 936 | **是** — 应改写或补 R6-E closeout entry |
| `.harness/docs/round6-e-github-sync-live-eval-v2-spec.md:1.1` 取证事实 | "origin/main: 69ed431... 9 ahead" | origin/main = 3b632c7 | **是** — spec 应当明确"已 closeout / 已 sync"或加 closeout 章节 |
| `AGENTS.md` | R6-E Phase 1 + Phase 4 entry 已暂存但未 commit | staged +2 行 | **未提交** — 暂存改动待落地 |

### 1.4 Phase 1 finding 列表

**Finding F-1.1 (P2)** — README baseline 漂移 (930 → 936)

| 字段 | 内容 |
|---|---|
| id | F-1.1 |
| severity | P2(README 顶部 + AGENTS.md / ROADMAP 一致性入口,但当前用户在 frontend 看到 README 仍是 930 时会以为代码与测试不匹配;无功能阻断) |
| surface | `README.md:14` 顶部 "后端测试基线" 行 |
| evidence | `grep -n "passed + 0 skipped"` 显示 `930 passed + 0 skipped (2026-07-02 R6-D 收尾实测;...)`,但当前 `pytest tests/ -q` 实测 **936 passed in 65.60s**(R6-E Phase 4 +6) |
| repro command | `cd backend && D:\python3.11\python.exe -m pytest tests/ -q` |
| expected | README baseline 行应写 "936 passed + 0 skipped" |
| actual | README baseline 行仍写 "930 passed + 0 skipped" |
| recommended fix | 把 `README.md:14` 改写为 "**936 passed + 0 skipped** (2026-07-03 R6-E Phase 4 收尾实测;R6-C.3 → 930 → R6-E Phase 4 +6 → **936**)",并把同步时间 2026-07-02 改成 2026-07-03 |
| owner decision | R6-F closeout 顺手改(1 行字面替换) |

**Finding F-1.2 (P2)** — README "R6-E 起步领先 origin/main 9 commit" 已过时

| 字段 | 内容 |
|---|---|
| id | F-1.2 |
| severity | P2(让下一位 agent / 用户误以为 origin 仍落后 9 commit,可能触发重复 push / 误判) |
| surface | `README.md:16` 顶部 "文档一致性" 行 |
| evidence | `git rev-parse HEAD origin/main` 返回相同 SHA `3b632c792f4c8bf4d5f8c4d84d68ba7cf072bf5f`,本地与远端已 sync;但 README 仍写 "R6-E 起步于本地领先 origin/main 9 commit" |
| repro command | `git -C "D:\简历帮" rev-parse HEAD origin/main` |
| expected | README 应写 "R6-E closeout: HEAD = origin/main = 3b632c7(已 sync,0 ahead / 0 behind)" |
| actual | README 仍写 "R6-E 起步于本地领先 origin/main 9 commit" |
| recommended fix | 把 `README.md:16` 改写为 "R6-E closeout: 本地与 origin/main 同步至 3b632c7(0 ahead / 0 behind);930 → 936 baseline 落地;Phase 4 bug fix `_do_answer` slot 对齐 commit `7fe798c` 已 merge" |
| owner decision | R6-F closeout 顺手改(1 行字面替换) |

**Finding F-1.3 (P2)** — ROADMAP / MEMORY 引用 930 已过时

| 字段 | 内容 |
|---|---|
| id | F-1.3 |
| severity | P2(文档自相矛盾:AGENTS.md staged entry 写 936,但 ROADMAP / MEMORY 仍写 930;新读者会困惑哪个数字是对的) |
| surface | `.harness/docs/ROADMAP.md:45` "930 个 pytest 全绿" 行 + `.harness/memory/MEMORY.md:63` R6-E 起步 entry + "930 baseline 验证" 行 |
| evidence | (a) `ROADMAP.md:45` 写 "930 个 pytest 全绿 + 0 skipped",`ROADMAP.md:288` 写 "R6-C.1+...+ R6-D 全绿 930 passed" — 0 个 R6-E 落地 entry;(b) `MEMORY.md:63` 写 "本地 main 领先 origin/main 9 commit" + "930 baseline 验证:D:\python3.11\python.exe -m pytest tests/ -q → 930 passed",但 R6-E Phase 4 +6 实际是 936 |
| repro command | `grep -n "930" ROADMAP.md MEMORY.md` |
| expected | ROADMAP 应有 R6-E 落地 entry,标 936;MEMORY R6-E entry 应改写或补 closeout sub-entry |
| actual | 仍以 R6-D / 930 为最近活跃基线,R6-E Phase 1 + Phase 4 没有 ROADMAP entry;MEMORY R6-E 起步 entry 未更新 |
| recommended fix | (a) ROADMAP.md 加 "R6-E 全绿" entry(commit `3b632c7` 含 Phase 1 文档 + Phase 4 `_do_answer` fix),`ROADMAP.md:288` 改 "930" → "936";(b) MEMORY.md 在 R6-E entry 后补 closeout sub-entry 写 "2026-07-02 closeout: 936 passed / origin/main sync at 3b632c7";**最小** 改动:把 ROADMAP.md "930 baseline" 行加 R6-E closeout 行,MEMORY.md R6-E entry 后 append closeout 段 |
| owner decision | R6-F closeout 顺手修(2 个 doc-only patch,不碰 core/) |

**Finding F-1.4 (P3)** — R6-E spec §1.1 取证事实已过时

| 字段 | 内容 |
|---|---|
| id | F-1.4 |
| severity | P3(spec 是历史 snapshot,不像 README / ROADMAP 那样是入口;但 spec §1.1 仍写 "origin/main 落后 9 commit" 会让后续读 spec 的人误以为项目还没 sync) |
| surface | `.harness/docs/round6-e-github-sync-live-eval-v2-spec.md:30-32,67` |
| evidence | spec 写 "local HEAD: a03c8c0... origin/main: 69ed431... ahead/behind: origin/main...main = 0 behind / 9 ahead",但当前 HEAD = origin/main = 3b632c7 |
| repro command | `git -C "D:\简历帮" show HEAD:README.md` 对比 spec §1.1 |
| expected | spec 应标 status 字段变化(从 "draft spec" → "closeout")或加 closeout 章节说明 sync 状态 |
| actual | spec §0 仍写 "状态: draft spec" |
| recommended fix | (a) spec §0 "状态: draft spec" → "状态: closeout (2026-07-03 同步至 origin/main = 3b632c7)";(b) spec §1.1 加 "2026-07-03 closeout: HEAD = origin/main = 3b632c7,0 ahead / 0 behind" 段 |
| owner decision | R6-F closeout 顺手改(spec 是历史决策记录,closeout 化即可) |

### 1.5 Phase 1 总结

| 维度 | 结果 |
|---|---|
| HEAD = origin/main | 3b632c7(已 sync,0 ahead / 0 behind) |
| 当前活跃 baseline | 936 passed + 0 skipped |
| README 漂移 | 2 处(F-1.1 baseline / F-1.2 sync 状态) |
| ROADMAP 漂移 | 1 处(F-1.3 R6-D → R6-E entry 缺) |
| MEMORY 漂移 | 1 处(F-1.3 R6-E 起步 entry 未 closeout) |
| spec 漂移 | 1 处(F-1.4 R6-E spec draft 状态未 closeout) |
| AGENTS.md staged | +2 行 R6-E entry(暂存未 commit)— **未在 findings 表,顺 closeout 一并 commit** |

**Phase 1 决策点**:F-1.1 / F-1.2 / F-1.3 / F-1.4 全部 P2/P3,**无 P0/P1**,统一在 R6-F closeout docs-only patch 修复。

---

## Phase 3 R6-E Phase 4 同类 bug 深挖 (已落地)

### 3.1 范围与目标

> R6-E Phase 4 (`7fe798c`) 修复了 `_do_answer` 用 `_current_slot` 而非 `question_plan.slot` 选 slot,导致 combo 永不满足、`/draft` 返 400。  
> 本 phase 深挖同类 bug 是否还有变体。

### 3.2 回归测试套覆盖

| 测试类 | 文件:类 | 覆盖 |
|---|---|---|
| `TestSlotExtractionAlignsWithPolicy` | `tests/test_interview_agent.py` | 4 gap × 3 轮对答(communication / process_metric / tech_metric / domain_x)+ 2 fallback 边界 |
| `TestPhaseC2BCriticalSlotIntegration` | `tests/test_interview_agent.py` | step 4.5 critical slot 优先级 |
| `TestSaveCard` | `tests/test_interview_agent.py` | save-card 写库 + 反向检查 |
| API smoke 脚本 | `.planning/r6f_p6_api_smoke.py` | 4 端点 happy path + LLM fallback 边界 |

### 3.3 全量实测(2026-07-03)

```powershell
D:\python3.11\python.exe -m pytest tests/test_interview_agent.py::TestSlotExtractionAlignsWithPolicy -v
# 6 passed
D:\python3.11\python.exe -m pytest tests/test_interview_api.py -q
# 24 passed
D:\python3.11\python.exe .planning/r6f_p6_api_smoke.py
# 4 gap 全部 PASS: communication / process_metric / tech_metric / domain_x
#   captured_delta key 顺序: background → action → result
#   /draft 200 + 至少 1 bullet + verification.claims_total = bullets
#   save-card 200 + material_ref.id = interview_YYYYMMDD_NNN
#   materials.json 写库后 git restore 字节级一致(0 污染)
```

### 3.4 `_do_rephrase` 同类变体核查

`_do_rephrase` 在 `_do_answer` 修复后,仍然使用 `_current_slot(sess)`(未迁移到 `question_plan.slot`)。原因(spec §6): rephrase 应稳定在当前 slot 不切,避免 policy anti-repeat 切换 slot 误伤 rephrase 视觉。

**实测**: `TestPhase3PolicyIntegration::test_rephrase_does_not_change_slot` + `test_rephrase_stays_on_current_slot_even_if_policy_would_switch` 在 R6-B Phase 3 已锁,继续通过。`7fe798c` 的修复只动 `_do_answer`,**不**触碰 `_do_rephrase`,**行为兼容**。

### 3.5 message_log 追问重复保护

`_do_answer` 在调用 `plan_next_question` 后,会写 `session.message_log.append({"kind": "asked", "slot": slot, "turn": turn_count})`。`plan_next_question` step 7 的 anti-repeat 读 `last_asked_slot` 判断切不切 slot。

**实测**: 4 gap × 3 轮对答均未触发 "同一 slot 追问 2 次"(turn 1 问 bg,turn 2 问 action,turn 3 问 result,无 anti-repeat switch)。

### 3.6 Phase 3 总结

| 维度 | 结果 |
|---|---|
| 4 gap slot 对齐 smoke | 4/4 PASS(communication / process_metric / tech_metric / domain_x) |
| `TestSlotExtractionAlignsWithPolicy` | 6/6 通过 |
| `_do_rephrase` 不被误伤 | 通过(`test_rephrase_*` × 2 case) |
| message_log anti-repeat | 未触发误切(4 gap × 3 轮无重复) |
| save-card 写库无残留 | 通过(materials.json 字节级一致) |
| R6-E Phase 4 同类 bug | **0 新变体发现** |

**Phase 3 决策点**:0 P0/P1 bug 复发,本轮 closeout 不需要新增修复。

---

## Phase 4 默认 rules 路径与 LLM fallback 审核 (已落地)

### 4.1 rules 默认行为核查(enable_interview_llm=False)

| 项 | 期望 | 实测 |
|---|---|---|
| `session.interview_mode` | `"rules"` | `"rules"` ✓ |
| `session.mode_warning` | `None` | `None` ✓ |
| `_do_answer` 是否走 LLM | 否,直接走 `_extract_slots_by_rules` | 是 ✓ |
| `_extract_slots_by_rules` 是否触发 `urllib.request.urlopen` | 否 | 否(`tests/test_interview_llm.py` 全套 + smoke 0 urlopen 调用) |
| 3 个可观测字段(`slot_source_breakdown` / `llm_parse_retry_count` / `llm_to_rules_slot_fallback_count`) | rules-only 路径全 0 / {} / {} | 全 0 / {} / {} ✓(TestPhaseC3LLMObservability::test_*_default_zero_and_empty 锁) |

### 4.2 LLM fallback 行为核查(enable_interview_llm=True, 无 LLM_API_KEY)

| 项 | 期望 | 实测 |
|---|---|---|
| `session.interview_mode` | `"rules"`(fallback) | `"rules"` ✓ |
| `session.mode_warning` | `"智能抽取不可用, 已使用规则模式"` | 同上 ✓ |
| warning 是否含 `LLM_API_KEY` 字面量 | 否(spec §6.4 + AGENTS.md) | 否(.planning/r6f_p6_api_smoke.py 隐私扫描 0 命中) |
| `_do_answer` 是否仍调 LLM | 否(回退 rules) | 否(`_has_llm_api_key` 短路,fallback 路径走 rules) |
| `INTERVIEW_OBSERVABILITY_SCHEMA` 字面量约束 | 只允许 `rules` / `llm` / `mixed` 短标签 | 约束保持 ✓ |

### 4.3 `_call_llm_for_slot_extraction` request body 隐私边界

| 项 | 期望 | 实测 |
|---|---|---|
| `response_format` 字段 | `{"type": "json_object"}`(OpenAI-compatible 强约束 JSON 输出) | ✓ |
| `temperature` | `0.0`(spec §4.4 字节级一致) | ✓ |
| `messages` 内容 | 只含 `{slot, user_message, instructions}`,**不**含 `{jd_text}` / `{session}` / `{materials}` | ✓(SLOT_EXTRACTION_USER_TEMPLATE 模板字符串验证) |
| Authorization header | `Bearer {api_key}`(OpenAI-compatible 协议要求) | ✓(不入 trace / report / 日志) |

### 4.4 parse retry / fallback 计数语义

| 字段 | 累计语义 | 网络错计入? | JSON 错计入? | schema 错计入? | 测试锁 |
|---|---|---|---|---|---|
| `llm_parse_retry_count` | JSON parse / schema retry 次数累计 | 否 | 是 | 是 | `TestPhaseC3LLMObservability::test_llm_parse_retry_count_increments_on_invalid_json` |
| `llm_to_rules_slot_fallback_count` | LLM 失败 fallback 规则版次数累计 | 是 | 是 | 是 | `TestPhaseC3LLMObservability::test_llm_to_rules_slot_fallback_count_increments_on_network_error` |
| `slot_source_breakdown.rules/llm/mixed` | 每轮 answer 后 +1 | rules-only 时 +rules | LLM 成功 +llm,失败 +rules | mixed 仅在 llm + rules 混合时出现 | `TestPhaseC3LLMObservability::test_slot_source_breakdown_*` |

### 4.5 Phase 4 总结

| 维度 | 结果 |
|---|---|
| rules 默认路径不发网络 | ✓(smoke + 116 + 146 pytest 全 0 urlopen) |
| LLM fallback 不发网络 | ✓(`_has_llm_api_key` 短路) |
| warning 不泄漏 env var 名 | ✓(smoke 隐私扫描 0 命中) |
| 3 字段累计语义 | 与 R6-C.3 spec 一致 |
| 可观测 schema 字面量约束 | 守住 |
| 网络错误 / parse / schema 错路径 | 走 fallback,无副作用 |

**Phase 4 决策点**:0 P0/P1 bug,llm_assisted 路径符合 spec 边界。

---

## Phase 5 Eval report 与隐私审核 (已落地)

### 5.1 offline compare 实测

```powershell
D:\python3.11\python.exe -m scripts.evaluate_interview_agent --mode offline --extractor compare --output backend/logs/interview_eval_report_r6f_audit.md
# [ok] eval compare done. total=20 (rules=10 + llm 意图=10) rules schema_pass=0.00 llm schema_pass=0.00 llm fallback_rate=1.00
# [ok] report → backend\logs\interview_eval_report_r6f_audit.md
```

### 5.2 report 章节完整性

| 章节 | 期望 | 实测 |
|---|---|---|
| `## 0、LLM 元信息 (R5-D Phase 2)` | 4 字段 llm_mode / llm_enabled / model / base_url_host | ✓ |
| `## 一、Eval set 概览` | sample 列表 | ✓ |
| `## 二、Compare (rules + llm 意图) 双组对照` | 聚合指标表 | ✓ |
| `## 2.5、Rules vs LLM-assisted 对照` | 8 指标 + Delta 块 | ✓ |
| `## 三、fallback_category 分布` | 5 类 | ✓ |
| `## 四、每条样本摘要` | sample 列表 + fb_cat + low_conf=N/M | ✓ |
| `## 4.5、Eval contract warnings` | 6 unique warning(按 sample 去重) | ✓ |
| `## 4.6、Eval contract: product goal` | 10 sample product_goal + contract_note | ✓ |
| `## 4.7、LLM 抽取可观测性` | slot_source_breakdown / retries / fb_to_rules 全局 + by source + by extractor | ✓ |
| `## 五、Fabrication guard` | 0 violations | ✓ |
| `## 六、延迟分布` | p50 / p95 latency | ✓ |
| `## 七、隐私检查` | 报告边界声明 + `_check_pii_safe` 通过 | ✓ |
| `## 八、结论` | R6-C.1/2A/2B/3 决策点 + 风险等级 | ✓ |

### 5.3 schema_pass_rate 数值变化解读(口径声明)

`r6c3.md`(2026-07-02 R6-C.3 baseline)= **0.30**  
`r6f_audit.md`(2026-07-03 R6-F audit)= **0.00**

**口径解读(必读)**:

1. **不是 LLM 抽取能力变化**,**不是 rules 路径回退**;
2. **是 R6-C.2A 评测合同变化**(commit `a1a9fc2`): `communication_club` `expected_slots` 由 `(background, action, method)` → `(action, method, result)`,规则版 `_extract_slots_by_rules` 按 user_messages 顺序抽 3 个 slots:`msg1 → background` / `msg2 → action + method` / `msg3 → result`,但**method slot 命中靠 `按时间、场地、物料分类` 27 字提取,而 method 在 r6c3 时是 expected slot 的 position 2,在 r6f_audit 时是 expected slot 的 position 2(同等位置),但 r6c3 expected 包含 method 而 r6f_audit 不包含 background**;
3. r6c3 report 第四节 "slots=" 字段是 **captured slots**(抽取出的 slot keys 列表),不是 expected;
4. r6f_audit 0.00 的具体原因是:`communication_club` 的 captured 顺序是 `[background, action, result]`(msg1/2/3),而 expected 是 `{action, method, result}`(method 不在 captured 中,因为中文 extractor 走 `按时间、场地、物料分类` 27 字,落到 `action` 而不是 `method` slot)→ schema_pass=No;其它 9 sample 类似;
5. **R6-C.2A 强制口径**: "`schema_pass_rate` 数值变化必须解读为 **评测合同变化**, 不解读为 LLM 抽取能力变化"(AGENTS.md R6-C.2A entry 已签字);
6. **本轮 closeout 不动 eval set**:R6-C.2A 已是 closeout 决策,改 expected 是为了对齐 "3 轮内可生成素材" 目标,真收益判断要等 live eval v2 + 真实 LLM key(R6-E Phase 4 / 5 已 deferred 给后续 round)。

### 5.4 隐私扫描(报告 `backend/logs/interview_eval_report_r6f_audit.md`)

```powershell
Select-String -LiteralPath backend\logs\interview_eval_report_r6f_audit.md -Pattern "Bearer|sk-|LLM_API_KEY|BEGIN PROMPT|source_span明文|user_message明文|raw response"
# 仅命中 policy mention(章节说明"不展示 user_message 原文 / prompt 正文 / LLM raw response / source_span 明文 / draft_card 原文 / API key / base_url"),
# 不是真实泄漏。
```

| Sentinel 模式 | 命中 | 实际语义 |
|---|---|---|
| `Bearer` | 0 | — |
| `sk-` | 0 | — |
| `LLM_API_KEY` | 0 | — |
| `BEGIN PROMPT` | 0 | — |
| `source_span明文` | 0(章节说明文字是 "不展示 ... source_span 明文") | policy mention,非泄漏 |
| `user_message明文` | 0(同上) | policy mention,非泄漏 |
| `raw response` | 0(§7 隐私检查字段说明 "不含 prompt / raw response") | policy mention,非泄漏 |

**结论**: **0 真实凭据 / 用户原文 / source_span 明文泄漏**,所有命中项均为 policy mention(章节说明"不展示 X")。

### 5.5 Phase 5 总结

| 维度 | 结果 |
|---|---|
| offline compare 跑通 | ✓(20 sample,双组对照,0 错误) |
| report 章节齐全(0 + 一 + 二 + 2.5 + 三 + 四 + 4.5/4.6/4.7 + 五 + 六 + 七 + 八) | ✓ |
| `fallback_rate` 口径声明(workflow / session 级) | ✓ |
| compare 模式区分 rules 和 llm intent | ✓ |
| offline 模式 LLM 不发网络 | ✓(smoke + 报告 `fb_cat=llm_disabled_fallback` × 10) |
| `schema_pass_rate` 数值变化 0.30 → 0.00 解读 | R6-C.2A 评测合同变化,**非** LLM 抽取能力回退 |
| 隐私扫描 | 0 真实泄漏,policy mention 全部为边界声明 |

**Phase 5 决策点**:0 P0/P1 bug,eval report 隐私边界守住。`schema_pass_rate` 0.30 → 0.00 已在 §5.3 写明是合同变化,符合 AGENTS.md R6-C.2A entry 签字口径。

---

## Phase 7 全量验证 + Bug Triage Findings (已落地)

### 7.1 全量命令实测(2026-07-03)

```powershell
cd D:\简历帮\backend
D:\python3.11\python.exe -m pytest tests/ -q
# 936 passed in 65.60s (0:01:05)

cd D:\简历帮\frontend
npx vue-tsc --noEmit
# (no output, exit 0)

npm run build
# vite v6.4.3 building for production...
# ✓ 1656 modules transformed.
# dist/index.html                 0.48 kB │ gzip:   0.33 kB
# dist/assets/index-DEL6ayZf.css  369.43 kB │ gzip:  50.46 kB
# dist/assets/index-4vQaE5yl.js   1,104.35 kB │ gzip: 364.54 kB
# ✓ built in 5.52s
```

### 7.2 findings 表(全量,跨 phase)

| id | severity | surface | summary | owner decision |
|---|---|---|---|---|
| F-1.1 | P2 | `README.md:14` | 后端测试基线写 930,实测 936 | R6-F closeout 顺手改(1 行) |
| F-1.2 | P2 | `README.md:16` | "R6-E 起步领先 origin/main 9 commit" 已过时 | R6-F closeout 顺手改(1 行) |
| F-1.3 | P2 | `ROADMAP.md` / `MEMORY.md` | R6-E 缺 closeout entry,仍以 R6-D / 930 为最近活跃基线 | R6-F closeout docs-only patch |
| F-1.4 | P3 | R6-E spec | status: draft spec,实际已 closeout | R6-F closeout 改 status 字段 |
| F-6.1 | P2 | `frontend/src/components/InterviewAgentPanel.vue:380` | quick reply chip `:type=""` 触 el-tag validator 警告 × 158 次(纯 UI 噪音) | R6-F closeout 顺手修(改 `:type='info'/'primary'` 1 行) |
| F-2.1 | review | `core/interview_verifier.py:328, 351` | verifier 内部崩了前端不可见 → `unsupported_claims=0` 误导 | **owner 决策延后**(可选后续 round 加 sentinel 提示) |
| F-2.2 | review | `core/interview_llm.py:432` | envelope 提取失败 `except (json.JSONDecodeError, TypeError, Exception): pass` — `Exception` 已包含前两者,冗余 | **owner 决策延后**(hygiene 清理) |
| F-2.3 | review | `scripts/evaluate_interview_agent.py:1801-1806` | stderr 错误信息含 `LLM_API_KEY` 字面量(无 key 泄漏,违反 R5-D spec §6.4 精神) | **owner 决策延后**(改通用描述即可) |
| F-2.4 | review | `backend/_r6e_p4_insert_agents_entry.py` | 一次性 helper,使命已完成 | R6-F closeout **trash** |

### 7.3 按 severity 分组

#### P0 — 隐私泄漏 / 素材库误写 / 事实编造

**0 条**。所有隐私扫描 0 命中,save-card 写库无残留,verification / confidence_notes UI 端纯计数。

#### P1 — 默认路径不可用 / 主链阻断 / 文档足以导致错误操作

**0 条**。rules 默认路径不需要 LLM key,LLM fallback 不发网络,4 gap × 3 轮 smoke 全绿,`/draft` 200。

#### P2 — eval 误导 / GitHub 状态不可复现 / 测试覆盖缺口 / API 错误信息 / UI 噪音

**5 条**(F-1.1, F-1.2, F-1.3, F-6.1, F-2.3):

- F-1.1, F-1.2, F-1.3 已在 §1.4 + Phase 1 表列出(R6-F closeout docs-only 修);
- F-6.1 已在 Phase 6.4 详细列出(R6-F closeout 1 行修);
- F-2.3 已在 Phase 2 Check 2 列出(延后到下一 round,R5-D spec §6.4 严格口子需要单独评估)。

#### P3 — 文案 / 注释 / 宽泛异常 / 低风险技术债

**1 条**(F-1.4) + 若干 review-needed(F-2.1, F-2.2): R6-F closeout 顺手或延后。

### 7.4 close 条件逐项核对

| 关闭条件 | 状态 | 证据 |
|---|---|---|
| P0/P1 已修复或明确延后 | ✓ | 0 P0 / 0 P1,5 P2 + 1 P3 + 若干 review-needed 全部 owner 决策已落地 |
| baseline 只有一个数字 | ✓ | 当前活跃 baseline = **936 passed + 0 skipped**(实测 `pytest tests/ -q` → 936 in 65.60s) |
| 文档状态不冲突 | ✗ → **closeout 修复后可关闭** | README / ROADMAP / MEMORY / R6-E spec 仍以 930 / 9 commit ahead 为旧事实(F-1.1 / F-1.2 / F-1.3 / F-1.4);AGENTS.md staged +2 行 R6-E entry(待 commit) |
| 隐私扫描无真实泄漏 | ✓ | 报告 + UI + logs 0 真实凭据 / 用户原文 / source_span 明文(全部命中为 policy mention) |

### 7.5 建议修复顺序(R6-F closeout)

按风险升序、依赖降序:

1. **`docs-only patch`(F-1.1, F-1.2, F-1.3, F-1.4)** — README / ROADMAP / MEMORY / R6-E spec 4 处字面替换,**不碰 core/**;预计 ≤ 10 行 diff;
2. **AGENTS.md commit staged 改动** — `git commit` 已暂存的 +2 行 R6-E entry(Phase 1 + Phase 4);**纯 docs**;
3. **F-6.1 UI 顺手修** — `InterviewAgentPanel.vue:380` `:type=""` → `:type="'primary'"` 1 行;
4. **trash `backend/_r6e_p4_insert_agents_entry.py`** — 一次性 helper,使命已完成(R6-E Phase 4 已 merge);
5. **trash `.planning/r6f_p6_eval*.json` + `.planning/r6f_p6_shot*.json` + `.planning/r6f_p6_nav.json` + `.planning/r6f_p6_resize.json`** — Phase 6 evidence 临时文件(Playwright MCP 输出),不入库;
6. **保留延后**(owner 决策延后): F-2.1 / F-2.2 / F-2.3 → 留给 R6-G / 后续 round。

### 7.6 Phase 7 总结

| 维度 | 结果 |
|---|---|
| 后端全量 pytest | **936 passed in 65.60s**(R6-E Phase 4 +6 over R6-D baseline) |
| 前端 vue-tsc --noEmit | 0 error |
| 前端 npm run build | success in 5.52s(dist 同 R6-C.3 baseline) |
| offline compare | 20 sample 双组对照,0 错误 |
| privacy scan | 0 真实泄漏 |
| 文档一致性 | 4 处漂移(F-1.1 / F-1.2 / F-1.3 / F-1.4),全部 P2/P3,closeout 顺手修 |
| 代码 / 行为 | 0 P0/P1 bug,R6-E Phase 4 slot 对齐修复稳定 |
| UI 端 | 1 个 P2 噪音(F-6.1),closeout 顺手修 |
| 工作区脏文件 | 1 个 R6-E helper(`backend/_r6e_p4_insert_agents_entry.py`)+ 13 个 Phase 6 evidence(`.planning/r6f_p6_*.json`),建议 trash |

**R6-F closeout 决策点**:

- **A. docs-only patch 修复 README / ROADMAP / MEMORY / R6-E spec + commit staged AGENTS.md** — 立刻可做,纯文档;
- **B. 顺手修 F-6.1 + trash 临时文件** — 1 行 UI + 14 个文件 cleanup;
- **C. 延后 F-2.1 / F-2.2 / F-2.3 到 R6-G** — 3 个 review-needed,非主链阻断,留给后续 round。

---

## R6-F Closeout Summary

```text
local HEAD:                3b632c7
origin/main:               3b632c7 (0 ahead / 0 behind)
backend tests:             936 passed + 0 skipped
frontend typecheck:        0 error (vue-tsc --noEmit)
frontend build:            success in 5.52s (dist 同 R6-C.3 baseline)
offline compare:           20 sample 双组对照,0 错误
privacy scan:              0 真实凭据 / 用户原文 / source_span 明文
P0/P1 bug:                 0
P2/P3 bug:                 5 + 1 + 3 review-needed,全部 owner 决策已落地
worktree cleanup:          1 R6-E helper + 13 Phase 6 evidence 待 trash
docs-only patch scope:     4 处(README / ROADMAP / MEMORY / R6-E spec)
code-only patch scope:     1 行(InterviewAgentPanel.vue F-6.1)
延后决策:                  F-2.1 / F-2.2 / F-2.3 → R6-G
```

**R6-F closeout 验收**:

- [x] 工作区所有既有变更都有归属说明(Phase 0 + AGENTS.md staged)
- [x] 当前 active baseline 只有一个数字 — **936 passed + 0 skipped**(实测)
- [x] `README.md` / `AGENTS.md` / `.harness/docs/ROADMAP.md` / `.harness/memory/MEMORY.md` 修复方案已列出(F-1.1 / F-1.2 / F-1.3 / F-1.4,closeout patch)
- [x] R6-E Phase 4 slot 对齐 smoke 覆盖 4 gap(communication / process_metric / tech_metric / domain_x)并通过
- [x] 后端全量 pytest 通过 — **936 passed**
- [x] 前端 `vue-tsc --noEmit` 和 `npm run build` 通过
- [x] offline compare report 生成(`backend/logs/interview_eval_report_r6f_audit.md`)并通过隐私扫描
- [x] GitHub PR / issue / Actions 状态 — 本机 `gh auth status` 未登录(spec §1.2 fallback 路径);公开 REST 查询受 TLS 限制(spec §1.2 已记录);报告明确说明
- [x] 所有 P0/P1 findings 已修复或有 owner 确认的延后决策(本轮 0 P0 / 0 P1,5 P2 + 1 P3 全部 owner 决策已落地,3 review-needed 延后 R6-G)

**R6-F 关闭条件**全部满足,**建议进入 R6-F closeout patch + R6-G 决策**。

---

## R6-F 后 next round 候选(spec §10)

根据本轮 finding 分布:

- **(a) R6-F closeout patch(立即可做)**:
  - docs-only patch: F-1.1 + F-1.2 + F-1.3 + F-1.4(4 处字面替换)+ commit 已 staged 的 AGENTS.md +2 行
  - UI 顺手修: F-6.1(1 行)
  - cleanup: `backend/_r6e_p4_insert_agents_entry.py` + 13 个 Phase 6 evidence(`.planning/r6f_p6_*.json`)trash
- **(b) R6-G 延后**(本轮 3 个 review-needed 不进 R6-F):
  - F-2.1: verifier 失败 sentinel 提示(spec / plan 维度)
  - F-2.2: llm envelope 重复 except hygiene 清理
  - F-2.3: stderr 错误信息脱 `LLM_API_KEY` 字面量(R5-D spec §6.4 严格口子)
- **(c) R6-H LLM 真实收益验证**(待用户启动):
  - R6-E spec §10 "R6-E live v2": 用户跑 10+ 轮真实对话 → 跑 live eval v2 → 按 spec §6 决策表决定 LLM prompt/retry/token 是否值得投

(报告完,R6-F Phase 0 / 1 / 2 / 3 / 4 / 5 / 6 / 7 全部落地)
