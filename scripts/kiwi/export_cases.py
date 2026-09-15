#!/usr/bin/env python3
"""导出 Kiwi 用例清单，用于与代码里的 `@pytest.mark.kiwi_id` 交叉对账。

用法::

    # 导出策展用例库（默认）为 JSON
    python3 scripts/kiwi/export_cases.py --out cases.json
    # 导出为 CSV
    python3 scripts/kiwi/export_cases.py --format csv --out cases.csv
    # 与代码里的 kiwi_id 对账（在 backend 目录或给定 --code-root 下 grep）
    python3 scripts/kiwi/export_cases.py --reconcile --code-root ../bms/backend
    # 只看某个产品（如 CI 自动用例产品）
    python3 scripts/kiwi/export_cases.py --product "BMS 自动化用例（CI）" --limit 20

对账口径：代码用 `@pytest.mark.kiwi_id(N)` 关联用例；报告分三类——
`only_code`（代码引用了但平台没有）、`only_platform`（平台有但代码未引用）、`matched`（两边一致）。
退出码：0 成功；1 执行失败；2 参数/环境错误。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

KIWI_ID_RE = re.compile(r"kiwi_id\(\s*(\d+)\s*\)")
DEFAULT_PRODUCT = "BMS 基础管理系统"


def build_shell_code(product: str, limit: int) -> str:
    payload = {"product": product, "limit": limit}
    return f'''import json
from tcms.testcases.models import TestCase

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))})
qs = TestCase.objects.filter(category__product__name=payload["product"]).order_by("pk")
rows = []
for case in qs[: payload["limit"]]:
    rows.append({{
        "case_id": case.pk,
        "summary": case.summary,
        "category": case.category.name,
        "priority": case.priority.value,
        "status": case.case_status.name,
        "is_automated": case.is_automated,
        "tags": sorted(t.name for t in case.tag.all()),
    }})
print("RESULT_JSON" + json.dumps(rows, ensure_ascii=False))
'''


def run_remote(code: str, host: str, user: str, container: str) -> tuple[int, str]:
    cmd = [
        "ssh",
        "-o",
        "BatchMode=yes",
        f"{user}@{host}",
        f"docker exec -i {container} python manage.py shell",
    ]
    proc = subprocess.run(cmd, input=code, capture_output=True, text=True, check=False)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def scan_code_kiwi_ids(code_root: Path) -> set[int]:
    ids: set[int] = set()
    for path in code_root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        ids.update(int(m.group(1)) for m in KIWI_ID_RE.finditer(path.read_text(encoding="utf-8", errors="ignore")))
    return ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出 Kiwi 用例清单并与代码 kiwi_id 对账")
    parser.add_argument("--product", default=DEFAULT_PRODUCT, help=f"产品名（默认 {DEFAULT_PRODUCT}）")
    parser.add_argument("--limit", type=int, default=5000, help="导出条数上限（默认 5000）")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--out", help="输出文件（不给则打印到标准输出）")
    parser.add_argument("--reconcile", action="store_true", help="执行与代码的对账")
    parser.add_argument("--code-root", default=".", help="代码根目录（对账时扫描 .py，默认当前目录）")
    parser.add_argument("--host", default=os.environ.get("MJBK_IP"))
    parser.add_argument("--user", default=os.environ.get("MJBK_SSH_USER"))
    parser.add_argument("--container", default="bms-kiwi")
    args = parser.parse_args(argv)

    if not args.host or not args.user:
        print("缺少主机或用户：用 --host/--user 指定，或设置 MJBK_IP / MJBK_SSH_USER", file=sys.stderr)
        return 2

    code = build_shell_code(args.product, args.limit)
    rc, out = run_remote(code, args.host, args.user, args.container)
    marker = [line for line in out.splitlines() if line.startswith("RESULT_JSON")]
    if rc != 0 or not marker:
        print(f"执行失败（退出码 {rc}）：\n{out[-2000:]}", file=sys.stderr)
        return 1
    rows = json.loads(marker[-1][len("RESULT_JSON") :])

    if args.reconcile:
        platform_ids = {row["case_id"] for row in rows}
        code_ids = scan_code_kiwi_ids(Path(args.code_root))
        only_code = sorted(code_ids - platform_ids)
        only_platform = sorted(platform_ids - code_ids)
        print(f"平台用例 {len(platform_ids)} 条，代码引用 kiwi_id {len(code_ids)} 个")
        print(f"  matched(两边都有)  {len(code_ids & platform_ids)}")
        print(f"  only_code(平台缺)  {only_code[:50]}{' …' if len(only_code) > 50 else ''}")
        print(f"  only_platform(代码未引用)  {len(only_platform)} 条（自动用例产品属预期）")

    if args.out:
        target = Path(args.out)
        if args.format == "json":
            target.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            with target.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["case_id"])
                writer.writeheader()
                writer.writerows(rows)
        print(f"已导出 {len(rows)} 条 → {target}")
    elif not args.reconcile:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
