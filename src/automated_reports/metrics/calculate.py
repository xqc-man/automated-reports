import json
import math

import pandas as pd

from automated_reports.processing.schema import (
    DERIVED_METRICS,
    OUTPUT_COLUMNS,
    SYNTHETIC_NOTICE,
    DataError,
)


def _reference(row: dict) -> dict:
    return {
        "metric_id": row["metric_id"],
        "period_start": row["period_start"],
        "value": None if pd.isna(row["value"]) else row["value"],
        "source_record_id": row["source_record_id"],
        "status": row["status"],
    }


def calculate(frame: pd.DataFrame, manifest: dict) -> pd.DataFrame:
    """仅接受规范化标准表；缺失、负基数与零分母都保留明确原因。"""
    data_type = manifest["data_type"]
    notice = SYNTHETIC_NOTICE if data_type == "synthetic" else "历史样本，分析范围以来源说明为准"
    rows = frame.assign(formula="", inputs="[]", data_type=data_type, data_notice=notice)
    output = rows.to_dict("records")
    lookup = {(r["metric_id"], r["period_start"]): r for r in output}
    periods = sorted(frame["period_start"].unique())
    frequency = {"monthly": "M", "quarterly": "Q-DEC"}[manifest["frequency"]]
    year_offset = 12 if manifest["frequency"] == "monthly" else 4

    def derive(metric_id: str, base: dict, operands: list[dict | None], operation: str) -> None:
        unit, formula = DERIVED_METRICS[metric_id]
        status, reason, value = "derived", "", float("nan")
        if any(r is None for r in operands):
            status, reason = "missing", "baseline_not_available"
        elif any(pd.isna(r["value"]) for r in operands):
            status, reason = "missing", "input_missing"
        else:
            left, right = (r["value"] for r in operands)
            if operation in {"ratio", "growth"} and right == 0:
                status, reason = "not_comparable", "zero_denominator"
            elif operation == "growth" and right < 0:
                status, reason = "not_comparable", "negative_baseline"
            elif operation == "difference":
                value = left - right
            else:
                value = left / right - (1 if operation == "growth" else 0)
            if status == "derived" and not math.isfinite(value):
                raise DataError(f"派生计算溢出：{metric_id}，请核查输入量级")
        row = base.copy()
        row.update(
            metric_id=metric_id,
            value=value,
            unit=unit,
            currency=base["currency"] if unit.startswith("currency") else "",
            definition=formula,
            status=status,
            missing_reason=reason,
            source_record_id="",
            formula=formula,
            inputs=json.dumps(
                [_reference(r) for r in operands if r is not None],
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            ),
        )
        output.append(row)

    for start in periods:
        current_period = pd.Period(start, freq=frequency)
        previous = str((current_period - 1).start_time.date())
        previous_year = str((current_period - year_offset).start_time.date())
        sales = lookup.get(("sales_amount", start))
        orders = lookup.get(("orders_count", start))
        if sales is not None:
            if orders is not None:
                derive("average_order_value", sales, [sales, orders], "ratio")
            last_sales = lookup.get(("sales_amount", previous))
            derive("sales_period_growth", sales, [sales, last_sales], "growth")
            last_year_sales = lookup.get(("sales_amount", previous_year))
            derive("sales_yoy", sales, [sales, last_year_sales], "growth")
            derive("sales_change", sales, [sales, last_sales], "difference")
            derive("sales_yoy_change", sales, [sales, last_year_sales], "difference")
        profit = lookup.get(("net_profit", start))
        if profit is not None:
            derive(
                "profit_change",
                profit,
                [profit, lookup.get(("net_profit", previous))],
                "difference",
            )
    return pd.DataFrame(output, columns=OUTPUT_COLUMNS).sort_values(
        ["case_id", "metric_id", "period_start"],
        ignore_index=True,
    )
