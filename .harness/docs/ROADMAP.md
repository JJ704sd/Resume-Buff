# 简历帮 — 未来规划 ROADMAP

> **可持续更新的项目规划文档**。每个 round 收尾时由 orchestrator 更新:已完成 → 移到顶部"快照";新启动 → 加进对应优先级段。
>
> **历史档案** 见 `.harness/memory/MEMORY.md`(项目里程碑 / 改动记录 / 已知陷阱)。
> **设计文档** 见 `.harness/docs/`(每 round 一份 `roundN-*.md`)。
> **本文件** 只描述未来:目标 + 触发条件 + 工作量估算,具体实施 spec 落 `.harness/docs/roundN-*.md`。

---

## 0. 当前项目快照(2026-06-27 R3-G 收尾)

**已上线能力**(用户视角):
- FastAPI 后端 + Vue 3 前端 + 本地单用户工具
- 6 个 role:tech_metric / product / algorithm / data_annot / test_qa / general
- 5 套简历模板:classic / single_column / two_column / minimal / technical
- JD 加权 score + tier 分组 + 业务阈值 banner(高≥80 / 中 60-79 / 低<60,**R3.5 调优锁死**)
- **borrowed pool + 'AI' surface + PM 维度 surface**(R3.5+ / R3.5+ (b) 修复 false negative + 让 match_score 精确告诉 user 缺什么)
- **R3.5.1 score_thresholds 实跑模式**(`scripts/score_thresholds.py` 不再读 frozen top_score, 实时跑 match_score 出报告, 反映当前实现 + 真实素材库)
- **R3.6 扩库 + 质量清理: 88 份 JD**(v3 86 → R3.6 +10 → R3.6.1 清理 -8 = 88, **A 级 86 / B 级 2**, 无 placeholder 无 C 级, 4 级标签 strong=53 / campus_to_intern=7 / weak=20 / none=8)
- **R3.6.2 baiyun_product label 复核完成**(第三次复核改 '别投', un-skip → **8/8 = 100% 准确率, 0 skipped**)
- **R3-G 外部简历上传 + 简历视角评分**(`POST /api/resume/parse-external` 解析 .docx/.pdf/.txt → `match_score` 增加 `external_resume_text` 参数 → 返回 `resume_perspective` 块 {have_keywords, need_keywords, have_count, need_count} → 前端 `ResumeUploader` drag 组件 + App.vue 评分结果区加 "已有/还缺" 卡片, 扣除素材库能补的避免 false negative)
- JD-driven generation:粘贴 JD 后项目/highlight/skill 按命中数倒序 + 段落命中关键词角标
- LLM 智能改写(无 key 静默降级)
- CI 验证(pre-push hook 自动 pytest + vue-tsc + build)
- **181 个 pytest 全绿 + 0 skipped**(137 R3.6.2 baseline + 30 `test_parse_external` + 14 `test_jd_match_ext`, 全移植自 R3-G worktree `eb7e841` + 当前 main 的 R3.5+ borrowed pool / KEYWORD_GROUPS 适配)

**最近 5 个 commit**:
- `c3b2807` feat(round3-g#3): 前端集成 ResumeUploader + resume_perspective 展示
- `d81c71e` feat(round3#g step2): 实装 _build_resume_perspective + 移植 R3-G 测试 (181 passed)
- `b15dec5` feat(round3#g step1): resume upload 端点 + match_score 透传 external_resume_text
- `2813505` docs(round3.6.2): sync ROADMAP + AGENTS + README to R3.6.2 closeout (137/0 skipped)
- `b254611` chore(round3.6.2): baiyun_product label 第三次复核改 '别投' + un-skip

---

## 1. P1 — 短期可做(下次 round 候选)

### R3.5+ — 修 match_score 漏匹配 bug ✅ 完成 (2026-06-27, commit `2889dd9`)
- **问题**:`baiyun_2026_product` / `baiyun_2026_qa` 触发 score=0,本应命中 Python/AI/LLM 等关键词
- **实际根因**(比推测更复杂,2 个独立 bug):
  1. `_build_candidate_pool` 只查 role_skill_keys 对应 items,跨 role 经验不计入池 → baiyun_qa 误判
  2. `KEYWORD_GROUPS` 缺 "AI" surface,中英 JD 里高频 "AI" 字面识别不到 → baiyun_product 误判(parse_jd 命中 0 关键词,score 走全 unknown 兜底)
- **修法**:
  1. `_build_candidate_pool` 加 `include_borrowed=True` 参数(默认开):池 = role 范围 + 全素材库扫描
  2. `KEYWORD_GROUPS['skills']` 加 `("AI", "LLM", 0.5)`:跟 "大模型"/"LLM" 语义等价
  3. 抽出 `_scan_items_into_pool` 工具函数复用扫描逻辑
- **效果**:8 份 eval 实跑准确率 **7/8 = 88%**(R3.5 时 6/8 = 75%,+13pp);baiyun_qa 修后 score=100 ✓,baiyun_product 修后 score=100 但 label='建议补充' 待 user 复核(原 label 基于 score=0 反推)
- **3 个回归测试**:`tests/test_jd_parser.py::TestMatchScoreBugfixR35Plus` 锁死 baiyun_qa/baiyun_product 修复 + include_borrowed=False 旧行为

### R3.5+ (b) — PM 维度 surface ✅ 完成 (2026-06-27, commit `ed57e25`)
- **上下文**:R3.5+ 修后 baiyun_product score=100 vs label='建议补充' (期望 '中') 仍 gap;user 选 (b) 方案: 加 PM 维度 surface, 让 match_score 精确告诉 user 缺什么
- **修法**:`KEYWORD_GROUPS['domains']` 加 4 个 PM 维度 surface (0.5 加分): 物流 / 工业工程 / 原型 / 流程图
- **效果**:baiyun_2026_product 实跑: score=33, matched=['LLM'], missing=['原型', '工业工程', '流程图', '物流'];suggestions 精确给"补 PM 维度素材"指引 (提到物流/工业工程/原型)
- **8 份 eval live 准确率保持 7/8 = 88%**;baiyun_product 仍 skip (score='低' vs label='中' 仍 gap, 根因是 user 素材库实际缺 PM 经验, 不是算法问题)
- **3 个回归测试**:`tests/test_jd_parser.py::TestMatchScorePMDimensions` 锁死 baiyun_product missing 含 PM 4 项 + suggestions 提到 PM 关键词 + KEYWORD_GROUPS 字典级断言

### R3.5.1 — score_thresholds.py 改实跑 ✅ 完成 (2026-06-27, commit `44bd370`)
- **背景**:R3.5 写的 score_thresholds.py 读 jd_samples.json 里的 frozen top_score (R3.5 时 AI 推断写死的 score),R3.5+ / R3.5+ (b) 修 match_score 后, frozen top_score 跟实跑结果不一致, 报告失去参考价值
- **修法**:`scripts/score_thresholds.py` 移除 `s['top_score']` 读取, 改跑 `match_score(s['text'], s['role_id_hint'], materials)` 拿 score / coverage;role 沿用 role_id_hint (user 标定的期望 role), 不再 6 role 取最高 (简化);sys.path 注入 backend/ 让 scripts/ 下脚本能 import core.* (跟 match_golden_targets.py 同样处理);报告 markdown 顶部加 "R3.5.1 (实跑模式)" 标识 + "R3.5.1 vs R3.5 差异说明" 段
- **效果**:**8 份 eval 实跑准确率 7/8 = 88%** (R3.5 frozen 6/8 = 75%, +13pp);提升核心是 baiyun_2026_qa 从 frozen 0 → 实跑 100 (修后 '高' 跟 label '推荐投' 一致);报告含详细 coverage (skills/tools/domains 三维), 比 R3.5 报告信息量更丰富;baiyun_2026_product 仍 fail (实跑 33 '低' vs label '中')
- **5 个回归测试**:`tests/test_score_thresholds.py::TestScoreThresholdsLive` 锁死 (含 `test_live_mode_ignores_frozen_top_score` 篡改 frozen 字段后实跑分数不变, 核心防回潮)
- **未修(留给 user)**:baiyun_2026_product 严格阈值校验留待 user 补 PM 素材 (or 改 label='低') 后再 un-skip;frozen top_score / top_role / top_coverage 字段保留在 jd_samples.json 作为 R3.5 时点历史 snapshot

### R3-G — 外部简历上传 + 简历视角评分 ✅ 完成 (2026-06-27, commits `b15dec5` + `d81c71e` + `c3b2807`)
- **背景**:`feat/r3g-resume-upload` 分支保留 1467 行 MVP(外部简历实时读取 + JD 评分联动),worktree `D:/简历帮/r3g-resume-upload` HEAD `eb7e841`;用户 2026-06-26 选完 scope 后主动 cancel,R3-G cancelled 但 MVP commit 在分支保留
- **实施路径**(不走 git cherry-pick 改"功能移植"):R3-G base 是 R3-I 之前的旧 base,eb7e841 自身只 +1467/-5(worker 提前做了"剥离"工作),用 `git show <commit>:<file>` 提取纯新增文件 + 手动合并修改文件(避开 ~30 文件冲突)
- **实施成果**(3 commit 顺序落地):
  1. `b15dec5` Step 1: 纯新增 `backend/core/resume_parser.py` (250 行 docx/pdf/txt 解析) + `frontend/src/components/ResumeUploader.vue` (227 行 el-upload drag) + `backend/api/resume.py` 加 `POST /parse-external` + `backend/api/jd.py` MatchRequest 加 `external_resume_text` 字段 + `backend/core/jd_parser.py` `match_score` 加 `external_resume_text` 关键字参数(占位 `_build_resume_perspective`)
  2. `d81c71e` Step 2: 实装 `_build_resume_perspective` 核心逻辑(归一化简历文本 + 扫 required keywords 的 surface 命中 → have, 否则 need_candidate, need 扣掉 match_score 的 borrowed pool 避免 false negative) + 移植 44 个 R3-G 测试(`test_parse_external.py` 30 + `test_jd_match_ext.py` 14)
  3. `c3b2807` Step 3: 前端集成 `api/index.ts` 加 `ParsedResume` / `ResumePerspective` 类型 + `resumeApi.parseExternal(file)` + `jdApi.match` 第 3 参 + `App.vue` 加 `ResumeUploader` + `externalResumeText` ref + 评分结果区加 have/need 卡片
- **实施坑**(已写进 MEMORY.md):
  1. PowerShell `>` 重定向 git show 文件会写 UTF-16 with BOM → pytest "source code string cannot contain null bytes", 改用 `python -c "subprocess.check_output + open('wb')"`
  2. PowerShell `git commit -m` body 里 `**xx**:` 触发 pathspec 吞字段, 改用 `git commit -F <tmp_file>` 传多行 message
  3. `parse_resume_bytes` 返回 dict 不是 list, API endpoint 必须提取 `parsed["paragraphs"]` 不能直接传整个 dict
  4. UTF-16 → UTF-8 转码:6959 个 null bytes 让 pytest 报 "source code string cannot contain null bytes"
- **效果**:**181 passed, 0 skipped**;端到端冒烟: 上传简历 (.txt 218 字符/10 段) → score=95 / recommendation='高' / have=10 关键词 / need=0 (简历覆盖所有 JD 要求);不传 / 空字符串 → `resume_perspective: None` (前端 v-if 隐藏)

---

## 2. P2 — 中期(按用户场景触发,不主动开)

### R3-K — 求职信(规则版)
- **背景**:⏸️ 2026-06-26 暂缓,用户认为求职信在国内使用频率低
- **范围**:基于素材库 + role + JD 自动生成 200-300 字中文求职信,支持 5 个 role 模板(每个 role 一段 boilerplate + JD 关键词驱动改写)
- **触发条件**:你说"我要写求职信"
- **依赖**:LLM 改写链路已就绪(无 key 静默降级)
- **工作量**:中(模板生成 ~300 行 + 前端单页 ~150 行)
- **价值**:投递最后一公里自动化

### R3-M — 简历导出多格式
- **背景**:待启动,目前只支持 docx
- **范围**:docx → pdf / md / html 三种格式输出
- **触发条件**:你要投递支持 pdf 的平台 / 要把简历分享到 markdown 仓库
- **依赖**:`pymupdf` 已装(可做 pdf);markdown 直接拼;html 用 docx-to-html 转换库或自写
- **工作量**:中(pdf 渲染 ~150 行 + md 模板 ~50 行 + html 转换 ~100 行 + 前端 radio 切换 ~30 行)
- **价值**:跨平台投递

### R3.5.1 — 扩 ground truth 样本 + 重跑阈值
- **背景**:R3.5 决策"10 份够用",但 label 分布有偏(0 份"别投")
- **范围**:补 10-20 份真实 JD + 各类 role 覆盖 + 确保 label 分布均衡(至少 2-3 份"别投")
- **触发条件**:R3.5+ match_score bug 修完后,想跑新一轮阈值调优
- **依赖**:R3.5+ 完成(match_score 必须先准)
- **工作量**:小(用户手工抄 ~20 份 + 跑 label_samples.py + 复核)
- **价值**:阈值调优可信度提升

---

## 3. P3 — 长期(按用户偏好暂停,不主动开)

### 云端部署 / 多端同步
- **背景**:本地单用户工具,AGENTS.md 已明确"不要加账号系统,不要暴露公网"
- **范围**:账号系统 + 数据库 + API 部署 + 鉴权(可能要迁 sqlite → postgres)+ CI/CD
- **触发条件**:你换电脑 / 多设备工作
- **工作量**:大(2-3 周,需评估云服务选型 + 隐私合规)
- **价值**:跨设备工作 / 远程访问

### GUI 实施任务
- **背景**:用户偏好"GUI 实施任务默认暂停"(2026-06-23 CT 重建后确定)
- **范围**:任何前端界面改动
- **触发条件**:你说"启动"才开(设计文档已够用时尤其如此)
- **价值**:避免无明确需求时的 UI 投资浪费

---

## 4. 维护类任务(随时可做)

### 定期清理
- `backend/output/` 真实 PII 产物 docx/json(每次跑完生成记得用 `mavis-trash` 清)— 2026-06-26 A 任务已清理过 6 份
- `scripts/_*.py` 临时脚本(跑完诊断即删)— 当前未发现

### 文档同步
- README.md 顶部"当前能力"表 + AGENTS.md 测试数 — 每 round commit 时由 developer 同步,orchestrator 收尾核对
- MEMORY.md 项目里程碑 / 待办表 / 改动记录 — 每 round 收尾由 orchestrator 同步

### 测试覆盖
- 每次新行为必须加 pytest(核心逻辑 / 边界 / 集成,thin wrapper 不写)— AGENTS.md 约定
- 每次 bugfix 必须加回归测试(覆盖每个 score 区间 / 死代码删除点)— AGENTS.md 约定
- 每轮独立验证 + 清理冗余测试文件 — 用户偏好,2026-06-23

---

## 5. 决策原则(用户偏好 + 项目约定)

按优先级递减:
1. **不要加账号系统 / 鉴权 / 公网部署**(本地单用户,AGENTS.md)
2. **不主动 git push**(commit 由用户决定何时推,AGENTS.md)
3. **GUI 实施任务默认暂停**(设计文档够用就停,2026-06-23)
4. **每轮独立验证 + 清理冗余测试**(用户偏好,2026-06-23)
5. **bugfix 必须加回归测试**(AGENTS.md)
6. **commit message 中文 + multi `-m` 别用字面 \n**(PowerShell 5.1 坑)
7. **新行为必须有 pytest 覆盖**(AGENTS.md)

---

## 6. 文档维护规则

**何时更新本文件**:
- 启动新 round → 在对应优先级段加 entry
- 完成 round → 把 entry 移到顶部"快照"(只留 commit hash + 1 行说明)
- 用户取消 / 暂缓 round → 把 entry 标 ⏸️ 移到对应"暂缓"段
- 用户说"暂停某任务" → 移到 P3 段

**更新方式**:orchestrator(本次会话主代理)在 round 收尾时改本文件 + MEMORY.md 同步指向本文件。

**历史档案**:已完成的 round 完整描述见 `.harness/memory/MEMORY.md` 项目里程碑段 + commit 历史。

---

## 7. 项目快速参考

| 类别 | 路径 |
|---|---|
| 后端入口 | `backend/main.py` |
| 核心域 | `backend/core/generator.py` + `backend/core/jd_parser.py` + `backend/core/llm_rewriter.py` + `backend/core/jd_ranker.py` |
| API | `backend/api/resume.py` + `backend/api/jd.py` |
| 测试 | `backend/tests/` 124 pytest |
| 前端入口 | `frontend/src/App.vue` |
| 设计文档 | `.harness/docs/` |
| 项目记忆 | `.harness/memory/MEMORY.md` |
| 本地隐私数据 | `简历帮知识库/` (`.gitignore`,不进库) |
| JD 库 | `AI岗位JD库_v4_intern.json` + 4 份报告 md |
| 扩库 / 打标 / 阈值脚本 | `scripts/build_v4.py` + `scripts/score_intern_match.py` + `scripts/label_samples.py` + `scripts/score_thresholds.py` + `scripts/match_golden_targets.py` |

---

_最后更新:2026-06-26 R3.5 收尾,由 orchestrator 创建_