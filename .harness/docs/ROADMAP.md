# 简历帮 — 未来规划 ROADMAP

> **可持续更新的项目规划文档**。每个 round 收尾时由 orchestrator 更新:已完成 → 移到顶部"快照";新启动 → 加进对应优先级段。
>
> **历史档案** 见 `.harness/memory/MEMORY.md`(项目里程碑 / 改动记录 / 已知陷阱)。
> **设计文档** 见 `.harness/docs/`(每 round 一份 `roundN-*.md`)。
> **本文件** 只描述未来:目标 + 触发条件 + 工作量估算,具体实施 spec 落 `.harness/docs/roundN-*.md`。

---

## 0. 当前项目快照(2026-06-26 R3.5 收尾)

**已上线能力**(用户视角):
- FastAPI 后端 + Vue 3 前端 + 本地单用户工具
- 6 个 role:tech_metric / product / algorithm / data_annot / test_qa / general
- 5 套简历模板:classic / single_column / two_column / minimal / technical
- JD 加权 score + tier 分组 + 业务阈值 banner(高≥80 / 中 60-79 / 低<60,**R3.5 调优锁死**)
- JD-driven generation:粘贴 JD 后项目/highlight/skill 按命中数倒序 + 段落命中关键词角标
- LLM 智能改写(无 key 静默降级)
- CI 验证(pre-push hook 自动 pytest + vue-tsc + build)
- **124 个 pytest 全绿**(113 baseline + 11 R3.5 threshold_tuning),2 skipped(已知 match_score bug 待 R3.5+)

**最近 4 个 commit**:
- `722b599` MEMORY 同步 R3.5 idempotent fix
- `1bac68e` fix label_samples.py idempotent + --force flag
- `24dfcc5` R3.5 阈值调优(80/60 锁死 + 11 回归测试)
- `273df33` R3.5 样本入库(4 个百运网)

---

## 1. P1 — 短期可做(下次 round 候选)

### R3.5+ — 修 match_score 漏匹配 bug
- **问题**:`baiyun_2026_product` / `baiyun_2026_qa` 触发 score=0,本应命中 Python/AI/LLM 等关键词
- **推测根因**:`match_score` 只查 `KEYWORD_GROUPS`(用户素材里的 group),没查 raw text;JD 文本里关键词不在用户素材分组里 → 不命中
- **修法**(待定):加 raw text fallback 查全 KEYWORD_GROUPS 子集;2 个回归测试(baiyun_product / baiyun_qa 应得非零分)
- **触发条件**:你想看到更多 JD 真实命中情况 / 想跑 R3.5.1 重新调阈值
- **依赖**:无
- **工作量**:小(~50 行代码 + 2 测试)
- **价值**:false negative 减少,后续阈值调优更可信

### R3-G — 重启 cherry-pick
- **背景**:`feat/r3g-resume-upload` 分支保留 1467 行 MVP(外部简历实时读取 + JD 评分联动),worktree `D:/简历帮/r3g-resume-upload` HEAD `eb7e841`;用户 2026-06-26 选完 scope 后主动 cancel,R3-G cancelled 但 MVP commit 在分支保留
- **重启工作**:cherry-pick `eb7e841` 到 main + 集成测试(简历解析不破 generator)+ UI 适配(上传简历 → 跑 match_score → 给建议)
- **触发条件**:你想做"上传简历自动打分"功能(投递前最后一道检查)
- **依赖**:无前置(分支已就绪)
- **工作量**:中(cherry-pick 可能冲突 ~30 文件,集成测试 ~200 行)
- **价值**:简历→JD 一站式,减少"投错简历"风险

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