from pathlib import Path

from automated_reports.adapters.csv_input import read_input
from automated_reports.metrics.calculate import calculate
from automated_reports.processing.normalize import normalize
from automated_reports.processing.schema import DataError
from automated_reports.storage.snapshot import write_snapshot


def build_snapshot(csv_path: Path, manifest_path: Path, destination: Path) -> dict:
    for source in (csv_path, manifest_path):
        if source.resolve().is_relative_to(destination.resolve()):
            raise DataError("输入文件不能放在将被替换的输出目录内")
    frame, manifest = read_input(csv_path, manifest_path)
    normalized, quality = normalize(frame, manifest)
    metrics = calculate(normalized, manifest)
    return write_snapshot(metrics, manifest, quality, destination)
