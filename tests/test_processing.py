import copy
import json

import pandas as pd
import pytest

from automated_reports.metrics.calculate import calculate
from automated_reports.processing.normalize import normalize
from automated_reports.processing.schema import DataError


def result_row(result, metric, start):
    selected = result[(result.metric_id == metric) & (result.period_start == start)]
    assert len(selected) == 1
    return selected.iloc[0]


def test_growth_uses_prior_year_outside_display_window(sample):
    frame, manifest = sample
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    row = result_row(result, "sales_yoy", "2024-01-01")
    assert row.value == pytest.approx(0.5)
    refs = json.loads(row.inputs)
    assert refs[1]["period_start"] == "2023-01-01"
    assert refs[1]["source_record_id"] == "fixture-source"


def test_order_value_and_profit_absolute_change(sample):
    frame, manifest = sample
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    assert result_row(result, "average_order_value", "2024-01-01").value == 10
    # 亏损到盈利采用绝对差，不给负基数增长百分比。
    assert result_row(result, "profit_change", "2024-02-01").value == 20


def test_zero_and_negative_sales_baselines(sample):
    frame, manifest = sample
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    zero = result_row(result, "sales_period_growth", "2024-03-01")
    negative = result_row(result, "sales_period_growth", "2024-04-01")
    assert pd.isna(zero.value) and zero.missing_reason == "zero_denominator"
    assert pd.isna(negative.value) and negative.missing_reason == "negative_baseline"
    assert negative.status == "not_comparable"
    assert result_row(result, "sales_change", "2024-04-01").value == 220


def test_zero_orders_and_missing_inputs(sample):
    frame, manifest = sample
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    row = result_row(result, "average_order_value", "2024-02-01")
    assert pd.isna(row.value) and row.missing_reason == "zero_denominator"
    row = result_row(result, "sales_period_growth", "2024-06-01")
    assert pd.isna(row.value) and row.missing_reason == "input_missing"


def test_gap_is_missing_not_zero_or_previous_observation(sample):
    frame, manifest = sample
    normalized, quality = normalize(frame, manifest)
    assert quality["inserted_missing_periods"] > 0
    missing = result_row(normalized, "sales_amount", "2024-05-01")
    assert pd.isna(missing.value) and missing.missing_reason == "period_not_provided"
    result = calculate(normalized, manifest)
    assert result_row(result, "sales_period_growth", "2024-06-01").status == "missing"


def test_exact_duplicates_are_deduplicated_and_order_does_not_matter(sample):
    frame, manifest = sample
    original, _ = normalize(frame, manifest)
    repeated = pd.concat([frame, frame.iloc[[0]]]).sample(frac=1, random_state=7)
    deduplicated, quality = normalize(repeated, manifest)
    pd.testing.assert_frame_equal(original, deduplicated)
    assert quality["duplicates_removed"] == 1


def test_conflicting_duplicate_is_rejected(sample):
    frame, manifest = sample
    conflict = frame.iloc[[0]].copy()
    conflict["value"] = "999"
    with pytest.raises(DataError, match="冲突"):
        normalize(pd.concat([frame, conflict]), manifest)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("unit", "thousands", "单位"),
        ("currency", "USD", "混用币种"),
        ("value", "Infinity", "有限数字"),
        ("value", "NaN", "有限数字"),
        ("value", "not-a-number", "有限数字"),
        ("value", "", "原始值"),
        ("case_id", "other-company", "企业标识"),
        ("period_start", "2024-01-02", "完整月"),
        ("period_end", "2024-01-30", "完整月"),
        ("source_record_id", "unknown", "来源记录"),
        ("status", "derived", "输入状态"),
        ("metric_id", "unknown", "未适配"),
    ],
)
def test_invalid_input_rejected(sample, column, value, message):
    frame, manifest = sample
    frame.loc[0, column] = value
    with pytest.raises(DataError, match=message):
        normalize(frame, manifest)


@pytest.mark.parametrize("value", ["-1", "2.5"])
def test_count_must_be_nonnegative_integer(sample, value):
    frame, manifest = sample
    index = frame.index[frame.metric_id == "orders_count"][0]
    frame.loc[index, "value"] = value
    with pytest.raises(DataError, match="非负整数"):
        normalize(frame, manifest)


def test_inconsistent_definitions_rejected(sample):
    frame, manifest = sample
    frame.loc[0, "definition"] = "新口径"
    with pytest.raises(DataError, match="不一致口径"):
        normalize(frame, manifest)


def test_missing_row_requires_reason_and_no_value(sample):
    frame, manifest = sample
    frame.loc[0, "status"] = "missing"
    with pytest.raises(DataError, match="缺失值"):
        normalize(frame, manifest)
    frame.loc[0, "value"] = ""
    with pytest.raises(DataError, match="缺失值"):
        normalize(frame, manifest)
    frame.loc[0, "missing_reason"] = "not_disclosed"
    normalized, _ = normalize(frame, manifest)
    assert pd.isna(result_row(normalized, "sales_amount", "2023-01-01").value)


def test_synthetic_cannot_have_fake_url(sample):
    frame, manifest = sample
    manifest["sources"]["fixture-source"]["url"] = "https://example.com/fake"
    with pytest.raises(DataError, match="伪造链接"):
        normalize(frame, manifest)


def test_real_source_requires_url(sample):
    frame, manifest = sample
    manifest["data_type"] = "real"
    with pytest.raises(DataError, match="HTTP"):
        normalize(frame, manifest)


def test_invalid_manifest_and_empty_input(sample):
    frame, manifest = sample
    bad = copy.deepcopy(manifest)
    bad["display_window"]["end"] = "2024-06-29"
    with pytest.raises(DataError, match="展示窗口"):
        normalize(frame, bad)
    with pytest.raises(DataError, match="不能为空"):
        normalize(frame.iloc[:0], manifest)
    with pytest.raises(DataError, match="仅包含"):
        normalize(frame.drop(columns="unit"), manifest)


def test_quarterly_yoy_is_four_quarters(sample):
    frame, manifest = sample
    frame = frame[
        (frame.metric_id == "sales_amount")
        & frame.period_start.isin(
            ["2023-01-01", "2024-01-01"],
        )
    ].copy()
    frame["period_end"] = ["2023-03-31", "2024-03-31"]
    frame["frequency"] = "quarterly"
    manifest["frequency"] = "quarterly"
    manifest["display_window"] = {"start": "2024-01-01", "end": "2024-03-31"}
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    assert result_row(result, "sales_yoy", "2024-01-01").value == pytest.approx(0.5)


def test_yoy_change_and_negative_current_value(sample):
    frame, manifest = sample
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    assert result_row(result, "sales_yoy_change", "2024-01-01").value == 50
    frame.loc[
        (frame.metric_id == "sales_amount") & (frame.period_start == "2024-01-01"), "value"
    ] = "-50"
    normalized, _ = normalize(frame, manifest)
    result = calculate(normalized, manifest)
    # 基期为正、本期为负时增长率仍有意义，正常计算。
    assert result_row(result, "sales_yoy", "2024-01-01").value == pytest.approx(-1.5)
    assert result_row(result, "sales_yoy_change", "2024-01-01").value == -150
