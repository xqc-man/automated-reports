from pathlib import Path

import duckdb
import pandas as pd

from automated_reports.storage.snapshot import read_snapshot


def query_snapshot(
    path: Path,
    metric_id: str | None = None,
    *,
    all_periods: bool = False,
) -> tuple[pd.DataFrame, dict]:
    frame, metadata = read_snapshot(path)
    window = metadata["source_config"]["display_window"]
    conditions, parameters = [], []
    if metric_id is not None:
        conditions.append("metric_id = ?")
        parameters.append(metric_id)
    if not all_periods:
        conditions.append("period_start >= ? AND period_end <= ?")
        parameters.extend([window["start"], window["end"]])
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    with duckdb.connect(":memory:") as connection:
        connection.register("snapshot_frame", frame)
        connection.execute("CREATE TABLE metrics AS SELECT * FROM snapshot_frame")
        result = connection.execute(
            "SELECT * FROM metrics" + where + " ORDER BY case_id, metric_id, period_start",
            parameters,
        ).df()
    return result, metadata
