# 简历帮 (JianLiBang)

> 个人简历助手 — 一份素材库,一键生成多份针对性简历。

## 这是什么 / 不是什么

### ✅ 简历帮**做**的事
- 把分散在 10+ 份原简历里的**事实**去重合并,沉淀为结构化**素材库**(`backend/data/materials.json`)
- 根据**目标岗位方向**,从素材库挑选 facts + 调整措辞,生成定制版 `.docx` 简历
- 生成前**强制预览**(人工确认),人 review 每个模块内容后再下载,避免投错

### ❌ 简历帮**不做**的事
- ❌ **不**自动投递(不会去 BOSS / 拉勾 / 牛客上代投)
- ❌ **不**追踪 HR 进度、面试状态
- ❌ **不**做模拟面试、八股训练
- ❌ **不**爬取招聘网站,不联网抓 JD(用户粘贴 JD 进来即可)
- ❌ **不**做账号/多用户系统(本地单用户工具)
- ❌ **不**替代人做最终决策(预览后必须人点确认才下载)

> 边界画在「素材库管理 + 简历文件生成」,再往外就是越权。

---

## Round 1 当前能力(2026-06-24)

| 功能 | 状态 |
|---|---|
| 素材库(4 项目 + 7 技能组 + 3 荣誉 + 1 证书) | ✅ |
| 大模型技术度量方向简历生成 | ✅ |
| 其他 5 个方向(产品/算法/测试/标注/通用) | ⏸️ Round 2 |
| 生成预览(按模块) | ✅ |
| 本地日志 `backend/logs/generation.log` | ✅ |
| JD 解析 / 匹配度评分 | ⏸️ Round 2 |
| LLM 智能改写项目描述 | ⏸️ Round 2 |

---

## 8 要素 × Round 1 落地表

| 要素 | 落地方式 |
|---|---|
| **1. 任务边界** | 本 README 顶部明确"做/不做"清单;`ENABLED_ROLES` 写死在代码里,只暴露 `tech_metric` |
| **2. 上下文** | Round 1 只用"素材库 + role 模板"两样;生成历史/用户偏好留 Round 2 |
| **3. 工具** | python-docx(写 docx) + pymupdf(读 docx/pdf) + FastAPI + Vue 3 + Element Plus |
| **4. 权限** | 本地单用户;素材库和输出目录按 user 权限隔离(不需要账号系统) |
| **5. 人工确认** | 强制两段式:`POST /preview` → 渲染 → `POST /generate`;无预览不能直接生成 |
| **6. 评测** | Round 1 仅做"事实覆盖自检"(每个 role 必须包含腾讯/理邦项目,作为 sanity check) |
| **7. 监测** | `backend/logs/generation.log` 记录每次生成(时间/role/文件/大小/状态) |
| **8. 监控** | FastAPI 默认 exception handler;前端 `ElMessage.error` 捕获 |

---

## 启动方式

### 后端
```bash
cd backend
pip install -r requirements.txt   # 首次
python main.py                    # http://127.0.0.1:8000
```

### 前端
```bash
cd frontend
npm install                       # 首次
npm run dev                       # http://127.0.0.1:5173
```

### 端到端
1. 启后端 → 启前端 → 浏览器开 `http://127.0.0.1:5173`
2. 选岗位(默认 大模型技术度量) → 点「预览」
3. Review 各模块内容 → 点「确认下载」→ docx 落盘 `backend/output/`

---

## 目录结构

```
简历帮/
├── backend/
│   ├── main.py               # FastAPI 入口
│   ├── api/
│   │   ├── materials.py      # 素材库 CRUD
│   │   └── resume.py         # 简历预览/生成
│   ├── core/
│   │   ├── generator.py      # sections 构造 + docx 渲染
│   │   └── logger.py         # 本地日志
│   ├── data/
│   │   └── materials.json    # 素材库(单人唯一真源)
│   ├── logs/
│   │   └── generation.log    # 生成历史(自动)
│   ├── output/               # 生成的 docx(自动)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.vue           # 单页主界面
│   │   ├── api/index.ts      # axios 封装
│   │   └── main.ts
│   ├── package.json
│   └── vite.config.ts        # /api 代理 → :8000
└── README.md
```

---

## 后续规划

- **Round 2**: 启用 5 个 role + JD 解析(关键词/匹配度) + LLM 改写项目描述
- **Round 3**: 求职信/自我介绍生成 + 模板库 + 历史偏好
- **未来可选**: 多端同步、云端部署(不主动做,看用户需求)
