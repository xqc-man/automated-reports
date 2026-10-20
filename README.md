# 自动化报表

将约定格式的经营指标 CSV 转换为可追溯、可查询的分析快照。一次命令完成导入、校验、计算和保存，DuckDB 在内存中查询快照，无需单独安装数据库服务。

仓库内的数据全部是**模拟数据，仅用于功能演示**，不代表真实企业业绩。真实数据选型和接入按规划后续进行。阶段状态与验收结果统一见 [项目记录](项目记录.md)。

## 安装

环境：Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/)。依赖通过 `uv.lock` 锁定，无需 API 密钥。

先按 uv 官方文档安装 uv，然后在仓库根目录执行：

```bash
cd automated-reports
uv sync --locked
```

`cd` 后面换成你实际克隆或存放项目的目录。首次安装需要网络，之后下列数据流程不访问网络。`.env.example` 提供配置说明，本版本不读取 `.env`，路径通过命令行参数指定。

## 生成快照

```bash
uv run --locked automated-reports build
uv run --locked automated-reports validate
```

默认读取 `data/synthetic/input.csv` 和 `data/synthetic/source.json`，输出到 `runtime/snapshot/`：

- `metrics.csv`：原始及派生指标，包含状态、公式、输入依据和模拟数据标识。
- `metadata.json`：来源、固定展示窗口、许可、版本哈希、导入时间和质量统计。

命令返回 JSON 摘要，`changed: false` 表示内容相同，快照和首次成功导入时间保持不变。每次调用的成功或失败原因写入 `runtime/runs.jsonl`，该目录不入库。日志写入失败会单独提示，不把已经成功保存的快照误报为导入失败。

接入另一个符合相同契约的文件：

```bash
uv run --locked automated-reports build \
  --input tests/fixtures/input.csv \
  --manifest tests/fixtures/source.json \
  --output runtime/fixture-snapshot \
  --run-log runtime/fixture-runs.jsonl
```

测试材料同样是模拟数据，不能作为真实案例使用。标准输入字段与来源配置见 [数据契约](docs/数据契约.md)。

## 查询与导出

```bash
# 默认只查询元数据中的展示窗口
uv run --locked automated-reports query --metric sales_amount

# 同比使用窗口外基线计算；该参数用于查看包含基线的完整指标表
uv run --locked automated-reports query --metric sales_yoy --all-periods

# 查询结果为 CSV，可重定向到新文件，不要覆盖输入或快照文件
uv run --locked automated-reports query --metric average_order_value > runtime/order-value.csv

# 查询指定快照
uv run --locked automated-reports query --snapshot runtime/fixture-snapshot --metric profit_change
```

CSV 的 `data_type`、`data_notice` 始终保留数据类型说明。比率为小数，例如 `0.5` 表示 50%，金额保持声明币种的基本单位，计数保持人数或订单数。查询无匹配指标时返回错误，错误信息写到标准错误，不混入 CSV。

## 验证与开发

```bash
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest
```

CI 使用 `tests/fixtures/` 中的固定材料，不访问实时数据网站。可在本地重建演示输入：

```bash
uv run --locked python scripts/generate_synthetic.py
```

生成器使用固定随机种子，不读取系统时间。演示数据保持业务上合理的关系（客户数、订单数、销售额、利润相互关联），只保留 2024-05 活跃客户数一个缺失示例；零基数、负基数、重复行等边界场景只放在 `tests/fixtures/` 中测试。

## 行为与限制

- 支持标准指标长表，不接受任意列名或原始订单明细；未知指标必须先适配。
- 输入每行代表一个完整月或自然季度的单期值，不自动猜测累计值、进行换汇或聚合客户明细。
- 相同记录去重，同键冲突拒绝导入；指标口径或币种不一致时报错。
- 缺失期间显式补为空值，缺失不填零。同比和环比按日历期间查找，不能跳过缺失期间比较。
- 输入、计算和发布前校验失败时不替换旧快照；发布目录切换遇到可捕获的安装错误时回滚。现阶段仅支持本地单写入者，不提供并发读写或断电恢复保证。
- 输出目录必须不存在或是工具生成的完整快照，不覆盖用户的其他文件；快照损坏需先诊断，再换一个输出路径重建。
- 数值使用双精度浮点，适用于分析展示，不作为会计记账或结算账本。
- 网页看板、HTML 报告、真实来源适配与在线演示按后续阶段实现。

核心实现位于 `src/automated_reports/`；指标集中在 `metrics/`，后续页面与报告应复用同一计算结果。
