#!/usr/bin/env python3
"""批量改名 Kiwi 用例标题（summary），并回读改前 / 改后。

登记与查询走 mjbk 上 Kiwi 容器的 Django shell（脚本经 stdin 传入，不落盘进容器）：
`ssh <user>@<host> "docker exec -i <container> python manage.py shell"`。

用法::

    python3 scripts/kiwi/rename_cases.py --file cases/2026-09-17_标题对齐改名.json --dry-run
    python3 scripts/kiwi/rename_cases.py --file cases/2026-09-17_标题对齐改名.json

输入 JSON::

    {
      "renames": [
        { "id": 699, "summary": "阶段四 02-01 根系基类（frontend/apps/mobile）：同接口多实现一致性" }
      ]
    }

退出码：0 成功；1 执行失败；2 参数/环境错误。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def build_shell_code(renames: list[dict]) -> str:
    payload = {"renames": renames}
    return f'''import json
from tcms.testcases.models import TestCase

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))})
if not payload["renames"]:
    raise SystemExit("ERR: 改名清单为空")

changed = []
for item in payload["renames"]:
    case = TestCase.objects.get(pk=item["id"])
    before = case.summary
    if before != item["summary"]:
        case.summary = item["summary"]
        case.save()
    changed.append({{
        "case_id": case.pk,
        "before": before,
        "after": case.summary,
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
    parser = argparse.ArgumentParser(description="批量改名 Kiwi 用例标题（summary）")
    parser.add_argument("--file", required=True, help="改名清单 JSON（renames: [{id, summary}]）")
    parser.add_argument("--host", default=os.environ.get("MJBK_IP"))
    parser.add_argument("--user", default=os.environ.get("MJBK_SSH_USER"))
    parser.add_argument("--container", default="bms-kiwi")
    parser.add_argument("--dry-run", action="store_true", help="只打印容器内代码，不执行")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    renames = data.get("renames", [])
    if not renames:
        print("改名清单为空：检查 --file 内容（renames 数组）", file=sys.stderr)
        return 2

    code = build_shell_code(renames)
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
        print(f"  {flag}  {row['case_id']:>6}")
        print(f"        前: {row['before']}")
        print(f"        后: {row['after']}")
    print(f"合计 {len(rows)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
