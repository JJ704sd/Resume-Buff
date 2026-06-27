"""R3.5.1: 锁死 score_thresholds.py 必须实跑 match_score, 不读 frozen top_score。

防回潮核心思路:
  1. 跑 score_thresholds.main() 拿到 details 列表 (含每份 eval sample 的实跑 score)
  2. 临时篡改 jd_samples.json 的 top_score 字段 (改成 999, 跟实跑结果不一致)
  3. 再跑一次, 断言 details 里的 score 不受篡改影响
  → 如果未来有人把 score_thresholds.py 改回读 s["top_score"], 这个测试会 fail

附加断言:
  - 脚本报告准确率 >= R3.5 基线 6/8 (实际 R3.5.1 是 7/8 = 88%)
  - 脚本输出含 "R3.5.1" 标识 (防有人把它改回 R3.5 标题)
  - 报告 markdown 写入成功 + 顶部 "实跑模式" 标注
"""
import json
import sys
from pathlib import Path

# 把 scripts/ 加到 sys.path, 这样可以 import score_thresholds
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import score_thresholds  # noqa: E402
from core.jd_parser import match_score  # noqa: E402
from core.generator import load_materials  # noqa: E402


SAMPLES_PATH = Path(r"D:/简历帮/简历帮知识库/jd_samples.json")
REPORT_PATH = Path(r"D:/简历帮/AI岗位JD库_v4_intern_阈值调优报告.md")


def _run_score_thresholds_and_capture(capsys):
    """跑 score_thresholds.main(), 返回 (details 列表, 输出文本, 报告 markdown)。"""
    score_thresholds.main()
    out = capsys.readouterr().out
    report = REPORT_PATH.read_text(encoding="utf-8")
    # 从输出文本提取 details 列表
    # main() 里 details 是局部变量, 这里重新跑一次拿
    # 简化: 从 report markdown 表格解析 (更稳)
    details = []
    for line in report.splitlines():
        if line.startswith("| ") and "score=" not in line and "---" not in line and "id" not in line:
            # 形如: | baiyun_2026_algorithm | algorithm | 推荐投 | 86 | 高 | ✅ | ... |
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 6:
                sid = parts[1]
                # 只取 8 份 eval 样本的 id
                if sid and not sid.startswith("true") and not sid.startswith("---"):
                    try:
                        score = int(parts[4])
                        details.append({"id": sid, "score": score})
                    except (ValueError, IndexError):
                        pass
    return details, out, report


class TestScoreThresholdsLive:
    """R3.5.1 实跑模式锁死测试。"""

    def test_main_runs_without_error(self, capsys):
        """score_thresholds.main() 必须能跑通 (无 import / runtime 错)。"""
        score_thresholds.main()
        out = capsys.readouterr().out
        assert "Confusion Matrix" in out
        assert "准确率" in out

    def test_output_marks_live_mode(self, capsys):
        """输出必须含 R3.5.1 标识 + 实跑模式说明。"""
        score_thresholds.main()
        out = capsys.readouterr().out
        assert "R3.5.1" in out, f"输出缺 R3.5.1 标识: {out[:200]}"
        assert "实跑模式" in out, f"输出缺'实跑模式'说明: {out[:200]}"

    def test_accuracy_meets_baseline(self, capsys):
        """实跑准确率必须 >= R3.5 baseline 6/8 (实际 R3.5.1 = 7/8 = 88%)。"""
        score_thresholds.main()
        out = capsys.readouterr().out
        # 提取 "准确率: 7/8 = 88%" 这种行
        import re
        m = re.search(r"准确率: (\d+)/(\d+)", out)
        assert m, f"找不到准确率行: {out[:300]}"
        correct, total = int(m.group(1)), int(m.group(2))
        assert total == 8, f"eval 样本数变 {total}, 期望 8"
        assert correct >= 6, (
            f"实跑准确率 {correct}/{total} < R3.5 baseline 6/8, 可能是 match_score 改动破坏阈值"
        )

    def test_live_mode_ignores_frozen_top_score(self, capsys):
        """篡改 jd_samples.json 的 top_score 字段, 验证脚本不受影响 (实跑 vs frozen 区别)。

        锁死核心: 如果未来有人把 score_thresholds.py 改回 s["top_score"], 这个测试会 fail。
        """
        # 1) 先跑一次, 拿实跑 baseline
        score_thresholds.main()
        out_baseline = capsys.readouterr().out
        report_baseline = REPORT_PATH.read_text(encoding="utf-8")
        # 解析 baseline 分数
        import re
        baseline_scores = {}
        for line in report_baseline.splitlines():
            if line.startswith("| "):
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 5:
                    try:
                        score = int(parts[4])
                        sid = parts[1]
                        if sid and "baiyun" in sid or "deepseek" in sid or "alibaba" in sid or "bytedance" in sid:
                            baseline_scores[sid] = score
                    except (ValueError, IndexError):
                        pass

        # 2) 篡改 jd_samples.json: 把所有 eval sample 的 top_score 改成 999
        original = SAMPLES_PATH.read_text(encoding="utf-8")
        try:
            data = json.loads(original)
            for s in data["samples"]:
                if s.get("label") != "公告型":
                    s["top_score"] = 999
                    s["top_role"] = "frozen_篡改"
            SAMPLES_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 3) 再跑一次, 解析新分数
            score_thresholds.main()
            out_tampered = capsys.readouterr().out
            report_tampered = REPORT_PATH.read_text(encoding="utf-8")
            tampered_scores = {}
            for line in report_tampered.splitlines():
                if line.startswith("| "):
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 5:
                        try:
                            score = int(parts[4])
                            sid = parts[1]
                            if sid and ("baiyun" in sid or "deepseek" in sid or "alibaba" in sid or "bytedance" in sid):
                                tampered_scores[sid] = score
                        except (ValueError, IndexError):
                            pass

            # 4) 断言: 篡改后分数必须 == baseline (因为实跑不看 frozen top_score)
            assert baseline_scores == tampered_scores, (
                f"实跑模式被破坏! baseline {baseline_scores} != "
                f"tampered {tampered_scores} (说明脚本仍读 frozen top_score)"
            )
        finally:
            # 5) 恢复 jd_samples.json (无论测试 pass/fail 都要恢复)
            SAMPLES_PATH.write_text(original, encoding="utf-8")
            # 6) 再跑一次, 把报告写回 baseline 状态
            score_thresholds.main()
            capsys.readouterr()  # 吃掉输出

    def test_report_contains_live_mode_marker(self):
        """报告 markdown 顶部必须含 "R3.5.1" + "实跑模式" 标识。"""
        score_thresholds.main()
        report = REPORT_PATH.read_text(encoding="utf-8")
        assert "R3.5.1" in report[:200], (
            f"报告顶部缺 R3.5.1 标识: {report[:200]}"
        )
        assert "实跑模式" in report[:500], (
            f"报告缺实跑模式说明: {report[:500]}"
        )
