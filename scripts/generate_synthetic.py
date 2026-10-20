"""生成固定种子的虚构数据，仅用于功能开发，不代表任何真实企业。"""

import calendar
import csv
import json
import random
from pathlib import Path

SEED = 20261020
SEASONALITY = [0.92, 0.88, 0.97, 1.0, 1.02, 1.05, 0.98, 0.97, 1.02, 1.04, 1.12, 1.2]
ROOT = Path(__file__).resolve().parents[1] / "data" / "synthetic"
COLUMNS = [
    "case_id",
    "metric_id",
    "value",
    "unit",
    "currency",
    "period_start",
    "period_end",
    "frequency",
    "definition",
    "source_record_id",
    "status",
    "missing_reason",
]


def generate() -> None:
    rng = random.Random(SEED)
    rows = []
    for index in range(24):
        year, month = 2023 + index // 12, index % 12 + 1
        start, end = (
            f"{year}-{month:02d}-01",
            f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]}",
        )
        customers = round((600 + index * 15) * SEASONALITY[month - 1] + rng.randint(-20, 20))
        orders = round(customers * rng.uniform(1.25, 1.35))
        sales = round(orders * (120 + index * 0.5 + rng.uniform(-4, 4)))
        values = {
            "sales_amount": (
                sales,
                "currency",
                "CNY",
                "虚构样本销售额，含退款调整，不代表财务营收",
            ),
            "orders_count": (orders, "count", "", "虚构有效订单数，非商品行数"),
            "active_customers": (customers, "count", "", "虚构期间去重客户数"),
            "net_profit": (
                round(sales * 0.18 - 9000),
                "currency",
                "CNY",
                "虚构净利润：销售额的 18% 减固定成本",
            ),
        }
        for metric_id, (value, unit, currency, definition) in values.items():
            # 保留一个缺失示例，用于展示缺失提示；其余边界场景只在 tests/fixtures 中覆盖。
            is_missing = (year, month) == (2024, 5) and metric_id == "active_customers"
            rows.append(
                {
                    "case_id": "synthetic-shop",
                    "metric_id": metric_id,
                    "value": "" if is_missing else value,
                    "unit": unit,
                    "currency": currency,
                    "period_start": start,
                    "period_end": end,
                    "frequency": "monthly",
                    "definition": definition,
                    "source_record_id": "synthetic-generator",
                    "status": "missing" if is_missing else "original",
                    "missing_reason": "synthetic_missing_example" if is_missing else "",
                }
            )
    manifest = {
        "case_id": "synthetic-shop",
        "case_name": "模拟商店（虚构）",
        "data_type": "synthetic",
        "frequency": "monthly",
        "license": "本项目生成的模拟数据，可用于功能演示",
        "display_window": {"start": "2024-01-01", "end": "2024-12-31"},
        "sources": {
            "synthetic-generator": {
                "url": None,
                "evidence": f"scripts/generate_synthetic.py；固定随机种子 {SEED}；全部为虚构数据",
            }
        },
    }
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / "input.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (ROOT / "source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    generate()
