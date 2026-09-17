#!/usr/bin/env python3
"""批量更新 Kiwi 用例正文（text），按用例标题（summary）匹配并回读改前 / 改后。

走 mjbk 上 Kiwi 容器的 Django shell（脚本经 stdin 传入，不落盘进容器）：
`ssh <user>@<host> "docker exec -i <container> python manage.py shell"`。

用法::

    python3 scripts/kiwi/update_case_text.py --file cases/2026-09-16_阶段四02-02_组件根基类.json --dry-run
    python3 scripts/kiwi/update_case_text.py --file cases/2026-09-16_阶段四02-02_组件根基类.json

输入 JSON 为登记输入文件格式（``cases`` 数组，取 ``summary`` + ``text``）：

    {
      "product": "BMS 基础管理系统",
      "cases": [ { "summary": "用例标题（平台内唯一，按此匹配）", "text": "<p>…</p>" } ]
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


def build_shell_code(cases: list[dict]) -> str:
    payload = {"cases": cases}
    return f'''import json
from tcms.testcases.models import TestCase

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))})
if not payload["cases"]:
    raise SystemExit("ERR: 更新清单为空")

changed = []
for item in payload["cases"]:
    qs = TestCase.objects.filter(summary=item["summary"])
    if qs.count() != 1:
        raise SystemExit(f"ERR: 标题「{{item['summary']}}」匹配到 {{qs.count()}} 条（需唯一）")
    case = qs.get()
    before = case.text
    if before != item["text"]:
        case.text = item["text"]
        case.save()
    changed.append({{
        "case_id": case.pk,
        "summary": case.summary,
        "changed": before != case.text,
        "text_len": len(case.text or ""),
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
    parser = argparse.ArgumentParser(description="批量更新 Kiwi 用例正文（按标题匹配）")
    parser.add_argument("--file", required=True, help="登记输入 JSON（cases: [{summary, text}]）")
    parser.add_argument("--host", default=os.environ.get("MJBK_IP"))
    parser.add_argument("--user", default=os.environ.get("MJBK_SSH_USER"))
    parser.add_argument("--container", default="bms-kiwi")
    parser.add_argument("--dry-run", action="store_true", help="只打印容器内代码，不执行")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    cases = [{"summary": c["summary"], "text": c["text"]} for c in data.get("cases", []) if c.get("summary") and c.get("text")]
    if not cases:
        print("更新清单为空：检查 --file 内容（cases 数组，需含 summary / text）", file=sys.stderr)
        return 2

    code = build_shell_code(cases)
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
        flag = "改" if row["changed"] else "查"
        print(f"  {flag}  {row['case_id']:>6}  text={row['text_len']}  {row['summary'][:56]}")
    print(f"合计 {len(rows)} 条（改 {sum(1 for r in rows if r['changed'])}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
