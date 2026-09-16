#!/usr/bin/env python3
"""压测场景骨架——复制为 `scenario_<场景>.py` 后填写。

用法::

    cp scenario_template.py scenario_登录.py
    python3 scripts/perf/scenario_登录.py --plan                      # 只打印计划（默认，不施压）
    python3 scripts/perf/scenario_登录.py --plan --users 50 --run-time 3m --host http://<目标>
    python3 scripts/perf/scenario_登录.py --run  --users 50 --host http://<目标>   # 真正施压（需已装 locust）

口径（《测试规范》§2 / §3、本仓 `scripts/perf/README.md`）::

- 命名 `scenario_<场景>.py`；结果 CSV 落 `reports/`（已 gitignore，不入库）。
- **不对生产或常驻服务施压**，目标为本地或专用环境；默认只出计划，`--run` 才真正加压。
- 指标口径：并发用户数、RPS、P95 / P99、失败率；准入阈值见《测试规范》§11
  （MVP 验收前：500 并发 / P99 ≤ 1s）。
- 依赖安装走国内镜像：`pip install locust -i https://mirrors.aliyun.com/pypi/simple`。

填写要点：把 `SCENARIO` 元信息与 `_build_user_class()` 里的任务改成真实链路；
数据准备优先复用 `scripts/data/`（跨模块数据集），单次压测专用数据在 `--plan` 里说明来源。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# 场景元信息：复制后逐项填写（同时作为 --plan 的输出与报告归档的索引）
SCENARIO: dict[str, object] = {
    "name": "<场景名，如 登录链路>",
    "scope": "<覆盖链路一句话>",
    "kiwi": "<关联 Kiwi 用例编号；无则写 —>",
    "endpoints": [
        "<METHOD /path>",
        "<METHOD /path>",
    ],
    "dataset": "<数据准备：scripts/data/ 的数据集名，或造数入口与规模>",
    "thresholds": {"p99_ms": 1000, "failure_rate": 0.01},
}

try:  # locust 只在真正施压时需要；--plan 不依赖它
    from locust import HttpUser, between, task

    _HAS_LOCUST = True
except ImportError:  # pragma: no cover - 骨架在未安装 locust 时仍可出计划
    _HAS_LOCUST = False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"压测场景：{SCENARIO['name']}")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="只打印计划（默认）")
    mode.add_argument("--run", action="store_true", help="真正施压（需已安装 locust）")
    parser.add_argument("--users", type=int, default=50, help="并发用户数（默认 50）")
    parser.add_argument("--spawn-rate", type=float, default=5.0, help="每秒启动用户数（默认 5）")
    parser.add_argument("--run-time", default="3m", help="持续时间，如 3m / 30s（默认 3m）")
    parser.add_argument("--host", default="http://127.0.0.1:8000", help="目标地址（非生产 / 非常驻服务）")
    parser.add_argument("--reports-dir", default="reports", help="结果输出目录（默认 reports/，已 gitignore）")
    return parser.parse_args(argv)


def print_plan(args: argparse.Namespace) -> None:
    thresholds = SCENARIO["thresholds"]
    print(f"场景      ：{SCENARIO['name']}")
    print(f"覆盖链路  ：{SCENARIO['scope']}")
    print(f"Kiwi 用例 ：{SCENARIO['kiwi']}")
    print(f"目标地址  ：{args.host}")
    print(f"并发 / 时长：{args.users} 用户（启动 {args.spawn_rate}/s） / {args.run_time}")
    print(f"数据准备  ：{SCENARIO['dataset']}")
    print(f"准入阈值  ：P99 ≤ {thresholds['p99_ms']} ms，失败率 ≤ {thresholds['failure_rate']:.0%}")
    print("请求清单：")
    for endpoint in SCENARIO["endpoints"]:
        print(f"  - {endpoint}")
    print(f"结果输出  ：{Path(args.reports_dir) / str(SCENARIO['name'])}_stats.csv（--run 时生成）")
    if not _HAS_LOCUST:
        print("提示      ：当前未安装 locust，--run 前请先 `pip install locust -i https://mirrors.aliyun.com/pypi/simple`")


if _HAS_LOCUST:  # 仅装 locust 时定义用户类（locust -f 导入本文件时生效）

    class ScenarioUser(HttpUser):  # type: ignore[misc]
        """压测用户：按 `SCENARIO['endpoints']` 轮询请求（复制后替换为真实业务链路）。"""

        wait_time = between(1, 3)

        @task(1)
        def probe(self) -> None:
            for endpoint in SCENARIO["endpoints"]:  # type: ignore[union-attr]
                method, path = str(endpoint).split(" ", 1)
                self.client.request(method, path, name=path)


def run_locust(args: argparse.Namespace) -> int:
    if not _HAS_LOCUST:
        print(
            "未安装 locust：pip install locust -i https://mirrors.aliyun.com/pypi/simple",
            file=sys.stderr,
        )
        return 2
    reports = Path(args.reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "locust",
        "-f",
        str(Path(__file__).resolve()),
        "--headless",
        "-u",
        str(args.users),
        "-r",
        str(args.spawn_rate),
        "-t",
        args.run_time,
        "--host",
        args.host,
        "--csv",
        str(reports / str(SCENARIO["name"])),
    ]
    print("执行：", " ".join(cmd))
    return subprocess.run(cmd, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.run:
        return run_locust(args)
    print_plan(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
