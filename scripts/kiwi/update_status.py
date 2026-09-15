#!/usr/bin/env python3
"""批量维护 Kiwi 用例的状态 / 优先级 / 标签。

用法::

    # 按编号（可多次给，或逗号分隔）
    python3 scripts/kiwi/update_status.py --ids 66,67 --status CONFIRMED
    # 按产品批量（配合 --tag 追加标签）
    python3 scripts/kiwi/update_status.py --product "BMS 基础管理系统" --priority P2 --tag 自动化
    python3 scripts/kiwi/update_status.py --ids 66 --status CONFIRMED --dry-run

未给任何修改项（--status / --priority / --tag）时只做查询，不改数据（核对场景常用）。
退出码：0 成功；1 执行失败；2 参数/环境错误。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def parse_ids(raw: list[str] | None) -> list[int]:
    ids: list[int] = []
    for chunk in raw or []:
        for part in chunk.replace(" ", "").split(","):
            if part:
                ids.append(int(part))
    return ids


def build_shell_code(ids: list[int], product: str | None, status: str | None, priority: str | None,
                     tags: list[str], remove_tag: bool) -> str:
    payload = {
        "ids": ids,
        "product": product,
        "status": status,
        "priority": priority,
        "tags": tags,
        "remove_tag": remove_tag,
    }
    return f'''import json
from tcms.management.models import Priority, Tag
from tcms.testcases.models import TestCase, TestCaseStatus

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))})
qs = TestCase.objects.all()
if payload["ids"]:
    qs = qs.filter(pk__in=payload["ids"])
elif payload["product"]:
    qs = qs.filter(category__product__name=payload["product"])
else:
    raise SystemExit("ERR: 必须给 --ids 或 --product，避免全表误改")

changed = []
for case in qs.order_by("pk"):
    before = (case.case_status.name, case.priority.value)
    if payload["status"]:
        case.case_status = TestCaseStatus.objects.get(name=payload["status"])
    if payload["priority"]:
        case.priority = Priority.objects.get(value=payload["priority"])
    if payload["status"] or payload["priority"]:
        case.save()
    for name in payload["tags"]:
        tag, _ = Tag.objects.get_or_create(name=name)
        if payload["remove_tag"]:
            case.remove_tag(tag)
        else:
            case.add_tag(tag)
    changed.append({{
        "case_id": case.pk,
        "before": before,
        "after": (case.case_status.name, case.priority.value),
        "summary": case.summary,
    }})
print("RESULT_JSON" + json.dumps(changed, ensure_ascii=False))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="批量维护 Kiwi 用例状态 / 优先级 / 标签")
    parser.add_argument("--ids", action="append", help="用例编号（逗号分隔，可重复给）")
    parser.add_argument("--product", help="按产品名批量（与 --ids 二选一，必填其一）")
    parser.add_argument("--status", help="目标状态名，如 CONFIRMED")
    parser.add_argument("--priority", help="目标优先级 value，如 P2")
    parser.add_argument("--tag", action="append", help="标签名（可重复给）")
    parser.add_argument("--remove-tag", action="store_true", help="改为删除标签")
    parser.add_argument("--host", default=os.environ.get("MJBK_IP"))
    parser.add_argument("--user", default=os.environ.get("MJBK_SSH_USER"))
    parser.add_argument("--container", default="bms-kiwi")
    parser.add_argument("--dry-run", action="store_true", help="只打印容器内代码，不执行")
    args = parser.parse_args(argv)

    ids = parse_ids(args.ids)
    if not ids and not args.product:
        print("必须给 --ids 或 --product（避免全表误改）", file=sys.stderr)
        return 2
    if not (args.status or args.priority or args.tag):
        print("提示：未给任何修改项，本次只做查询与回显（不会改数据）")

    code = build_shell_code(ids, args.product, args.status, args.priority, args.tag or [], args.remove_tag)
    if args.dry_run:
        print(code)
        return 0
    if not args.host or not args.user:
        print("缺少主机或用户：用 --host/--user 指定，或设置 MJBK_IP / MJBK_SSH_USER", file=sys.stderr)
        return 2

    rc, out = run_remote(code, args.host, args.user, args.container)
    marker = [line for line in out.splitlines() if line.startswith("RESULT_JSON")]
    if rc != 0 or not marker:
        print(f"执行失败（退出码 {rc}）：\n{out[-2000:]}", file=sys.stderr)
        return 1

    rows = json.loads(marker[-1][len("RESULT_JSON") :])
    for row in rows:
        flag = "改" if row["before"] != row["after"] else "查"
        print(f"  {flag}  {row['case_id']:>6}  {row['after'][0]}/{row['after'][1]}  {row['summary'][:56]}")
    print(f"合计 {len(rows)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
