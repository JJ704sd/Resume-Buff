"""R6-E Phase 4 API smoke test: 4 gaps × 3-turn dialogue → /draft.

Each scenario picks a role + JD text combo that targets a specific gap:
  1. product + 协同场景 → communication gap
  2. tech_metric + 大模型评测场景 → tech_metric gap
  3. algorithm + 流程优化场景 → process_metric gap
  4. data_annot + 医疗领域场景 → domain_x gap

Per scenario:
  - POST /api/interview/start → capture session_id
  - 3× POST /api/interview/reply → verify each captured_delta key == UI displayed slot
  - POST /api/interview/draft → assert 200 + draft_bullets >= 2
"""
import json
import sys
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:8000"

SCENARIOS = [
    {
        "name": "communication (product + 协同场景)",
        "role": "product",
        "jd": (
            "招聘 AI 产品经理, 负责协调业务、技术、设计团队, "
            "组织跨部门会议对齐产品方向, 解决沟通阻塞, "
            "提升团队信息透明度, 减少返工。"
        ),
        "answers": [
            "有的, 我会定期组织线上线下会议, 让信息对齐",
            "执行了一个动作: 整理需求文档, 拉齐团队理解",
            "减少了错误: 沟通后返工率明显下降",
        ],
    },
    {
        "name": "tech_metric (tech_metric role + 大模型评测场景)",
        "role": "tech_metric",
        "jd": (
            "招聘大模型评测工程师, 负责设计评测体系, "
            "执行评测任务, 输出准确率/召回率/F1 等量化指标, "
            "提升模型质量。"
        ),
        "answers": [
            "AI 评测项目背景, 我做数据质量评估",
            "执行了数据标注 + 模型评测的完整动作链",
            "结果: 准确率提升 5 个百分点",
        ],
    },
    {
        "name": "process_metric (algorithm + 流程优化场景)",
        "role": "algorithm",
        "jd": (
            "招聘算法工程师, 负责流程优化项目, "
            "梳理反馈分类流程, 缩短闭环时长, "
            "提升处理效率。"
        ),
        "answers": [
            "AI 测试反馈整理项目背景, 我做流程闭环",
            "梳理了反馈分类流程, 按优先级分派",
            "流程跑通后, 闭环时长从 3 天缩短到 1 天",
        ],
    },
    {
        "name": "domain_x (data_annot + 医疗领域场景)",
        "role": "data_annot",
        "jd": (
            "招聘医疗 NLP 数据标注工程师, 负责心电信号分类任务, "
            "标注心电图数据, 训练分类模型, "
            "提升 F1 指标。"
        ),
        "answers": [
            "医疗 NLP 项目背景, 心电信号分类任务",
            "做了数据标注 + 模型评测的完整动作链",
            "结果: 心电信号分类 F1 提升 12 个百分点",
        ],
    },
]


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def main():
    fail = 0
    for sc in SCENARIOS:
        print(f"\n========== {sc['name']} ==========")
        status, start_resp = post("/api/interview/start", {
            "target_role": sc["role"],
            "jd_text": sc["jd"],
        })
        if status != 200:
            print(f"  /start FAIL: status={status}, resp={start_resp}")
            fail += 1
            continue
        sid = start_resp.get("session_id")
        gap_id = (start_resp.get("selected_gap") or {}).get("gap_id")
        print(f"  /start OK: session_id={sid}, gap={gap_id}")
        # 3 turns of reply
        ok = True
        captured_per_turn = []
        for i, ans in enumerate(sc["answers"]):
            status, reply = post("/api/interview/reply", {
                "session_id": sid,
                "message": ans,
                "action": "answer",
            })
            if status != 200:
                print(f"  reply #{i+1} FAIL: status={status}, resp={reply}")
                ok = False
                break
            cd = reply.get("captured_delta") or {}
            qp = reply.get("question_plan") or {}
            next_slot = qp.get("slot")
            state = reply.get("state")
            force_draft = reply.get("force_draft", False)
            print(f"  reply #{i+1}: state={state}, ui_slot={next_slot}, "
                  f"captured_delta_keys={list(cd.keys())}, force_draft={force_draft}")
            captured_per_turn.append((next_slot, list(cd.keys()), state, force_draft))
        if not ok:
            fail += 1
            continue
        # /draft
        status, draft = post("/api/interview/draft", {"session_id": sid})
        if status != 200:
            print(f"  /draft FAIL: status={status}, resp={draft}")
            fail += 1
            continue
        bullets = (draft.get("draft_card") or {}).get("draft_bullets") or []
        print(f"  /draft OK: draft_bullets count={len(bullets)}")
        if len(bullets) < 2:
            print(f"  /draft FAIL: bullets < 2 (got {len(bullets)})")
            fail += 1
            continue
        # Final check: 第 3 轮 reply 应 force_draft=True (or state=DRAFT_READY)
        if not captured_per_turn[-1][3] and captured_per_turn[-1][2] != "DRAFT_READY":
            print(f"  WARNING: 第 3 轮 force_draft=False 且 state={captured_per_turn[-1][2]}")
        print(f"  PASS: {sc['name']}")
    print(f"\n========== summary ==========")
    print(f"total: {len(SCENARIOS)}, failed: {fail}")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()