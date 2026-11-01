#!/usr/bin/env python3
"""测试库改造台账：按 A~E 判据逐文件定档（任务 04-6-2）。

背景：测试体系从「每用例一套干净 SQLite 库」改为「每逻辑数据源一套库 + 用例叠加」后，
存量用例要按五类分层处置（A 不动 / B 机械改造 / C 语义重写 / D 白名单 / E 删除）。
人工逐文件定档既慢又不可复核，故定档由本脚本产出，人工只需复核结论。

判据（与《04-6-2 详细设计》§6.1 一致，优先级 E > D > C > B > A）：

- E：顶层 `import` 解析不到（功能已不存在的候选，需人工确认后删除）
- D：文件带 `@pytest.mark.own_db("理由")` 或模块级 `pytestmark` 含之（建库即被测）
- C：自建库痕迹 **且** 含整表断言（`len(...) == N` / `total == N` / `count()` 比较 / `== []`）
- B：自建库痕迹，无整表断言
- A：无自建库痕迹（纯逻辑 / 契约 / 路由 / 静态护栏）

用法见同目录 `README.md`。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SQLITE_PREFIXES = ("sqlite+aiosqlite:///", "sqlite:///")
ENGINE_FACTORIES = ("create_async_engine", "create_engine")
DB_SUFFIXES = (".db",)
MARKER = "own_db"

CLASS_ORDER = ("E", "D", "C", "B", "A")
ACTION = {
    "A": "不动",
    "B": "机械改造",
    "C": "语义重写",
    "D": "own_db 白名单",
    "E": "删除（先核覆盖率）",
}

_EXACT_COUNT_PATTERNS = (
    re.compile(r"^\s*(total|count|len)\(.*\)\s*==\s*\d+"),
    re.compile(r"^\s*assert\s+len\(.*\)\s*==\s*\d+"),
)

_D_KEYWORDS = (
    "create_database(",
    "drop_database(",
    "apply_unit_schema(",
    "init_schema",
    "init_tenant",
    "provision_tenant",
    "migrate_topology",
    "url_template",
    "alembic",
    "seed_tenants(",
)
"""「建库即被测」的代码特征：建库 / 迁移 / 多库拓扑 / 每租户派生库 / 建库播种。"""


@dataclass
class Entry:
    """单个测试文件的定档结果。"""

    repo: str
    path: str
    tests: int
    klass: str
    batch: int
    evidence: str


@dataclass
class Facts:
    """单文件的静态事实（判定输入）。"""

    tests: int = 0
    db_build: list[str] = field(default_factory=list)
    exact_count: list[str] = field(default_factory=list)
    own_db: str = ""
    unresolved: list[str] = field(default_factory=list)


def _call_name(node: ast.AST) -> str:
    """取调用名（支持 `a.b()` 与 `b()`）。"""
    if not isinstance(node, ast.Call):
        return ""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _marker_reason(node: ast.AST) -> str:
    """取节点装饰器上的 `own_db` 理由（空串表示未打标）。"""
    for decorator in getattr(node, "decorator_list", []):
        if not isinstance(decorator, ast.Call):
            continue
        target = decorator.func
        if isinstance(target, ast.Attribute) and target.attr == MARKER:
            for arg in decorator.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return arg.value
    return ""


def _module_marker_reason(tree: ast.Module) -> str:
    """取模块级 `pytestmark = [...]` 里的 `own_db` 理由。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None or not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets):
            continue
        elements = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        for element in elements:
            if not isinstance(element, ast.Call):
                continue
            target = element.func
            if not (isinstance(target, ast.Attribute) and target.attr == MARKER):
                continue
            for arg in element.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    return arg.value
    return ""


def _collect_facts(tree: ast.Module, source: str) -> Facts:
    """收集判定所需事实。"""
    facts = Facts()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            facts.tests += 1
            if not facts.own_db:
                facts.own_db = _marker_reason(node)
        elif isinstance(node, ast.ClassDef) and not facts.own_db:
            facts.own_db = _marker_reason(node)
    if not facts.own_db:
        facts.own_db = _module_marker_reason(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith(SQLITE_PREFIXES):
                facts.db_build.append(f"{node.lineno}: 连接串字面量")
        elif isinstance(node, ast.Call) and _call_name(node) in ENGINE_FACTORIES:
            facts.db_build.append(f"{node.lineno}: {_call_name(node)}()")
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant):
            value = node.right.value
            if isinstance(value, str) and value.endswith(DB_SUFFIXES):
                facts.db_build.append(f"{node.lineno}: 临时库 {value}")
        elif isinstance(node, ast.Name) and node.id == "tmp_path_factory":
            facts.db_build.append(f"{node.lineno}: tmp_path_factory")

    for line_no, line in enumerate(source.splitlines(), start=1):
        if any(pattern.match(line) for pattern in _EXACT_COUNT_PATTERNS):
            facts.exact_count.append(f"{line_no}: {line.strip()[:60]}")
        elif "count()" in line and re.search(r"count\(\).*==\s*\d", line):
            facts.exact_count.append(f"{line_no}: {line.strip()[:60]}")
    return facts


def _local_roots(repo_root: Path) -> dict[str, Path]:
    """本仓顶层包名 → 所在目录（用于判定「本地模块是否还存在」）。

    只认仓内目录：`backend/` 下的一层包、`backend/libs/*/src/` 下的包、`backend/services/*/` 下的服务包。
    第三方包与标准库不在其中，故不会把 `fastapi` 之类误判成「功能已删除」。
    """
    roots: dict[str, Path] = {}
    backend = repo_root / "backend"
    if not backend.is_dir():
        return roots
    candidates: list[Path] = [path for path in backend.iterdir() if path.is_dir()]
    for lib_src in backend.glob("libs/*/src/*"):
        if lib_src.is_dir():
            candidates.append(lib_src)
    candidates += [path for path in backend.glob("services/*") if path.is_dir()]
    for path in candidates:
        if path.name in {"__pycache__", ".venv"}:
            continue
        if any(path.glob("*.py")):
            roots.setdefault(path.name, path)
    return roots


def _unresolved_imports(tree: ast.Module, local_roots: dict[str, Path], repo_root: Path) -> list[str]:
    """仓内模块解析不到的 import（E 类候选：功能可能已删除）。

    只判本地包：`import a.b.c` / `from a.b import c` 中 `a` 属本仓已知包名时，检查
    `a/b/c.py` 或 `a/b/c/__init__.py` 是否存在。命名空间式的多根布局（同一包名散在多处，
    如产品仓的 `services`）按叶名在仓内再扫一遍，避免误报。
    """
    missing: list[str] = []
    for node in tree.body:
        targets: list[str] = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            targets = [node.module]
        for target in targets:
            parts = target.split(".")
            if parts[0] not in local_roots:
                continue
            module = local_roots[parts[0]].joinpath(*parts[1:])
            if module.with_suffix(".py").is_file() or (module.is_dir() and (module / "__init__.py").is_file()):
                continue
            leaf = parts[-1]
            if any(repo_root.rglob(f"{leaf}.py")) or any(path.is_dir() for path in repo_root.rglob(leaf)):
                continue
            missing.append(target)
    return missing


def _batch_for(repo: str, rel: str) -> int:
    """按工程边界映射批次（与设计 §5 一致）。"""
    if repo == "mdm":
        return 5
    if "libs/bms_core/tests" in rel:
        return 1
    if "services/platform/tests" in rel:
        return 2
    if any(part in rel for part in ("services/tenant/tests", "services/identity/tests", "services/file/tests")):
        return 3
    return 4


def _d_candidate(source: str) -> str:
    """「建库即被测」候选特征（命中关键词即候选，收口时逐条确认）。"""
    hits = [keyword for keyword in _D_KEYWORDS if keyword in source]
    return ", ".join(hits)


def _classify(facts: Facts, source: str) -> tuple[str, str]:
    """按优先级判定类别与依据（E > D > C > B > A）。"""
    if facts.unresolved:
        return "E", "顶层 import 解析不到：" + ", ".join(sorted(set(facts.unresolved)))
    if facts.own_db:
        return "D", f"已有 own_db 白名单（{facts.own_db}）"
    candidate = _d_candidate(source)
    if candidate:
        return "D", f"建库即被测候选（{candidate}），待人工确认"
    if facts.db_build and facts.exact_count:
        return "C", "自建库 + 整表断言：" + "；".join(facts.exact_count[:2])
    if facts.db_build:
        return "B", "自建库：" + "；".join(facts.db_build[:2])
    return "A", "无自建库痕迹"


def scan_repo(repo: str, root: Path, testpaths: list[str]) -> list[Entry]:
    """扫描单个仓库的测试根。"""
    entries: list[Entry] = []
    local_roots = _local_roots(root)
    for testpath in testpaths:
        base = root / testpath
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            rel = path.relative_to(root).as_posix()
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                entries.append(Entry(repo, rel, 0, "E", _batch_for(repo, rel), f"无法解析：{type(exc).__name__}"))
                continue
            facts = _collect_facts(tree, source)
            facts.unresolved = _unresolved_imports(tree, local_roots, root)
            klass, evidence = _classify(facts, source)
            entries.append(Entry(repo, rel, facts.tests, klass, _batch_for(repo, rel), evidence))
    return entries


def render_md(entries: list[Entry]) -> str:
    """渲染台账（Markdown）。"""
    lines = [
        "# 涉库用例改造 A~E 台账",
        "",
        "> 由 `test/scripts/testing/测试库改造台账.py` 生成；改动用例后重新生成即可对账。",
        "",
        "| 批 | 仓 | 文件 | 用例数 | 类 | 处置 | 依据 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for entry in sorted(entries, key=lambda e: (e.batch, e.repo, e.path)):
        cells = [str(entry.batch), entry.repo, f"`{entry.path}`", str(entry.tests), entry.klass, ACTION[entry.klass]]
        cells.append(entry.evidence.replace("|", "\\|"))
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 类 | 文件数 | 用例数 |")
    lines.append("| --- | --- | --- |")
    for klass in CLASS_ORDER:
        subset = [e for e in entries if e.klass == klass]
        lines.append(f"| {klass} | {len(subset)} | {sum(e.tests for e in subset)} |")
    lines.append(f"| 合计 | {len(entries)} | {sum(e.tests for e in entries)} |")
    lines.append("")
    return "\n".join(lines)


def render_json(entries: list[Entry]) -> str:
    """渲染台账（JSON，供 `--check` 对账）。"""
    payload = [
        {
            "repo": entry.repo,
            "path": entry.path,
            "tests": entry.tests,
            "class": entry.klass,
            "action": ACTION[entry.klass],
            "batch": entry.batch,
            "evidence": entry.evidence,
        }
        for entry in sorted(entries, key=lambda e: (e.batch, e.repo, e.path))
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def check_drift(entries: list[Entry], ledger_path: Path) -> int:
    """对账：输出台账与当前代码的类别漂移（返回条数）。"""
    baseline = {(item["repo"], item["path"]): item for item in json.loads(ledger_path.read_text(encoding="utf-8"))}
    current = {(entry.repo, entry.path): entry for entry in entries}
    drift = 0
    for key in sorted(set(baseline) | set(current)):
        before = baseline.get(key)
        now = current.get(key)
        if before and now and before["class"] == now.klass:
            continue
        drift += 1
        was = before["class"] if before else "（新文件）"
        print(f"[漂移] {key[0]}:{key[1]} 台账 {was} → 现状 {now.klass if now else '（已删除）'}")
    print(f"[台账对账] 漂移 {drift} 项（共 {len(current)} 个文件）")
    return drift


def main(argv: list[str] | None = None) -> int:
    """入口。

    Args:
        argv: 命令行参数（缺省取 `sys.argv[1:]`）。

    Returns:
        int: 退出码（0 无漂移 / 1 有漂移 / 2 参数错误）。
    """
    workspace = Path(__file__).resolve().parents[3]
    parser = argparse.ArgumentParser(description="涉库用例 A~E 台账（04-6-2）")
    parser.add_argument("--workspace", default=str(workspace), help="工作区根（缺省按脚本位置推导）")
    parser.add_argument("--out", default="", help="台账输出目录（落任务 实施/）")
    parser.add_argument("--check", default="", help="对账：已有台账 json 路径")
    args = parser.parse_args(argv)

    root = Path(args.workspace)
    bms = root / "bms"
    mdm = root / "mdm"
    entries: list[Entry] = []
    if bms.is_dir():
        entries += scan_repo("bms", bms, ["backend/libs/bms_core/tests", "backend/services"])
    if mdm.is_dir():
        entries += scan_repo("mdm", mdm, ["backend/tests", "backend/services"])
    if not entries:
        print(f"[台账] 未扫描到测试文件（工作区 {root}）")
        return 2

    if args.check:
        return 1 if check_drift(entries, Path(args.check)) else 0

    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "01_实施_01_涉库用例改造台账.md").write_text(render_md(entries), encoding="utf-8")
        payload = render_json(entries)
        (out / "01_实施_01_涉库用例改造台账.json").write_text(payload + "\n", encoding="utf-8")
        print(f"[台账] 已写出：{out / '01_实施_01_涉库用例改造台账.md'}")
    else:
        print(render_md(entries))
    counts = {klass: sum(1 for e in entries if e.klass == klass) for klass in CLASS_ORDER}
    print(f"[台账] 文件 {len(entries)} 个，用例 {sum(e.tests for e in entries)} 个；各类 {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
