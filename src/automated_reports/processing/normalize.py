import math
import re
from urllib.parse import urlparse

import pandas as pd

from automated_reports.processing.schema import BASE_METRICS, INPUT_COLUMNS, KEY, DataError


def period_index(start: str, end: str, frequency: str) -> pd.PeriodIndex:
    return pd.period_range(start, end, freq={"monthly": "M", "quarterly": "Q-DEC"}[frequency])


def validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict):
        raise DataError("来源配置必须是 JSON 对象")
    for field in ("case_id", "case_name", "license", "data_type", "frequency"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise DataError(f"来源配置缺少有效字段：{field}")
    if manifest["data_type"] not in {"synthetic", "real", "anonymized"}:
        raise DataError("data_type 必须为 synthetic / real / anonymized")
    if manifest["frequency"] not in {"monthly", "quarterly"}:
        raise DataError("frequency 必须为 monthly / quarterly")
    window = manifest.get("display_window")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise DataError("display_window 必须包含 start 和 end")
    try:
        start, end = (pd.Timestamp(window[k]) for k in ("start", "end"))
        if any(not isinstance(window[k], str) for k in window):
            raise ValueError
        periods = period_index(window["start"], window["end"], manifest["frequency"])
        if (
            not len(periods)
            or start.strftime("%Y-%m-%d") != window["start"]
            or end.strftime("%Y-%m-%d") != window["end"]
            or periods[0].start_time != start
            or periods[-1].end_time.normalize() != end
        ):
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise DataError("展示窗口必须为完整、有效且正序的月度或自然季度") from exc
    sources = manifest.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise DataError("sources 必须包含至少一条来源记录")
    for source_id, source in sources.items():
        if not isinstance(source_id, str) or not source_id.strip() or not isinstance(source, dict):
            raise DataError("来源 ID 和来源记录无效")
        if not isinstance(source.get("evidence"), str) or not source["evidence"].strip():
            raise DataError(f"来源 {source_id} 缺少 evidence")
        url = source.get("url")
        if manifest["data_type"] == "synthetic":
            if url is not None:
                raise DataError("模拟数据来源 url 必须为 null，不允许伪造链接")
        elif (
            not isinstance(url, str)
            or urlparse(url).scheme not in {"https", "http"}
            or not urlparse(url).netloc
        ):
            raise DataError(f"真实来源 {source_id} 必须提供 HTTP(S) 链接")


def normalize(frame: pd.DataFrame, manifest: dict) -> tuple[pd.DataFrame, dict]:
    validate_manifest(manifest)
    if set(frame.columns) != set(INPUT_COLUMNS):
        raise DataError(f"CSV 必须且仅包含这些列：{', '.join(INPUT_COLUMNS)}")
    if frame.empty:
        raise DataError("CSV 不能为空")
    result = frame[INPUT_COLUMNS].copy().fillna("").astype(str)
    for column in INPUT_COLUMNS:
        result[column] = result[column].str.strip()
    for column in set(INPUT_COLUMNS) - {"value", "currency", "missing_reason"}:
        if result[column].eq("").any():
            raise DataError(f"字段 {column} 不能为空")
    if not result["case_id"].eq(manifest["case_id"]).all():
        raise DataError("CSV 企业标识与来源配置不一致")
    if not result["frequency"].eq(manifest["frequency"]).all():
        raise DataError("CSV 频率与来源配置不一致")
    if not result["metric_id"].isin(BASE_METRICS).all():
        raise DataError("存在未适配的指标，请先定义其单位和计算口径")
    if not result["source_record_id"].isin(manifest["sources"]).all():
        raise DataError("CSV 存在未定义的来源记录")
    if not result["status"].isin(["original", "missing"]).all():
        raise DataError("输入状态只能为 original 或 missing")
    missing = result["status"].eq("missing")
    if (missing & (result["value"].ne("") | result["missing_reason"].eq(""))).any():
        raise DataError("缺失值必须为空且说明 missing_reason")
    if (~missing & (result["value"].eq("") | result["missing_reason"].ne(""))).any():
        raise DataError("原始值必须有数值且不能带缺失原因")
    numeric = pd.to_numeric(result["value"].where(~missing), errors="coerce")
    if ((~missing & numeric.isna()) | (numeric.notna() & ~numeric.map(math.isfinite))).any():
        raise DataError("数值必须为有限数字；不能以 NaN/Infinity 代替缺失标记")
    result["value"] = numeric.astype(float)

    for row in result.itertuples():
        try:
            periods = period_index(row.period_start, row.period_end, row.frequency)
            if (
                not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.period_start)
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.period_end)
                or len(periods) != 1
                or str(periods[0].start_time.date()) != row.period_start
                or str(periods[0].end_time.date()) != row.period_end
            ):
                raise ValueError
        except (ValueError, TypeError) as exc:
            raise DataError(
                f"期间必须为完整月或自然季度：{row.period_start}–{row.period_end}"
            ) from exc
        expected = BASE_METRICS[row.metric_id][0]
        if row.unit != expected:
            raise DataError(f"指标 {row.metric_id} 单位应为 {expected}")
        if expected == "currency":
            if not re.fullmatch(r"[A-Z]{3}", row.currency):
                raise DataError("金额必须声明三个大写字母的币种，如 CNY；首版不换汇")
        elif row.currency:
            raise DataError("计数指标 currency 必须为空")
        if expected == "count" and pd.notna(row.value):
            if row.value < 0 or not row.value.is_integer():
                raise DataError("计数必须为非负整数")

    money = result[result["unit"].eq("currency")]
    if money["currency"].nunique() > 1:
        raise DataError("一个案例不能混用币种；首版不换汇")
    for metric_id, group in result.groupby("metric_id"):
        if group["definition"].nunique() != 1:
            raise DataError(f"指标 {metric_id} 存在不一致口径")

    original_count = len(result)
    result = result.drop_duplicates()
    if result.duplicated(KEY).any():
        raise DataError("同一案例、指标、期间存在冲突记录，不自动选择其中一条")
    window = manifest["display_window"]
    periods = period_index(
        min(result["period_start"].min(), window["start"]),
        max(result["period_end"].max(), window["end"]),
        manifest["frequency"],
    )
    rows = []
    for _metric_id, group in result.groupby("metric_id", sort=True):
        existing = {row["period_start"]: row for row in group.to_dict("records")}
        for period in periods:
            start = str(period.start_time.date())
            if start in existing:
                rows.append(existing[start])
            else:
                row = group.iloc[0].to_dict()
                row.update(
                    period_start=start,
                    period_end=str(period.end_time.date()),
                    value=float("nan"),
                    status="missing",
                    missing_reason="period_not_provided",
                    source_record_id="",
                )
                rows.append(row)
    normalized = pd.DataFrame(rows, columns=INPUT_COLUMNS).sort_values(KEY).reset_index(drop=True)
    quality = {
        "input_rows": original_count,
        "duplicates_removed": original_count - len(result),
        "inserted_missing_periods": len(normalized) - len(result),
        "missing_base_values": int(normalized["value"].isna().sum()),
    }
    return normalized, quality
