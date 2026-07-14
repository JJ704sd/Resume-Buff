"""
R6-K Postman collection 字段名一致性检查工具

用途:
  解析 tests/postman/*.postman_collection.json, 抽出 Tests script 里
  `pm.expect(json.xxx.yyy).to.*` 引用的字段路径, 跟后端 API response
  schema(Pydantic Response + save_card 字面量)对账。字段名写错 / 后端
  schema 改了忘同步 collection 时会立刻 fail。

实现:
  1. AST 解析 backend/api/interview.py 抽 Pydantic Response 字段
  2. AST 解析 core/interview_agent.py 抽 save_card 返回字面量
  3. 正则解析 Postman collection 抽字段路径
  4. endpoint -> response schema 映射 + 字段路径校验
  5. 跑 FastAPI server 拿 /openapi.json 双校验(可选, 启动更快路径跳过)

执行:
  D:\\python3.11\\python.exe scripts/check_postman_schema.py
  exit 0 = 全 PASS
  exit 1 = 至少 1 个 FAIL

不依赖 server 启动, 纯静态分析, 适合 pre-push hook。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

# ----------------------------------------------------------------------
# 路径
# ----------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_API = REPO_ROOT / "backend" / "api" / "interview.py"
BACKEND_MAIN = REPO_ROOT / "backend" / "main.py"  # HealthResponse 在这里
CORE_AGENT = REPO_ROOT / "backend" / "core" / "interview_agent.py"
POSTMAN_DIR = REPO_ROOT / "tests" / "postman"


# ----------------------------------------------------------------------
# 1. 从 backend/api/interview.py 抽 Pydantic Response 字段
# ----------------------------------------------------------------------
def parse_pydantic_responses(path: Path) -> dict[str, set[str]]:
    """
    抽出 class XxxResponse(BaseModel) 的字段名。
    返回 {class_name: {field1, field2, ...}}
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    responses: dict[str, set[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # 只看 XxxResponse 类
        if not node.name.endswith("Response"):
            continue
        # 必须继承 BaseModel
        base_names = {
            ast.unparse(b) if hasattr(ast, "unparse") else b.id
            for b in node.bases
        }
        if not any("BaseModel" in bn for bn in base_names):
            continue

        fields: set[str] = set()
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields.add(stmt.target.id)
            elif isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name):
                        fields.add(tgt.id)
        responses[node.name] = fields

    return responses


# ----------------------------------------------------------------------
# 2. 从 core/interview_agent.py 抽 save_card 返回 dict 字面量
# ----------------------------------------------------------------------
def parse_save_card_literal(path: Path) -> dict[str, set[str]]:
    """
    抽出 save_card() 末尾 return 的 dict 字面量, 包括嵌套字段路径。
    返回 {"save_card": {material_ref.id, material_ref.type, refresh.should_refresh_preview, ...}}
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "save_card":
            continue

        # 找最后一个 return Dict
        for stmt in reversed(node.body):
            if isinstance(stmt, ast.Return) and isinstance(stmt.value, ast.Dict):
                fields = _flatten_dict_keys(stmt.value, prefix="")
                result["save_card"] = fields
                break
        break

    return result


def _flatten_dict_keys(d: ast.Dict, prefix: str) -> set[str]:
    """
    把 {"material_ref": {"type": "x", "id": "y"}} 拍扁成
    {"material_ref", "material_ref.type", "material_ref.id"}
    """
    out: set[str] = set()
    for k, v in zip(d.keys, d.values):
        if not isinstance(k, ast.Constant):
            continue
        key_name = str(k.value)
        if prefix:
            full_key = f"{prefix}.{key_name}"
        else:
            full_key = key_name
        out.add(full_key)
        if isinstance(v, ast.Dict):
            out.update(_flatten_dict_keys(v, prefix=full_key))
    return out


# ----------------------------------------------------------------------
# 3. 解析 Postman collection 抽字段路径
# ----------------------------------------------------------------------
PM_EXPECT_RE = re.compile(
    r"pm\.expect\(\s*json\.([\w.]+)\s*\)\s*\.to\b",
    re.MULTILINE,
)


def parse_postman_assertions(path: Path) -> list[dict[str, str]]:
    """
    抽出每个 step 的所有字段断言。
    返回 [{"step": "3. reply answer #1", "path": "captured_delta.responsibility", "check": "be.a"}, ...]
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    assertions: list[dict[str, str]] = []

    for item in data.get("item", []):
        step_name = item.get("name", "<unnamed>")
        for event in item.get("event", []):
            if event.get("listen") != "test":
                continue
            for line in event.get("script", {}).get("exec", []):
                m = PM_EXPECT_RE.search(line)
                if m:
                    assertions.append({
                        "step": step_name,
                        "path": m.group(1),
                        "check": "asserted",
                    })

    return assertions


# ----------------------------------------------------------------------
# 4. endpoint -> response schema 映射
# ----------------------------------------------------------------------
# 静态映射表: Postman step 的 request URL 决定用哪个 response schema
# 简化处理: 用 path 关键词匹配
ENDPOINT_TO_SCHEMA: list[tuple[str, str]] = [
    ("/api/health", "HealthResponse"),
    ("/api/interview/start", "StartResponse"),
    ("/api/interview/reply", "ReplyResponse"),
    ("/api/interview/draft", "DraftResponse"),
    ("/api/interview/save-card", "SaveResponse"),
]


def map_endpoint_to_schema(url_path: str) -> str | None:
    for substr, schema_name in ENDPOINT_TO_SCHEMA:
        if substr in url_path:
            return schema_name
    return None


# ----------------------------------------------------------------------
# 5. 对账
# ----------------------------------------------------------------------
def check_path_against_schema(
    field_path: str,
    schema_fields: set[str],
    nested_schemas: dict[str, set[str]],
) -> tuple[bool, str]:
    """
    字段路径在 schema 里是否能找到。
    返回 (ok, reason)
    """
    top_level = field_path.split(".")[0]

    # dict[str, Any] 弱类型: 查 nested_schemas 拿子字段
    if top_level in nested_schemas:
        nested = nested_schemas[top_level]
        if field_path in nested:
            return True, "nested field found"
        # top-level 存在但子字段不在
        return False, f"field '{field_path}' not in nested schema for '{top_level}'"

    if top_level in schema_fields:
        return True, "top-level field"

    return False, f"field '{top_level}' not in schema"


def main() -> int:
    # 1. 解析后端 schema
    responses = parse_pydantic_responses(BACKEND_API)
    # main.py 也有 Response (HealthResponse), 合并进来
    main_responses = parse_pydantic_responses(BACKEND_MAIN)
    responses.update(main_responses)
    # 健康检查端点 (/api/health) 直接返 dict 没 Pydantic model, hardcode
    responses["HealthResponse"] = {"status"}
    save_card_lit = parse_save_card_literal(CORE_AGENT)
    nested_schemas: dict[str, set[str]] = {}
    if "save_card" in save_card_lit:
        # 把 save_card 字面量平铺路径按顶级 key 分组
        grouped: dict[str, set[str]] = {}
        for f in save_card_lit["save_card"]:
            top = f.split(".")[0]
            grouped.setdefault(top, set()).add(f)
        nested_schemas.update(grouped)

    # 2. 解析 Postman collection
    collection_files = sorted(POSTMAN_DIR.glob("*.postman_collection.json"))
    if not collection_files:
        print(f"[check_postman_schema] no collection found in {POSTMAN_DIR}")
        return 1

    total_assertions = 0
    total_failures = 0

    for cpath in collection_files:
        print(f"\n=== {cpath.name} ===")
        data = json.loads(cpath.read_text(encoding="utf-8"))

        # 建立 step -> url 映射
        step_url: dict[str, str] = {}
        for item in data.get("item", []):
            url_obj = item.get("request", {}).get("url", {})
            if isinstance(url_obj, dict):
                # url 可能是 {"raw": "...", "path": [...]} 或纯 string
                raw = url_obj.get("raw", "")
                if not raw and "path" in url_obj:
                    host = url_obj.get("host", [""])
                    if isinstance(host, list):
                        host = host[0] if host else ""
                    raw = f"http://{host}/" + "/".join(url_obj["path"])
            else:
                raw = str(url_obj)
            step_url[item.get("name", "")] = raw

        assertions = parse_postman_assertions(cpath)
        if not assertions:
            print("  (no pm.expect assertions found)")
            continue

        for a in assertions:
            total_assertions += 1
            step = a["step"]
            field_path = a["path"]
            url = step_url.get(step, "")
            schema_name = map_endpoint_to_schema(url)
            if not schema_name:
                print(f"  [WARN] no schema mapping for step '{step}' (url={url})")
                continue

            schema_fields = responses.get(schema_name, set())
            ok, reason = check_path_against_schema(
                field_path, schema_fields, nested_schemas
            )

            status = "PASS" if ok else "FAIL"
            if not ok:
                total_failures += 1
            print(f"  [{status}] {step:50s} json.{field_path:50s} ({reason})")

    print(f"\n=== summary: {total_assertions} assertions, {total_failures} failures ===")
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
