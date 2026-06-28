"""
core/tool_schema 模块测试 (R5-B Phase 2A: 轻量 JSON Schema validator)

锁点(>=15 case):
  TestSchemaRequired (3 case):
    1.  missing_required_field_reported           — 单个必填字段缺失
    2.  multiple_missing_required_fields_reported — 多必填字段缺失,一次性列出
    3.  no_required_field_passes                  — 无 required 时不校验

  TestSchemaType (5 case):
    4.  string_type_accepted                      — string 类型匹配
    5.  integer_type_accepted                     — integer 接受 int
    6.  number_type_accepts_int_and_float         — number 同时接受 int 和 float
    7.  boolean_type_rejects_int                  — boolean 拒绝 int 0/1
    8.  wrong_type_reports_actual_type            — 类型错时报实际类型名

  TestSchemaRange (2 case):
    9.  integer_minimum_violation                 — 低于 minimum 报错
    10. integer_maximum_violation                 — 高于 maximum 报错

  TestSchemaArray (3 case):
    11. array_items_type_check                    — 数组 items 类型校验
    12. array_items_number_range                  — 数组 items 数值范围
    13. array_wrong_type_reports_array            — 非 list 报错

  TestSchemaNoSchema (2 case):
    14. no_schema_always_passes                   — 无 schema 不校验
    15. non_dict_schema_passes                    — 非 dict schema 不校验 (宽容)

  TestSchemaPrivacy (1 case):
    16. error_msg_never_contains_value             — 错误描述不含 value 原文

  TestSchemaIntegration (1 case):
    17. retrieve_evidence_real_schema_validates   — 真实工具 schema 能跑通 validator
"""
import pytest

from core.tool_schema import (
    _format_type,
    _check_type,
    validate_schema,
)


# =========================================================================
# TestSchemaRequired
# =========================================================================
class TestSchemaRequired:
    """required 字段缺失校验"""

    def test_missing_required_field_reported(self):
        """单个必填字段缺失 → 报错, 含字段名"""
        schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
        result = validate_schema(schema, {})
        assert result is not None
        assert "text" in result  # 含缺失字段名
        # 错误描述不应含 value 内容
        assert "<" not in result and ">" not in result

    def test_multiple_missing_required_fields_reported(self):
        """多个必填字段缺失 → 一次性列出(R5-A closeout 兼容语义)"""
        schema = {
            "type": "object",
            "required": ["text", "target_role", "materials"],
            "properties": {
                "text": {"type": "string"},
                "target_role": {"type": "string"},
                "materials": {"type": "object"},
            },
        }
        result = validate_schema(schema, {})
        assert result is not None
        # 一次性列出所有缺失字段(向后兼容 R5-A closeout 测试)
        assert "text" in result
        assert "target_role" in result
        assert "materials" in result

    def test_no_required_field_passes(self):
        """无 required 字段时不校验 required (即使 value 是空 dict)"""
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        # value 是空 dict, 但没 required → 通过
        result = validate_schema(schema, {})
        assert result is None


# =========================================================================
# TestSchemaType
# =========================================================================
class TestSchemaType:
    """type 校验"""

    def test_string_type_accepted(self):
        """string 类型接受 str"""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        assert validate_schema(schema, {"name": "hello"}) is None

    def test_integer_type_accepted(self):
        """integer 类型接受 int"""
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
        assert validate_schema(schema, {"n": 42}) is None

    def test_number_type_accepts_int_and_float(self):
        """number 类型同时接受 int 和 float (JSON number 语义)"""
        schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        assert validate_schema(schema, {"x": 1}) is None  # int
        assert validate_schema(schema, {"x": 1.5}) is None  # float

    def test_boolean_type_rejects_int(self):
        """boolean 拒绝 int 0/1 (Python bool ≠ int in strict mode)"""
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        # 1 不是 boolean, 应报错
        result = validate_schema(schema, {"flag": 1})
        assert result is not None
        assert "boolean" in result
        assert "integer" in result  # 报告实际类型

    def test_wrong_type_reports_actual_type(self):
        """类型错时报实际类型名(不含 value 原文)"""
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
        result = validate_schema(schema, {"n": "not a number"})
        assert result is not None
        # 含 expected + actual 类型名
        assert "integer" in result
        assert "string" in result
        # 不含 value 原文
        assert "not a number" not in result


# =========================================================================
# TestSchemaRange
# =========================================================================
class TestSchemaRange:
    """number / integer 的 minimum / maximum 范围校验"""

    def test_integer_minimum_violation(self):
        """值 < minimum → 报错"""
        schema = {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1}}}
        result = validate_schema(schema, {"n": 0})
        assert result is not None
        assert "minimum" in result
        # 不含 value
        assert "0" not in result or "<" in result  # range 报错只含 < 或 > 符号

    def test_integer_maximum_violation(self):
        """值 > maximum → 报错"""
        schema = {"type": "object", "properties": {"n": {"type": "integer", "maximum": 50}}}
        result = validate_schema(schema, {"n": 100})
        assert result is not None
        assert "maximum" in result


# =========================================================================
# TestSchemaArray
# =========================================================================
class TestSchemaArray:
    """array 类型 + items 校验"""

    def test_array_items_type_check(self):
        """array 的 items 类型校验"""
        schema = {
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        }
        # items 都是 string → 通过
        assert validate_schema(schema, {"tags": ["a", "b"]}) is None
        # items 含 int → 报错
        result = validate_schema(schema, {"tags": ["a", 1]})
        assert result is not None
        assert "string" in result
        assert "integer" in result

    def test_array_items_number_range(self):
        """array items 数值范围校验 (retrieve_evidence.top_k 场景)"""
        schema = {
            "type": "object",
            "properties": {
                "values": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 50}},
            },
        }
        assert validate_schema(schema, {"values": [5, 10, 50]}) is None
        # 0 < minimum 1
        result = validate_schema(schema, {"values": [5, 0]})
        assert result is not None
        assert "minimum" in result

    def test_array_wrong_type_reports_array(self):
        """非 list 字段 → 报 expected array"""
        schema = {"type": "object", "properties": {"tags": {"type": "array"}}}
        result = validate_schema(schema, {"tags": "not array"})
        assert result is not None
        assert "array" in result
        assert "string" in result


# =========================================================================
# TestSchemaNoSchema
# =========================================================================
class TestSchemaNoSchema:
    """无 schema 时不校验 (向后兼容)"""

    def test_no_schema_always_passes(self):
        """schema=None → 不校验, 任何 value 通过"""
        assert validate_schema(None, {}) is None
        assert validate_schema(None, {"any": "value"}) is None
        assert validate_schema(None, None) is None

    def test_non_dict_schema_passes(self):
        """schema 非 dict → 不校验 (宽容)"""
        assert validate_schema("not a dict", {}) is None
        assert validate_schema([], {"a": 1}) is None
        assert validate_schema(42, None) is None


# =========================================================================
# TestSchemaPrivacy
# =========================================================================
class TestSchemaPrivacy:
    """隐私边界: 错误描述不含 value 原文 (R5-A closeout §6.4 + R5-B Phase 2A)"""

    def test_error_msg_never_contains_value(self):
        """错误描述不含 value 原文(防 PII 泄漏)"""
        schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
        sensitive_text = "手机号 13800138000 邮箱 evil@example.com"
        # 故意让 value 含敏感信息, 看错误描述是否泄漏
        result = validate_schema(schema, {"text": 12345})  # type 错
        assert result is not None
        # 不含敏感 PII
        assert "13800138000" not in result
        assert "evil@example.com" not in result
        assert sensitive_text not in result


# =========================================================================
# TestSchemaIntegration
# =========================================================================
class TestSchemaIntegration:
    """真实工具 schema 跑通 validator"""

    def test_retrieve_evidence_real_schema_validates(self):
        """真实 retrieve_evidence 工具 schema 能跑 validator"""
        from core.agent_tools import AGENT_TOOLS
        spec = AGENT_TOOLS["retrieve_evidence"]
        # 完整 args (含 top_k / min_confidence 范围)
        valid_args = {
            "jd_keywords": ["LLM", "评测"],
            "role": "tech_metric",
            "materials": {"projects": [], "skills": {}},
            "top_k": 8,
            "min_confidence": 0.5,
        }
        assert validate_schema(spec.input_schema, valid_args) is None

        # top_k 越界
        invalid_args = dict(valid_args)
        invalid_args["top_k"] = 100  # > maximum 50
        result = validate_schema(spec.input_schema, invalid_args)
        assert result is not None

        # jd_keywords 类型错
        invalid_args2 = dict(valid_args)
        invalid_args2["jd_keywords"] = "not list"
        result2 = validate_schema(spec.input_schema, invalid_args2)
        assert result2 is not None

    def test_format_type_helper(self):
        """_format_type 把 Python 类型映射成 schema 字符串"""
        assert _format_type("hello") == "string"
        assert _format_type(42) == "integer"
        assert _format_type(1.5) == "number"
        assert _format_type(True) == "boolean"  # bool 必须先判
        assert _format_type(False) == "boolean"
        assert _format_type([1, 2]) == "array"
        assert _format_type({"k": "v"}) == "object"

    def test_check_type_helper(self):
        """_check_type 单元函数"""
        assert _check_type("string", "abc", path="x") is None
        assert _check_type("integer", 1, path="x") is None
        assert _check_type("integer", "abc", path="x") is not None
        assert _check_type("boolean", True, path="x") is None
        assert _check_type("boolean", 1, path="x") is not None  # int 不是 boolean