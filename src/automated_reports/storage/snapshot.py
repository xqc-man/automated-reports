import hashlib
import io
import json
import math
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from automated_reports import __version__
from automated_reports.processing.normalize import validate_manifest
from automated_reports.processing.schema import (
    KEY,
    OUTPUT_COLUMNS,
    SYNTHETIC_NOTICE,
    DataError,
)


def _version(csv_bytes: bytes, source_config: dict, code_version: str) -> str:
    config = json.dumps(source_config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(csv_bytes + config.encode() + code_version.encode()).hexdigest()


def read_snapshot(path: Path) -> tuple[pd.DataFrame, dict]:
    try:
        csv_bytes = (path / "metrics.csv").read_bytes()
        metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or metadata.get("schema_version") != 1:
            raise DataError("不支持的快照结构版本")
        if not isinstance(metadata.get("code_version"), str):
            raise DataError("快照代码版本必须为字符串")
        config = metadata["source_config"]
        validate_manifest(config)
        if hashlib.sha256(csv_bytes).hexdigest() != metadata["content_sha256"]:
            raise DataError("快照内容哈希不一致，文件可能损坏或混用了版本")
        if _version(csv_bytes, config, metadata["code_version"]) != metadata["snapshot_version"]:
            raise DataError("快照版本与数据/来源配置不一致")
        frame = pd.read_csv(
            io.BytesIO(csv_bytes), keep_default_na=False, dtype=str, encoding="utf-8"
        )
        if list(frame.columns) != OUTPUT_COLUMNS or frame.empty:
            raise DataError("快照指标表结构不正确")
        if metadata["output_rows"] != len(frame):
            raise DataError("快照记录数与元数据不一致")
        frame["value"] = pd.to_numeric(frame["value"].replace("", float("nan")), errors="raise")
        if (
            frame.duplicated(KEY).any()
            or not frame["data_type"].eq(config["data_type"]).all()
            or not frame["case_id"].eq(config["case_id"]).all()
        ):
            raise DataError("快照存在重复键或来源标识不一致")
        valid = frame["status"].isin(["original", "derived"])
        empty = frame["status"].isin(["missing", "not_comparable"])
        if (
            not (valid | empty).all()
            or (valid & (frame["value"].isna() | frame["missing_reason"].ne(""))).any()
            or (empty & (frame["value"].notna() | frame["missing_reason"].eq(""))).any()
            or not frame.loc[valid, "value"].map(math.isfinite).all()
        ):
            raise DataError("快照数值与缺失状态不一致")
        if (
            config["data_type"] == "synthetic"
            and not frame["data_notice"]
            .eq(
                SYNTHETIC_NOTICE,
            )
            .all()
        ):
            raise DataError("模拟快照必须保留演示标识")
        return frame, metadata
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(f"无法加载快照：{exc}") from exc


def _publish(staged: Path, destination: Path) -> None:
    """本地单写入者：整目录替换，安装失败时恢复旧目录。"""
    backup = None
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise DataError("输出路径必须是普通快照目录")
        if {p.name for p in destination.iterdir()} != {"metrics.csv", "metadata.json"}:
            raise DataError("拒绝覆盖非快照目录或包含其他文件的目录")
        backup = Path(
            tempfile.mkdtemp(prefix=f".{destination.name}-backup-", dir=destination.parent)
        )
        backup.rmdir()
        os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except OSError:
        if backup is not None:
            os.replace(backup, destination)
        raise
    if backup is not None:
        shutil.rmtree(backup)


def write_snapshot(frame: pd.DataFrame, manifest: dict, quality: dict, destination: Path) -> dict:
    csv_bytes = frame.to_csv(index=False, lineterminator="\n", float_format="%.17g").encode("utf-8")
    version = _version(csv_bytes, manifest, __version__)
    if destination.is_symlink():
        raise DataError("不向符号链接写入快照")
    if destination.exists():
        _, previous = read_snapshot(destination)
        if previous["snapshot_version"] == version:
            return {"changed": False, "metadata": previous, "quality": quality}
    metadata = {
        "schema_version": 1,
        "snapshot_version": version,
        "content_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "code_version": __version__,
        "imported_at": datetime.now(UTC).isoformat(),
        "source_config": manifest,
        "quality": quality,
        "output_rows": len(frame),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-staging-", dir=destination.parent
    ) as tmp:
        staged = Path(tmp) / "snapshot"
        staged.mkdir()
        (staged / "metrics.csv").write_bytes(csv_bytes)
        (staged / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        read_snapshot(staged)
        _publish(staged, destination)
    return {"changed": True, "metadata": metadata, "quality": quality}
