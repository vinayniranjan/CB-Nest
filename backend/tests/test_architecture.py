"""Architecture rule: AI agents never write HR business tables directly.

The only DB writes in the AI package are to the AI-owned tables (audit log and
policy-chunk vector store). Every HR mutation goes through backend APIs.
"""

import ast
import re
from pathlib import Path

AI_PACKAGE = Path(__file__).resolve().parents[1] / "app" / "services" / "ai"
AI_OWNED_MODELS = {"AIAuditLog", "AIPolicyChunk"}
WRITE_SQL = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b", re.IGNORECASE)


def _modules():
    return sorted(AI_PACKAGE.glob("*.py"))


def test_no_raw_write_sql_in_ai_package():
    for path in _modules():
        source = path.read_text()
        assert not WRITE_SQL.search(source), f"{path.name} contains raw write SQL"


def test_orm_writes_only_touch_ai_owned_tables():
    for path in _modules():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"add", "add_all", "merge"}
                and ast.unparse(node.func.value) in {"db", "session", "self.db"}
            ):
                if not node.args:
                    continue
                created = node.args[0]
                assert isinstance(created, ast.Call) and getattr(created.func, "id", None) in AI_OWNED_MODELS, (
                    f"{path.name}:{node.lineno} writes a non-AI model"
                )
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "delete":
                target = node.args[0] if node.args else None
                assert getattr(target, "id", None) in AI_OWNED_MODELS, f"{path.name}:{node.lineno} deletes a non-AI table"


def test_action_agent_has_no_database_session():
    for name in ("action_agent.py", "api_tools.py"):
        source = (AI_PACKAGE / name).read_text()
        assert "AsyncSession" not in source and "SessionLocal" not in source, f"{name} must use backend APIs only"
