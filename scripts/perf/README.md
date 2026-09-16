# 压测场景

> `scenario_场景.py` 形态的压测脚本

## 1. 口径

- 命名：`scenario_<场景>.py`（如 `scenario_登录.py`），见《[测试规范](../../bms文档/规范/测试规范.md)》§3 命名表。
- 输出位置：`reports/`（已 gitignore），不入库。
- 压测不对生产/常驻服务执行，目标为本地或专用环境。

## 2. 场景骨架 <a id="template"></a>

`scenario_template.py` 是标准骨架（**默认只出计划，`--run` 才施压**）：

```bash
cp scenario_template.py scenario_登录.py                              # 复制后改场景名与链路
python3 scripts/perf/scenario_登录.py --plan --host http://<目标>      # 打印计划（不施压，无需 locust）
python3 scripts/perf/scenario_登录.py --run --users 50 --host http://<目标>   # 真正施压（需装 locust）
```

骨架固化的口径：场景元信息（链路 / 关联 Kiwi 编号 / 数据准备 / 准入阈值）、请求清单逐条可见、
结果 CSV 落 `reports/`、locust 延迟导入（未装也能出计划）、安装走阿里云镜像。
**复制后必改**：`SCENARIO` 四项元信息与 `ScenarioUser.probe` 的真实链路。

## 3. 待办

| # | 待办 |
| --- | --- |
| 1 | ~~落地场景骨架与执行入口~~ **已完成 2026-09-16**（`scenario_template.py`：计划 / 施压双模式、指标与阈值口径） |
| 2 | 落地首个**真实**场景（登录链路，需登录与验证码链路就绪：阶段六）并录指标基线 |

> 依《文档生成规范》编写 · 测试资产仓库
