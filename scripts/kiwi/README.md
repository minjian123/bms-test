# Kiwi 用例工具

> Kiwi 用例的登记 / 批量维护 / 导出核对

## 1. 背景与口径

用例本体在 **Kiwi TCMS 平台**（不在 git），平台约定见《[测试规范](../../bms文档/规范/测试规范.md)》§5：
分类「平台骨架」、优先级 P2、状态 CONFIRMED、自动化用例加标签「自动化」、**一任务一条用例**。

**编号是平台全局自增且跨产品共享**：自动用例产品（CI 导入）会占用大量编号，
策展用例的新编号因此会跳号（实证：策展第 70 条为 **528**）——登记后务必回读实际编号，不要假设连续。

## 2. 脚本与用法

三个脚本都经 SSH 走容器 Django shell（代码 stdin 传入，不落盘进容器），
主机与用户默认读环境变量 `MJBK_IP` / `MJBK_SSH_USER`，也可用 `--host` / `--user` 覆盖：

```bash
cd bms && set -a && . ./deploy/.env && set +a    # 取 MJBK_IP / MJBK_SSH_USER

# 1) 批量登记（按 summary 去重，幂等），回读平台实际编号
python3 scripts/kiwi/register_cases.py --file cases.json --out result.json
python3 scripts/kiwi/register_cases.py --file cases.json --dry-run     # 只看将执行的代码

# 2) 批量维护状态 / 优先级 / 标签（必须给 --ids 或 --product，避免全表误改）
python3 scripts/kiwi/update_status.py --ids 66,67 --status CONFIRMED
python3 scripts/kiwi/update_status.py --product "BMS 基础管理系统" --tag 自动化

# 3) 导出清单，并与代码里的 @pytest.mark.kiwi_id 对账
python3 scripts/kiwi/export_cases.py --out cases.json
python3 scripts/kiwi/export_cases.py --reconcile --code-root ../bms/backend
```

| 脚本 | 说明 | 幂等性 |
| --- | --- | --- |
| `register_cases.py` | 按 JSON 登记，同名用例跳过并回读编号 | ✅ 按 `summary` 去重 |
| `update_status.py` | 状态 / 优先级 / 标签批量维护；不给修改项则只查询 | ✅ 重复执行结果一致 |
| `export_cases.py` | 导出 JSON / CSV，并输出「平台 vs 代码 kiwi_id」三类差异 | ✅ 只读 |

输入模板见 `examples/cases.example.json`。

## 3. 字段与编号口径

- 字段可反查：`TestCase._meta.get_field("<f>").related_model`（category / priority / case_status / author / tag）。
- **编号跳号是平台机制**：用例编号全局自增、跨产品共享，策展新用例的实际编号请以 `register_cases.py` 回读为准。

> 依《文档生成规范》编写 · 测试资产仓库
