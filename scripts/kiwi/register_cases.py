#!/usr/bin/env python3
"""批量登记 Kiwi 用例，并回读平台分配的**实际编号**。

登记走 mjbk 上 Kiwi 容器的 Django shell（脚本经 stdin 传入，不落盘进容器）：
`ssh <user>@<host> "docker exec -i <container> python manage.py shell"`。

用法::

    python3 scripts/kiwi/register_cases.py --file cases.json
    python3 scripts/kiwi/register_cases.py --file cases.json --out result.json
    python3 scripts/kiwi/register_cases.py --file cases.json --dry-run   # 只打印将要执行的代码

输入 JSON（``cases`` 数组；未给字段按下列默认补齐）::

    {
      "product": "BMS 基础管理系统",
      "cases": [
        {
          "summary": "用例标题（平台内按此去重）",
          "text": "<p>前置 / 步骤 / 预期</p>",
          "category": "平台骨架",
          "priority": "P2",
          "status": "CONFIRMED",
          "author": "admin",
          "tags": ["自动化"],
          "is_automated": true
        }
      ]
    }

**要点**：Kiwi 用例编号是**平台全局自增且跨产品共享**（自动用例产品会占用大量编号），
因此新登记的策展用例编号会跳号——务必以脚本回读的 ``case_id`` 为准，不要假设连续。

退出码：0 全部成功（含跳过）；1 存在失败；2 参数/环境错误。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PRODUCT = "BMS 基础管理系统"
DEFAULT_CATEGORY = "平台骨架"
DEFAULT_PRIORITY = "P2"
DEFAULT_STATUS = "CONFIRMED"
DEFAULT_AUTHOR = "admin"
DEFAULT_TAG = "自动化"


def build_shell_code(payload: dict) -> str:
    """生成容器内执行的 Python 代码（只读 payload，不拼接用户输入到可执行结构之外）。"""
    return f'''import json, sys
from django.contrib.auth.models import User
from tcms.management.models import Product, Priority
from tcms.testcases.models import TestCase, Category, TestCaseStatus
from tcms.management.models import Tag

payload = json.loads({json.dumps(json.dumps(payload, ensure_ascii=False))})
product = Product.objects.get(name=payload.get("product") or "{DEFAULT_PRODUCT}")
results = []
for item in payload.get("cases", []):
    summary = item["summary"]
    try:
        exist = TestCase.objects.filter(summary=summary).first()
        if exist:
            results.append({{"ok": True, "skipped": True, "case_id": exist.pk, "summary": summary}})
            continue
        category = Category.objects.filter(product=product, name=item.get("category") or "{DEFAULT_CATEGORY}").first()
        if category is None:
            category = Category.objects.filter(product=product).first()
        priority = Priority.objects.filter(value=item.get("priority") or "{DEFAULT_PRIORITY}").first() \\
            or Priority.objects.first()
        status = TestCaseStatus.objects.filter(name=item.get("status") or "{DEFAULT_STATUS}").first() \\
            or TestCaseStatus.objects.first()
        author = User.objects.filter(username=item.get("author") or "{DEFAULT_AUTHOR}").first() \\
            or User.objects.filter(is_superuser=True).first()
        case = TestCase.objects.create(
            summary=summary,
            text=item.get("text", ""),
            category=category,
            priority=priority,
            case_status=status,
            author=author,
            is_automated=bool(item.get("is_automated", False)),
        )
        for name in item.get("tags") or ["{DEFAULT_TAG}"]:
            tag, _ = Tag.objects.get_or_create(name=name)
            case.add_tag(tag)
        results.append({{"ok": True, "skipped": False, "case_id": case.pk, "summary": summary}})
    except Exception as exc:  # 单条失败不中断整批
        results.append({{"ok": False, "skipped": False, "case_id": None, "summary": summary, "error": str(exc)}})
print("RESULT_JSON" + json.dumps(results, ensure_ascii=False))
'''


def run_remote(code: str, host: str, user: str, container: str) -> tuple[int, str]:
    """把容器内代码经 stdin 灌进 Django shell。"""
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
    parser = argparse.ArgumentParser(description="批量登记 Kiwi 用例并回读编号")
    parser.add_argument("--file", required=True, help="用例 JSON 文件")
    parser.add_argument("--out", help="结果落盘 JSON（含平台回读的 case_id）")
    parser.add_argument("--host", default=os.environ.get("MJBK_IP"), help="mjbk 主机（默认读 MJBK_IP）")
    parser.add_argument("--user", default=os.environ.get("MJBK_SSH_USER"), help="SSH 用户（默认读 MJBK_SSH_USER）")
    parser.add_argument("--container", default="bms-kiwi", help="Kiwi 容器名（默认 bms-kiwi）")
    parser.add_argument("--product", help=f"覆盖 JSON 中的产品名（默认 {DEFAULT_PRODUCT}）")
    parser.add_argument("--dry-run", action="store_true", help="只打印容器内代码，不执行")
    args = parser.parse_args(argv)

    src = Path(args.file)
    if not src.is_file():
        print(f"用例文件不存在：{src}", file=sys.stderr)
        return 2
    payload = json.loads(src.read_text(encoding="utf-8"))
    if args.product:
        payload["product"] = args.product
    if not payload.get("cases"):
        print("用例文件里没有 cases", file=sys.stderr)
        return 2

    code = build_shell_code(payload)
    if args.dry_run:
        print(code)
        return 0

    if not args.host or not args.user:
        print("缺少主机或用户：用 --host/--user 指定，或设置 MJBK_IP / MJBK_SSH_USER", file=sys.stderr)
        return 2

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as tmp:
        tmp.write(code)
        tmp_path = tmp.name
    try:
        rc, out = run_remote(Path(tmp_path).read_text(encoding="utf-8"), args.host, args.user, args.container)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    marker = [line for line in out.splitlines() if line.startswith("RESULT_JSON")]
    if rc != 0 or not marker:
        print(f"执行失败（退出码 {rc}）：\n{out[-2000:]}", file=sys.stderr)
        return 1

    results = json.loads(marker[-1][len("RESULT_JSON") :])
    created = [r for r in results if r["ok"] and not r["skipped"]]
    skipped = [r for r in results if r["skipped"]]
    failed = [r for r in results if not r["ok"]]
    for r in created:
        print(f"  新建  {r['case_id']:>6}  {r['summary'][:60]}")
    for r in skipped:
        print(f"  跳过  {r['case_id']:>6}  {r['summary'][:60]}（同名已存在）")
    for r in failed:
        print(f"  失败  {'-':>6}  {r['summary'][:60]}：{r.get('error')}", file=sys.stderr)
    print(f"合计：新建 {len(created)}、跳过 {len(skipped)}、失败 {len(failed)}")

    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
