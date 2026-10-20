"""生成固定种子的虚构数据，仅用于功能开发，不代表任何真实企业。"""

import calendar
import csv
import json
import random
from pathlib import Path

SEED = 20261020
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
        sales = 10000 + index * 350 + rng.randint(-600, 600)
        if index in {0, 1}:
            sales = (0, -100)[index]
        values = {
            "sales_amount": (
                sales,
                "currency",
                "CNY",
                "虚构样本销售额，含退款调整，不代表财务营收",
            ),
            "orders_count": (
                0 if index in {0, 17} else 80 + index * 4,
                "count",
                "",
                "虚构有效订单数，非商品行数",
            ),
            "active_customers": (60 + index * 3, "count", "", "虚构期间去重客户数"),
            "net_profit": (-500 + index * 100, "currency", "CNY", "虚构净利润，仅验证正负数计算"),
        }
        for metric_id, (value, unit, currency, definition) in values.items():
            if index == 16 and metric_id == "active_customers":
                continue  # 故意遗漏一个期间，验证补为缺失，不能补零。
            is_missing = index == 5 and metric_id == "sales_amount"
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
    rows.append(rows[10].copy())  # 完全重复行：导入后应去重。
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
