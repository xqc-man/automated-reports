import json
from pathlib import Path

import pandas as pd

from automated_reports.processing.schema import DataError


def read_input(csv_path: Path, manifest_path: Path) -> tuple[pd.DataFrame, dict]:
    """按字符串读取，保留客户编号、空值和原始数字，交由统一校验。"""
    try:
        frame = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DataError(f"无法读取输入：{exc}") from exc
    return frame, manifest
