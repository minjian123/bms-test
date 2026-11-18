#!/usr/bin/env python3
"""主链路压测场景：异步副作用（操作日志 / 字段级审计）对写接口 P99 的影响。

口径（任务 15_01 / 需求 11-1）：
- 同一端点（`POST /api/v1/roles`，命中操作日志中间件 + `sys_role` 字段级审计白名单）；
- 固定并发（缺省 32）、固定请求数（缺省 2000）、固定数据集（每次运行按唯一角色码建 2000 条）；
- 三档配置由**服务端**决定（审计全关 / 仅操作日志 / 全开），本脚本只负责施压与出数：
  A 全关  `BMS_AUDIT_LOG__ENABLED=false` + `BMS_AUDIT_CAPTURE__ENABLED=false`
  B 仅操作日志 `audit_log.enabled=true` + `audit_capture.enabled=false`
  C 全开  两者 `true`（缺省）
- 只测**客户端观测时延**（请求发出到响应体读完）；操作日志在响应后发射，本口径天然不含该段。

用法::

    python3 scripts/perf/scenario_异步链路.py --plan
    python3 scripts/perf/scenario_异步链路.py --run --host http://127.0.0.4:8000 \
        --account perf_admin --password '***' --tenant demo --label A

结果：JSON 落 `reports/`（已忽略）或 `--out` 指定路径，stdout 同时打印摘要。
只依赖标准库（无 locust / httpx 依赖）。
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import os
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit

SCENARIO = "异步链路容量与延迟（主链路三档对比）"
KIWI = 2531
TARGET_PATH = "/api/v1/roles"
DEFAULT_HOST = "http://127.0.0.4:8000"
DEFAULT_CONCURRENCY = 32
DEFAULT_REQUESTS = 2000
DEFAULT_WARMUP = 100
DEFAULT_TIMEOUT = 15.0


def percentile(samples: list[float], ratio: float) -> float:
    """取分位值（毫秒）。"""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * ratio) - 1))
    return round(ordered[index], 2)


class Client:
    """单线程 HTTP 客户端（复用连接，避免建连开销掩盖差异）。"""

    def __init__(self, host: str, timeout: float) -> None:
        parts = urlsplit(host)
        self._https = parts.scheme == "https"
        self._host = parts.hostname or "127.0.0.4"
        self._port = parts.port or (443 if self._https else 80)
        self._timeout = timeout
        self._conn: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        if self._conn is None:
            klass = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
            self._conn = klass(self._host, self._port, timeout=self._timeout)
        return self._conn

    def request(self, method: str, path: str, *, body: object | None = None, token: str = "") -> tuple[int, dict]:
        """发一次请求，返回（状态码, JSON）。连接异常时重建连接并抛给调用方。"""
        payload = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Accept": "application/json", "Connection": "keep-alive"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conn = self._connect()
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            status = response.status
        except (OSError, http.client.HTTPException):
            self.close()
            raise
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            data = {"raw": raw[:200].decode("utf-8", "replace")}
        return status, data

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def login(client: Client, account: str, password: str, tenant: str) -> str:
    """登录取 access token（失败即抛错，不静默继续）。"""
    status, data = client.request(
        "POST", "/api/v1/auth/login", body={"account": account, "password": password, "tenant": tenant}
    )
    if status != 200 or data.get("code") != 0:
        raise SystemExit(f"登录失败：HTTP {status} {data}")
    token = (data.get("data") or {}).get("access_token") or ""
    if not token:
        raise SystemExit(f"登录响应缺少 access_token：{data}")
    return token


def role_body(index: int, label: str, run_id: str) -> dict:
    """构造一条唯一的角色创建请求（角色码租户内唯一）。"""
    return {"code": f"perf_{label}_{run_id}_{index}", "name": f"压测角色 {label}-{index}"}


def run(args: argparse.Namespace) -> int:
    """执行压测并输出结果 JSON。"""
    run_id = f"{int(time.time()):x}"
    client = Client(args.host, args.timeout)
    auth = Client(args.auth_host or args.host, args.timeout)
    token = login(auth, args.account, args.password, args.tenant)
    auth.close()
    label = args.label or "X"

    for index in range(args.warmup):
        status, data = client.request("POST", TARGET_PATH, body=role_body(index, f"w{label}", run_id), token=token)
        if status != 200 or data.get("code") != 0:
            raise SystemExit(f"预热失败：HTTP {status} {data}")

    latencies: list[float] = []
    statuses: dict[int, int] = {}
    errors: list[str] = []
    lock = threading.Lock()
    counter = {"next": args.warmup}
    started = time.perf_counter()

    def worker() -> None:
        local = Client(args.host, args.timeout)
        local_token = token
        while True:
            with lock:
                index = counter["next"]
                if index >= args.warmup + args.requests:
                    break
                counter["next"] = index + 1
            begin = time.perf_counter()
            try:
                status, data = local.request(
                    "POST", TARGET_PATH, body=role_body(index, label, run_id), token=local_token
                )
            except Exception as exc:  # 连接异常计入错误，不中断整轮
                with lock:
                    errors.append(f"{type(exc).__name__}: {exc}")
                    statuses[0] = statuses.get(0, 0) + 1
                continue
            elapsed = (time.perf_counter() - begin) * 1000
            with lock:
                latencies.append(elapsed)
                statuses[status] = statuses.get(status, 0) + 1
                if status != 200 or data.get("code") != 0:
                    errors.append(f"HTTP {status} {str(data)[:160]}")
        local.close()

    threads = [threading.Thread(target=worker) for _ in range(args.concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed_total = time.perf_counter() - started
    client.close()

    total = len(latencies)
    report = {
        "scenario": SCENARIO,
        "kiwi": KIWI,
        "label": label,
        "host": args.host,
        "auth_host": args.auth_host or args.host,
        "target": TARGET_PATH,
        "tenant": args.tenant,
        "concurrency": args.concurrency,
        "requests": args.requests,
        "warmup": args.warmup,
        "run_id": run_id,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ok": total - len(errors),
        "errors": len(errors),
        "error_samples": errors[:5],
        "status_counts": {str(key): value for key, value in sorted(statuses.items())},
        "elapsed_seconds": round(elapsed_total, 2),
        "qps": round(total / elapsed_total, 1) if elapsed_total > 0 else 0.0,
        "p50_ms": percentile(latencies, 0.5),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": round(max(latencies), 2) if latencies else 0.0,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return 0 if report["errors"] == 0 else 1


def plan(args: argparse.Namespace) -> int:
    """打印压测计划（不施压）。"""
    print(
        json.dumps(
            {
                "scenario": SCENARIO,
                "kiwi": KIWI,
                "host": args.host,
                "auth_host": args.auth_host or args.host,
                "target": TARGET_PATH,
                "account": args.account,
                "tenant": args.tenant,
                "concurrency": args.concurrency,
                "requests": args.requests,
                "warmup": args.warmup,
                "label": args.label or "X",
                "config_switch": {
                    "A": "BMS_AUDIT_LOG__ENABLED=false + BMS_AUDIT_CAPTURE__ENABLED=false",
                    "B": "BMS_AUDIT_LOG__ENABLED=true + BMS_AUDIT_CAPTURE__ENABLED=false",
                    "C": "两者 true（缺省）",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=SCENARIO)
    parser.add_argument("--plan", action="store_true", help="只打印计划（不施压，缺省行为）")
    parser.add_argument("--run", action="store_true", help="真正施压")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"业务服务基址（缺省 {DEFAULT_HOST}）")
    parser.add_argument(
        "--auth-host", default="", help="认证服务基址（缺省同 --host；本机全套为 http://127.0.0.5:8000）"
    )
    parser.add_argument("--account", default="perf_admin", help="登录账号")
    parser.add_argument("--password", default="", help="登录口令（必填；不写入任何文件）")
    parser.add_argument("--tenant", default="demo", help="租户编码")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="固定并发")
    parser.add_argument("--requests", type=int, default=DEFAULT_REQUESTS, help="固定请求数")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP, help="预热请求数")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="单请求超时（秒）")
    parser.add_argument("--label", default="", help="档位标签（A / B / C）")
    parser.add_argument("--out", default="", help="结果 JSON 落盘路径")
    args = parser.parse_args()
    if not args.run:
        return plan(args)
    if not args.password:
        parser.error("--run 需要 --password（口令不入库、不写文件）")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
