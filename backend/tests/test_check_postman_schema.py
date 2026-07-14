"""
tests/test_check_postman_schema.py

R6-K Postman collection 字段名一致性检查工具的 pytest 锁。
- 用 monkeypatch / tmp_path 隔离真实 collection
- 测 4 个能力:
  1. PASS 路径: 正确 collection 跑出 0 failures
  2. FAIL catch: 字段名 typo (project_id 写错) 工具能精确 catch
  3. FAIL catch: 字段名 typo (captured_delta 拼成 captured_dleta) 工具能 catch
  4. 主函数 import 入口存在

工具能力圈 (R6-K closeout §2 文档化):
  - 字段名 typo / schema 改名 → 能 catch
  - 业务正确性 (1st turn 抽哪个 slot) → 不能 catch, 需要真跑 server
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# 工具脚本在 scripts/ 下, 不是 Python package, 用 importlib 加载
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


def _load_check_module():
    """延迟加载 scripts/check_postman_schema.py (不在 import path)"""
    spec = importlib.util.spec_from_file_location(
        "check_postman_schema", SCRIPTS_DIR / "check_postman_schema.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------
# 测试数据: 一个最小可用的 fake collection, 字段都对得上
# ----------------------------------------------------------------------
GOOD_COLLECTION = {
    "info": {"name": "test-good", "_postman_id": "test-good-1"},
    "item": [
        {
            "name": "1. health",
            "request": {"method": "GET", "url": {"raw": "http://x/api/health"}},
            "event": [
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            "pm.test('health ok', function () {",
                            "    pm.expect(json.status).to.eql('ok');",
                            "});",
                        ],
                    },
                }
            ],
        },
        {
            "name": "2. start",
            "request": {
                "method": "POST",
                "url": {"raw": "http://x/api/interview/start"},
            },
            "event": [
                {
                    "listen": "test",
                    "script": {
                        "type": "text/javascript",
                        "exec": [
                            "pm.expect(json.session_id).to.be.a('string');",
                            "pm.expect(json.circuit_state).to.eql('closed');",
                        ],
                    },
                }
            ],
        },
    ],
}


def _make_bad_collection(bad_field: str) -> dict:
    """生成一个 typo 字段的 bad collection (FAIL case)"""
    bad = {
        "info": {"name": "test-bad", "_postman_id": "test-bad-1"},
        "item": [
            {
                "name": "7. save-card",
                "request": {
                    "method": "POST",
                    "url": {"raw": "http://x/api/interview/save-card"},
                },
                "event": [
                    {
                        "listen": "test",
                        "script": {
                            "type": "text/javascript",
                            "exec": [
                                f"pm.expect(json.{bad_field}).to.be.a('string');",
                            ],
                        },
                    }
                ],
            }
        ],
    }
    return bad


# ----------------------------------------------------------------------
# 1. 模块加载 + AST 解析函数单元
# ----------------------------------------------------------------------
class TestModuleLoading:
    def test_module_imports(self):
        """工具脚本可以被 importlib 加载, 4 个核心函数都在"""
        cps = _load_check_module()
        assert hasattr(cps, "parse_pydantic_responses")
        assert hasattr(cps, "parse_save_card_literal")
        assert hasattr(cps, "parse_postman_assertions")
        assert hasattr(cps, "main")


# ----------------------------------------------------------------------
# 2. parse_postman_assertions 单元
# ----------------------------------------------------------------------
class TestParsePostmanAssertions:
    def test_extracts_field_paths(self, tmp_path):
        cps = _load_check_module()
        col_path = tmp_path / "test.postman_collection.json"
        col_path.write_text(
            json.dumps(GOOD_COLLECTION, ensure_ascii=False), encoding="utf-8"
        )
        assertions = cps.parse_postman_assertions(col_path)

        # 至少 3 条: status / session_id / circuit_state
        paths = {a["path"] for a in assertions}
        assert "status" in paths
        assert "session_id" in paths
        assert "circuit_state" in paths

    def test_no_exec_lines(self, tmp_path):
        """空 collection 返空 list"""
        cps = _load_check_module()
        col_path = tmp_path / "empty.postman_collection.json"
        col_path.write_text(json.dumps({"info": {}, "item": []}), encoding="utf-8")
        assert cps.parse_postman_assertions(col_path) == []


# ----------------------------------------------------------------------
# 3. parse_pydantic_responses 单元
# ----------------------------------------------------------------------
class TestParsePydanticResponses:
    def test_extracts_response_fields(self):
        cps = _load_check_module()
        # 用真实 backend/api/interview.py 测
        from pathlib import Path
        api_path = Path(__file__).resolve().parent.parent / "api" / "interview.py"
        if not api_path.exists():
            pytest.skip("backend/api/interview.py not found")
        responses = cps.parse_pydantic_responses(api_path)

        # 至少 StartResponse + ReplyResponse + DraftResponse + SaveResponse
        assert "StartResponse" in responses
        assert "ReplyResponse" in responses
        assert "DraftResponse" in responses
        assert "SaveResponse" in responses

        # StartResponse 应该含 session_id / state / circuit_state
        start = responses["StartResponse"]
        assert "session_id" in start
        assert "state" in start
        assert "circuit_state" in start

    def test_ignores_non_response_classes(self, tmp_path):
        """非 Response 类不应被抽出来"""
        cps = _load_check_module()
        fake = tmp_path / "fake.py"
        fake.write_text(
            "from pydantic import BaseModel\n"
            "class Foo: pass\n"  # 非 BaseModel
            "class BarResponse(BaseModel):\n"
            "    x: int = 0\n",
            encoding="utf-8",
        )
        responses = cps.parse_pydantic_responses(fake)
        assert "BarResponse" in responses
        assert "Foo" not in responses


# ----------------------------------------------------------------------
# 4. parse_save_card_literal 单元
# ----------------------------------------------------------------------
class TestParseSaveCardLiteral:
    def test_extracts_nested_fields(self):
        cps = _load_check_module()
        from pathlib import Path
        core_path = (
            Path(__file__).resolve().parent.parent / "core" / "interview_agent.py"
        )
        if not core_path.exists():
            pytest.skip("backend/core/interview_agent.py not found")
        result = cps.parse_save_card_literal(core_path)
        assert "save_card" in result
        # 应该有 material_ref.id 这种嵌套字段
        fields = result["save_card"]
        assert "material_ref" in fields
        assert "material_ref.id" in fields
        assert "material_ref.type" in fields


# ----------------------------------------------------------------------
# 5. map_endpoint_to_schema 单元
# ----------------------------------------------------------------------
class TestEndpointMapping:
    def test_known_endpoints(self):
        cps = _load_check_module()
        assert cps.map_endpoint_to_schema("http://x/api/health") == "HealthResponse"
        assert (
            cps.map_endpoint_to_schema("http://x/api/interview/start")
            == "StartResponse"
        )
        assert (
            cps.map_endpoint_to_schema("http://x/api/interview/reply")
            == "ReplyResponse"
        )
        assert (
            cps.map_endpoint_to_schema("http://x/api/interview/draft")
            == "DraftResponse"
        )
        assert (
            cps.map_endpoint_to_schema("http://x/api/interview/save-card")
            == "SaveResponse"
        )

    def test_unknown_endpoint(self):
        cps = _load_check_module()
        assert cps.map_endpoint_to_schema("http://x/api/unknown") is None


# ----------------------------------------------------------------------
# 6. check_path_against_schema 单元
# ----------------------------------------------------------------------
class TestSchemaPathCheck:
    def test_top_level_field(self):
        cps = _load_check_module()
        ok, reason = cps.check_path_against_schema(
            "session_id", {"session_id", "state"}, {}
        )
        assert ok is True
        assert reason == "top-level field"

    def test_nested_field_found(self):
        cps = _load_check_module()
        ok, reason = cps.check_path_against_schema(
            "material_ref.id",
            {"material_ref", "ok"},
            {"material_ref": {"material_ref.id", "material_ref.type"}},
        )
        assert ok is True
        assert reason == "nested field found"

    def test_nested_field_missing(self):
        cps = _load_check_module()
        ok, reason = cps.check_path_against_schema(
            "material_ref.project_id",  # 故意写错
            {"material_ref", "ok"},
            {"material_ref": {"material_ref.id", "material_ref.type"}},
        )
        assert ok is False
        assert "not in nested schema" in reason

    def test_top_level_missing(self):
        cps = _load_check_module()
        ok, reason = cps.check_path_against_schema(
            "captured_dleta",  # typo
            {"captured_delta"},
            {},
        )
        assert ok is False
        assert "not in schema" in reason


# ----------------------------------------------------------------------
# 7. main() 端到端 (用 monkeypatch POSTMAN_DIR 隔离)
# ----------------------------------------------------------------------
class TestMainEndToEnd:
    def test_good_collection_exits_0(self, tmp_path, monkeypatch, capsys):
        cps = _load_check_module()
        col_path = tmp_path / "test.postman_collection.json"
        col_path.write_text(
            json.dumps(GOOD_COLLECTION, ensure_ascii=False), encoding="utf-8"
        )
        monkeypatch.setattr(cps, "POSTMAN_DIR", tmp_path)
        exit_code = cps.main()
        out = capsys.readouterr().out
        assert exit_code == 0, f"expected 0, got {exit_code}, output:\n{out}"
        assert "0 failures" in out

    def test_bad_field_catches_typo(self, tmp_path, monkeypatch, capsys):
        cps = _load_check_module()
        # save-card 端点用 project_id (错) → 工具必须 catch
        col_path = tmp_path / "test.postman_collection.json"
        bad = _make_bad_collection("material_ref.project_id")
        col_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(cps, "POSTMAN_DIR", tmp_path)
        exit_code = cps.main()
        out = capsys.readouterr().out
        assert exit_code == 1, f"expected 1, got {exit_code}, output:\n{out}"
        assert "1 failures" in out
        assert "FAIL" in out
        assert "project_id" in out

    def test_bad_top_level_field_catches_typo(self, tmp_path, monkeypatch, capsys):
        """captured_dleta (拼错) vs captured_delta 实际 schema 字段"""
        cps = _load_check_module()
        col_path = tmp_path / "test.postman_collection.json"
        bad = _make_bad_collection("captured_dleta")  # 故意拼错
        col_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(cps, "POSTMAN_DIR", tmp_path)
        exit_code = cps.main()
        out = capsys.readouterr().out
        assert exit_code == 1
        assert "captured_dleta" in out


# ----------------------------------------------------------------------
# 8. 真实 collection 全跑通 (回归)
# ----------------------------------------------------------------------
class TestRealCollection:
    def test_real_r6k_collection_passes(self, capsys):
        """真实 R6-K collection 应该 0 failures"""
        cps = _load_check_module()
        real = (
            Path(__file__).resolve().parent.parent.parent
            / "tests"
            / "postman"
            / "R6-K_Interivew_Agent.postman_collection.json"
        )
        if not real.exists():
            pytest.skip("R6-K collection not found")
        cps.POSTMAN_DIR = real.parent
        exit_code = cps.main()
        out = capsys.readouterr().out
        assert exit_code == 0, f"real collection should pass, got {exit_code}:\n{out}"
        assert "0 failures" in out
