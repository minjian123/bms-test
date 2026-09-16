# 测试数据生成

> 测试数据集构造与环境准备

## 1. 口径

- 测试数据与工程测试数据（`backend/tests/`）分工：本目录放**跨模块/可复用的数据集构造**，
  单次单测用的 fixture 仍随测试代码。
- 涉及三库方言（MySQL / PostgreSQL / 达梦）的数据准备，方言差异口径见
  《[测试规范](../../bms文档/规范/测试规范.md)》§7。

## 2. 数据集骨架 <a id="template"></a>

`dataset_template.py` 是标准骨架（**默认只出计划，`--apply` 必须显式 `--confirm`**）：

```bash
cp dataset_template.py dataset_组织与用户.py         # 复制后填表结构与元信息
python3 scripts/data/dataset_组织与用户.py --list    # 数据集与规模
python3 scripts/data/dataset_组织与用户.py --plan    # 写入计划（不落库；缺环境变量只提示）
python3 scripts/data/dataset_组织与用户.py --apply --confirm   # 接入造数逻辑后执行
```

骨架固化的口径：声明式定义（表 → 行，`--plan` 可逐条打印）、元信息四项（用途 / 依赖服务 / 清理策略 /
脱敏说明）、连接与凭据只从环境变量读（`REQUIRED_ENV` 列变量名，代码与文档不出现值）、
破坏性写入需 `--confirm`。**复制后必做**：填 `DATASETS` 与 `META`，并在 `apply_dataset()` 的 TODO 处接入连接与幂等写入。

## 3. 待办

| # | 待办 |
| --- | --- |
| 1 | ~~数据集定义格式与生成入口~~ **已完成 2026-09-16**（`dataset_template.py`：声明式定义 + `--list/--plan/--apply` 三段式） |
| 2 | ~~敏感数据脱敏约定~~ **已完成 2026-09-16**（脱敏说明进元信息；真实值只从环境变量注入，见骨架 `META["sensitive"]` 与 `REQUIRED_ENV`） |
| 3 | 首个真实数据集（随需造数的阶段任务落地，如 RBAC 组织与用户、导入导出样例文件） |

> 依《文档生成规范》编写 · 测试资产仓库
