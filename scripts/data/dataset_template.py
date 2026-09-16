#!/usr/bin/env python3
"""测试数据集骨架——复制为 `dataset_<数据集>.py` 后填写。

用法::

    cp dataset_template.py dataset_组织与用户.py
    python3 scripts/data/dataset_组织与用户.py --list              # 列出数据集与规模
    python3 scripts/data/dataset_组织与用户.py --plan              # 只打印写入计划（默认，不落库）
    python3 scripts/data/dataset_组织与用户.py --apply --confirm   # 真正写入（需接入连接与造数逻辑）

口径（本仓 `scripts/data/README.md`、《测试规范》§7）::

- 本目录放**跨模块 / 可复用**的数据集构造；单次单测用的 fixture 仍随测试代码（`backend/tests/`）。
- 三库方言差异（MySQL / PostgreSQL / 达梦）按《测试规范》§7 口径准备；不把方言写在数据集定义里。
- **默认只出计划**：`--apply` 必须显式 `--confirm`（破坏性操作带确认，见本仓 `scripts/README.md` 通用约定）。
- 连接与凭据从环境变量读（如 `BMS_DATABASE__PLATFORM__URL`），**不硬编码、不入库**。
- 真实数据须脱敏后入库；敏感值只从环境变量注入，文档与代码里只写变量名。
"""

from __future__ import annotations

import argparse
import os
import sys

# 数据集定义：表名 → 行（声明式，便于 --plan 逐条打印；复制后填真实结构）
DATASETS: dict[str, list[dict[str, object]]] = {
    "<表名，如 sys_tenant>": [
        {"<字段>": "<占位值>", "<字段>": "<占位值>"},
    ],
    "<表名，如 sys_user>": [
        {"<字段>": "<占位值>"},
    ],
}

# 数据集元信息：规模、依赖、清理策略、脱敏说明
META: dict[str, object] = {
    "name": "<数据集名>",
    "purpose": "<用途：哪类测试 / 哪个阶段任务需要它>",
    "depends_on": ["<依赖服务，如 MySQL 平台库>"],
    "cleanup": "<清理策略：跑完即删 / 命名前缀批量清理 / 幂等 upsert>",
    "sensitive": "<脱敏说明：哪些字段是脱敏值、真实值从哪个环境变量注入>",
}

# 写入所需的环境变量（只写变量名，便于 --plan 提示缺项）
REQUIRED_ENV = ["BMS_DATABASE__PLATFORM__URL"]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"测试数据集：{META['name']}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="列出数据集与规模")
    mode.add_argument("--plan", action="store_true", help="只打印写入计划（默认）")
    mode.add_argument("--apply", action="store_true", help="真正写入（必须同时给 --confirm）")
    parser.add_argument("--confirm", action="store_true", help="确认执行破坏性写入")
    return parser.parse_args(argv)


def print_list() -> None:
    total = sum(len(rows) for rows in DATASETS.values())
    print(f"数据集：{META['name']}（{len(DATASETS)} 张表 / {total} 行）")
    for table, rows in DATASETS.items():
        print(f"  - {table}: {len(rows)} 行")


def print_plan() -> int:
    print(f"数据集    ：{META['name']}")
    print(f"用途      ：{META['purpose']}")
    print(f"依赖服务  ：{', '.join(META['depends_on'])}")
    print(f"清理策略  ：{META['cleanup']}")
    print(f"脱敏说明  ：{META['sensitive']}")
    missing = [key for key in REQUIRED_ENV if not os.environ.get(key)]
    print(f"环境变量  ：{', '.join(REQUIRED_ENV)}" + (f"（缺：{', '.join(missing)}）" if missing else "（已就绪）"))
    print("写入计划：")
    for table, rows in DATASETS.items():
        print(f"  - {table}：{len(rows)} 行 → 字段 {', '.join(rows[0].keys()) if rows else '—'}")
    print("说明      ：本骨架不落库；接入连接与造数逻辑后再用 `--apply --confirm` 执行。")
    return 0


def apply_dataset() -> int:
    # TODO: 在此接入连接（从 REQUIRED_ENV 读取）与幂等写入逻辑（按 cleanup 策略）
    print("骨架未实现写入：请先接入连接与造数逻辑（见本文件 apply_dataset 的 TODO）", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list:
        print_list()
        return 0
    if args.apply:
        if not args.confirm:
            print("拒绝执行：--apply 需同时显式给 --confirm（破坏性写入）", file=sys.stderr)
            return 2
        return apply_dataset()
    return print_plan()


if __name__ == "__main__":
    raise SystemExit(main())
