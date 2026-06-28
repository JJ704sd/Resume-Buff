"""
R5-B Phase 2A: 轻量 JSON Schema validator 子集

设计目标 (round5-b-agent-capability-spec.md §3.1):
  - 只覆盖当前 ToolSpec.input_schema 用到的子集:
      * type (object / string / integer / number / boolean / array)
      * required
      * properties
      * items
      * minimum / maximum
  - 失败时:
      * 不调用工具函数
      * 返回 ToolResult(status="error", error_type=ToolErrorType.TOOL_ARGS_INVALID)
      * error_msg 只写字段名 + 类型摘要, 不写参数原文 (隐私边界)
  - 严格区别 expected type 和 actual type, 给出精确报错

不引入:
  - 不引入 jsonschema / pydantic / 任何第三方依赖
  - 不实现完整 JSON Schema Draft 7 (MVP 子集足够, Phase 2A 范围)
  - 不支持 oneOf / anyOf / allOf / $ref (留作 Phase 5+ 评估)

公开 API:
  - validate_schema(schema, value)            -> Optional[str]
      返回 None 表示通过; 返回 str 表示失败原因(不包含 value 原文, 只含字段名 + 类型名)
  - _format_type(value)                       -> str
      把 Python 类型映射成 schema 的 type 字符串

注意:
  - 工具 spec.input_schema 可以无 required (向后兼容 R5-A closeout 之前的工具)
  - 没 properties 的 object 类型不校验内部字段 (允许空 dict 透传)
  - items 只支持一维数组校验 (嵌套 array / tuple 不在范围)
"""
from __future__ import annotations

from typing import Any, Optional


# ----------------------------------------------------------------------
# 类型映射: Python type -> schema type 字符串
# ----------------------------------------------------------------------
_PY_TYPE_NAMES = {
    dict: "object",
    list: "array",
    str: "string",
    bool: "boolean",
    int: "integer",
    float: "number",
}


def _format_type(value: Any) -> str:
    """
    把 Python value 映射成 schema type 字符串 (用于 error_msg).
    bool 是 int 的子类, 所以 bool 必须先判 (Python 3 顺序).
    """
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


# ----------------------------------------------------------------------
# 单字段校验
# ----------------------------------------------------------------------
def _check_type(expected: str, value: Any, *, path: str) -> Optional[str]:
    """
    校验 value 是否匹配 schema expected type.

    Args:
        expected: schema type 字符串 (object/string/integer/number/boolean/array)
        value:    待校验的 Python 值
        path:     字段路径 (供 error_msg 使用, 不含 value 原文)

    Returns:
        None 表示类型匹配; str 表示不匹配的错误描述 (不含 value 原文)

    特殊规则:
      - expected="integer" 接受 Python int (但 bool 不算)
      - expected="number"  接受 int 和 float (JSON number 兼容)
      - expected="boolean" 只接受 bool (Python 中 0/1 不算 boolean)
    """
    if expected == "object":
        if not isinstance(value, dict):
            return f"{path}: expected object, got {_format_type(value)}"
        return None
    if expected == "array":
        if not isinstance(value, list):
            return f"{path}: expected array, got {_format_type(value)}"
        return None
    if expected == "string":
        if not isinstance(value, str):
            return f"{path}: expected string, got {_format_type(value)}"
        return None
    if expected == "boolean":
        # bool 必须先判 (bool 是 int 子类, Python 3 顺序)
        if not isinstance(value, bool):
            return f"{path}: expected boolean, got {_format_type(value)}"
        return None
    if expected == "integer":
        # 排除 bool (bool 是 int 子类)
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{path}: expected integer, got {_format_type(value)}"
        return None
    if expected == "number":
        # number = int | float (但排除 bool)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{path}: expected number, got {_format_type(value)}"
        return None
    # 未知 type — 不阻断, 视为通过 (保守, 留给上层)
    return None


def _check_number_range(
    expected: dict, value: Any, *, path: str
) -> Optional[str]:
    """
    校验 number / integer 类型的 minimum / maximum 范围.

    Args:
        expected: schema dict (含 minimum / maximum 等)
        value:    待校验的 Python 数值
        path:     字段路径

    Returns:
        None 表示在范围内; str 表示越界错误描述

    规则:
      - minimum / maximum 缺失时不做范围检查
      - 值必须可与 minimum/maximum 比较 (type check 已通过, 此处只比较数值)
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None  # 不是 number, 留给 type check
    minimum = expected.get("minimum")
    maximum = expected.get("maximum")
    if minimum is not None and value < minimum:
        return f"{path}: value < minimum({minimum})"
    if maximum is not None and value > maximum:
        return f"{path}: value > maximum({maximum})"
    return None


def _check_array_items(
    expected: dict, value: Any, *, path: str
) -> Optional[str]:
    """
    校验数组的 items 子 schema (只支持一维).

    Args:
        expected: schema dict (含 items 字段)
        value:    待校验的 list
        path:     数组路径

    Returns:
        None 表示数组 items 都通过; str 表示第一个失败元素的错误
    """
    items_schema = expected.get("items")
    if not isinstance(items_schema, dict):
        return None  # 无 items schema, 不校验
    expected_item_type = items_schema.get("type")
    if not expected_item_type:
        return None  # 无 type, 不校验

    for i, item in enumerate(value):
        item_path = f"{path}[{i}]"
        err = _check_type(expected_item_type, item, path=item_path)
        if err:
            return err
        # 数组元素的 number 也支持 minimum/maximum
        if isinstance(items_schema, dict):
            range_err = _check_number_range(items_schema, item, path=item_path)
            if range_err:
                return range_err
    return None


def _validate_object(
    schema: dict, value: Any, *, path: str = ""
) -> Optional[str]:
    """
    校验 object 类型 (required + properties).

    Args:
        schema: 完整 schema dict (含 type=object, required, properties)
        value:  待校验的 dict
        path:   字段路径 (递归时累加)

    Returns:
        None 表示通过; str 表示第一个失败的错误描述 (不含 value 原文)

    规则:
      - 必填字段缺失 -> 一次性列出所有缺失字段(向后兼容 R5-A closeout 语义)
      - 每个 property 单独校验 type + range
      - 未知字段不报错 (向后兼容 — 工具可以选择性消费)
    """
    if not isinstance(value, dict):
        # 不应到这里 (type check 已通过), 防御性
        return f"{path}: expected object, got {_format_type(value)}"

    required = schema.get("required") or []
    missing = [field_name for field_name in required if field_name not in value]
    if missing:
        # R5-A closeout 兼容: 一次性列出所有缺失字段
        return f"missing required args: {missing}"

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return None  # 无 properties 定义, 只校验 required

    for field_name, field_schema in properties.items():
        if field_name not in value:
            continue  # 非 required 字段缺失 -> 跳过
        if not isinstance(field_schema, dict):
            continue  # property schema 非 dict, 跳过 (宽容)
        field_path = f"{path}.{field_name}" if path else field_name
        field_value = value[field_name]

        # field type 检查
        field_type = field_schema.get("type")
        if field_type:
            err = _check_type(field_type, field_value, path=field_path)
            if err:
                return err
        # 数值范围
        range_err = _check_number_range(field_schema, field_value, path=field_path)
        if range_err:
            return range_err
        # 数组 items
        if field_type == "array":
            items_err = _check_array_items(field_schema, field_value, path=field_path)
            if items_err:
                return items_err

    return None


# ----------------------------------------------------------------------
# 主入口
# ----------------------------------------------------------------------
def validate_schema(schema: Any, value: Any) -> Optional[str]:
    """
    轻量 JSON Schema 校验 (子集: type / required / properties / items / minimum / maximum).

    Args:
        schema: 工具的 input_schema dict (或 None)
        value:  实际传入的 args dict

    Returns:
        None 表示通过校验; str 表示第一个失败的错误描述

        **错误描述只含字段名 + 类型名, 绝不包含 value 原文**
        (对齐 spec §6.4 隐私边界)

    校验顺序:
      1. schema 缺失或非 dict -> 视为通过 (向后兼容)
      2. type 检查 (顶层)
      3. number/integer 的 minimum/maximum
      4. array 的 items 子 schema
      5. object 的 required + properties (递归)

    已知边界:
      - unknown property 不报错 (宽容, 不破坏现有调用)
      - 不支持 oneOf / anyOf / allOf / $ref / format
      - 不支持嵌套 object 的 properties (只校验一层 properties + array.items)
    """
    if schema is None or not isinstance(schema, dict):
        return None  # 无 schema = 不校验 (向后兼容)

    expected_type = schema.get("type")
    if expected_type:
        # 顶层 type
        err = _check_type(expected_type, value, path="args")
        if err:
            return err

        # 顶层 number 范围
        range_err = _check_number_range(schema, value, path="args")
        if range_err:
            return range_err

        # 顶层 array items
        if expected_type == "array":
            return _check_array_items(schema, value, path="args")

        # 顶层 object: 递归校验 properties + required
        if expected_type == "object":
            return _validate_object(schema, value, path="")

    return None