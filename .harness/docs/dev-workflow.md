# 简历帮 — 开发流程

> 每个 round 一组关联改动。本文档定义从需求到 commit 的标准节奏。

## Round 编号约定

`round<大版本>#<子任务>`，如：

- `round1`：MVP（已完成）
- `round2#1`：启用全部 6 个角色（已完成，commit `14fc0eb`）
- `round2#2`：JD 解析 / 匹配度评分（待启动）
- `round2#3`：LLM 智能改写项目描述（待启动）
- `round3`：求职信 / 模板库 / 历史偏好（远期）

## 单 round 标准流程

```
1. Plan        (harness)
   └─ 子任务清单 + 验收标准
2. Design      (harness / developer 按需)
   └─ 落到 .mavis/plans/round<N>.yaml 或 .harness/docs/
3. Implement   (developer)
   └─ 改代码 + 自测
4. Verify      (tester)
   └─ 后端冒烟 + 前端类型/构建 + 清理冗余测试
5. Document    (developer 或 harness)
   └─ 同步 README "当前能力" 表 + AGENTS.md 边界变更
6. Commit      (developer)
   └─ 一个 round 一个 commit（不要混 commit）
7. Push        (用户确认后)
```

## 验证清单（tester 必跑）

### 后端冒烟

```bash
cd backend
pip install -r requirements.txt   # 首次 / 依赖变更后
python main.py &                  # 后台启动
sleep 2
curl http://127.0.0.1:8000/api/health   # 应返回 {"status":"ok"}
# round 涉及的 API：选 role → preview → generate
curl -X POST http://127.0.0.1:8000/api/resume/preview \
     -H 'Content-Type: application/json' \
     -d '{"target_role":"tech_metric"}'
# 检查 backend/output/ 里有生成的 .docx 且 size > 0
kill %1   # 停后端
```

### 前端

```bash
cd frontend
npm install                       # 首次 / 依赖变更后
npx vue-tsc --noEmit              # 类型检查，必须 0 error
npm run build                     # 构建，必须成功
# (可选) npm run dev 起 dev server，手测关键路径
```

### 卫生检查

```bash
git status                        # 不应有未跟踪的临时脚本 / 个人备份
git diff --stat                   # 改动范围与本轮目标对齐
# 检查 .gitignore 包含：
#   backend/output/   backend/logs/   backend/data/_private_backup.json
#   node_modules/   dist/   *.tsbuildinfo
```

## 冗余测试清理（tester 关键职责）

每轮结束前，审视本轮新增的每个测试文件，按价值判定：

| 类别 | 处理 |
|---|---|
| 测 thin wrapper（包了一层函数调用） | ❌ 删 |
| 测 URL 字符串字面量 / 路由 path | ❌ 删 |
| 测 mock 自指（mock 自己 → 测 mock） | ❌ 删 |
| 测核心逻辑（fallback / 验证 / 边界 / 集成） | ✅ 留 |
| 测非关键路径 / 与其他文件 100% 重叠 | ❌ 删 |

清理后**必须重跑构建 / 测试**确认仍绿，再单独提交：

```bash
git add -A
git commit -m "chore(<scope>): prune redundant test files"
```

## Commit 规范

- conventional commits：`feat:` / `fix:` / `docs:` / `refactor:` / `chore:` / `test:`
- 标注 round：`feat(round2#2): JD 关键词解析`
- 范围限定：message 描述改动**为什么**，不只是**改了什么**
- 一个 commit 只做一件事（不要把 refactor 混进 feature）

## 分支策略

- `main` — 始终可运行；每个 round commit 后 fast-forward
- `feat/<scope>` — 特性分支（如 `feat/round2-jd`）
- `fix/<scope>` — 修复分支
- `chore/<scope>` — 杂项（依赖升级、清理等）

**永远不要直接 push 到 `main`**，一律 PR。

## 失败 / 阻塞流程

1. tester 验证失败 → 回报 developer（带命令 + 报错前 20 行）
2. developer 同一问题改 2 次还没过 → 回报 harness
3. harness 判断是阻塞 / 改方向 / 暂停，等用户确认

## 启动一个 round 的最小 prompt（给 orchestrator 用）

```
启动 round <N>：
- 目标：<一句话>
- 子任务：<列表>
- 验收：<可验证的标准>
- 依赖约束：<材料 / 角色 / 隐私>
- 不要做：<越界事项>
```

把这个 prompt 派给 developer 即可。tester 会在 developer 回报后被自动调度。