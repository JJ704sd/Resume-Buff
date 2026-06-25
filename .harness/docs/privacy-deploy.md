# 简历帮 — 隐私与部署边界

> 这是项目的**硬约束**。任何 agent 改动前都必须先读这份。

## 设计定位

**本地单用户工具** — 只在 `127.0.0.1` 上跑，不上云、不公开、不协作。

边界画在「素材库管理 + 简历文件生成」，**再往外就是越权**。

## 不做的事（hard NO）

- ❌ 自动投递（不会去 BOSS / 拉勾 / 牛客代投）
- ❌ HR 进度追踪 / 面试状态管理
- ❌ 模拟面试 / 八股训练
- ❌ 爬取招聘网站 / 联网抓 JD（用户粘贴 JD 进来即可）
- ❌ 账号系统 / 多用户
- ❌ 替代人做最终决策（预览后必须人点确认才下载）

## 隐私硬约束

### 个人信息（PII）— **绝不进 git**

下列字段一律**脱敏**或**留空**：

- 姓名 / 手机 / 邮箱 / 学校 / 公司
- 真实项目经历里的客户名 / 内部代号
- 真实住址 / 身份证 / 学号

### 数据流向

```
真实素材（本地）              公开仓库版（脱敏）
─────────────────    ──────────────────────────
私人简历 docx     →    materials.json (placeholder)
                   →    src/App.vue 不 hardcode 姓名
                   →    README.md 用「示例同学」
                   →    generator.py 注释不写 PII
真实数据备份：     _private_backup.json (.gitignore)
```

### clone 后如何切到真实数据

```bash
cp backend/data/_private_backup.json backend/data/materials.json
# 然后编辑 materials.json 填入真实内容
```

`_private_backup.json` 在 `.gitignore` 内，**不会**被 push。

### 代码内禁止出现的写法

- ❌ `defaultName: '张三'` — 任何 hardcode 真实姓名
- ❌ `console.log(request.body)` — 日志打整个请求（可能含 PII）
- ❌ 报错信息暴露完整堆栈到前端
- ❌ commit message 提及真实客户 / 项目代号

## 部署边界

### 当前允许

- ✅ `python main.py` 本地起后端
- ✅ `npm run dev` 本地起前端
- ✅ `npm run build` 打包 `dist/`（本地预览用）

### 当前**不允许**

- ❌ 后端监听 `0.0.0.0` 或非 `127.0.0.1`
- ❌ CORS 放开 `*`（当前只允许 `localhost:5173`）
- ❌ 部署到任何云平台 / VPS / 内网穿透
- ❌ 用 ngrok / frp / cloudflared 等暴露本地端口
- ❌ 把 `materials.json` 真实版 commit 到任何仓库

### 何时考虑放开（**用户明确启动后**）

- Round 4+：多端同步 / 云端部署 — **需要重新设计鉴权 + 数据隔离**
- 多人协作：需要账号系统 + per-user 素材库 + 权限模型

> **默认假设：永远不放开**。放开前必须经过用户明确同意。

## 安全审计清单（每 round 验证）

- [ ] `materials.json` 是脱敏版（用 `git diff` 看是否有真实姓名）
- [ ] 没有新增 hardcode PII 的代码 / 配置 / 注释
- [ ] `.gitignore` 仍包含 `_private_backup.json` / `output/` / `logs/`
- [ ] `git log` 检查最近 commit 没意外 commit 真实数据
- [ ] 后端监听地址仍是 `127.0.0.1`
- [ ] CORS origins 仍是 `localhost:5173` / `127.0.0.1:5173`

## 泄密应急

如果怀疑不小心 commit 了 PII：

1. **立即**告诉用户（不要等下一个 round）
2. 用 `git filter-branch` 或 `git filter-repo` 从历史里清除
3. force-push 到远端（**这是允许的紧急操作**）
4. 通知用户更换被泄露的密码 / 邮箱
5. 评估是否需要 rotate 相关凭证