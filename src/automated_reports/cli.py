import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from automated_reports import __version__
from automated_reports.pipeline import build_snapshot
from automated_reports.processing.schema import DataError
from automated_reports.storage.query import query_snapshot
from automated_reports.storage.snapshot import read_snapshot


def _write_run(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {"time": datetime.now(UTC).isoformat(), **event},
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自动化报表：CSV 接入、计算、快照与查询")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="导入并校验 CSV，计算后发布快照")
    build.add_argument("--input", type=Path, default=Path("data/synthetic/input.csv"))
    build.add_argument("--manifest", type=Path, default=Path("data/synthetic/source.json"))
    build.add_argument("--output", type=Path, default=Path("runtime/snapshot"))
    build.add_argument("--run-log", type=Path, default=Path("runtime/runs.jsonl"))
    validate = commands.add_parser("validate", help="校验已有快照的结构、版本及内容哈希")
    validate.add_argument("--snapshot", type=Path, default=Path("runtime/snapshot"))
    query = commands.add_parser("query", help="通过 DuckDB 查询快照，输出含数据标识的 CSV")
    query.add_argument("--snapshot", type=Path, default=Path("runtime/snapshot"))
    query.add_argument("--metric", help="只查询一个指标，如 sales_yoy")
    query.add_argument("--all-periods", action="store_true", help="包含展示窗口之外的基线")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_snapshot(args.input, args.manifest, args.output)
            metadata = result["metadata"]
            event = {
                "command": "build",
                "status": "success",
                "changed": result["changed"],
                "snapshot_version": metadata["snapshot_version"],
                "data_type": metadata["source_config"]["data_type"],
                "output_rows": metadata["output_rows"],
                "quality": result["quality"],
                "output": str(args.output),
            }
            try:
                _write_run(args.run_log, event)
            except OSError as log_error:
                print(f"快照已成功生成，但运行记录写入失败：{log_error}", file=sys.stderr)
            print(json.dumps(event, ensure_ascii=False, indent=2))
        elif args.command == "validate":
            frame, metadata = read_snapshot(args.snapshot)
            print(
                json.dumps(
                    {
                        "valid": True,
                        "rows": len(frame),
                        "snapshot_version": metadata["snapshot_version"],
                        "data_type": metadata["source_config"]["data_type"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            frame, metadata = query_snapshot(
                args.snapshot, args.metric, all_periods=args.all_periods
            )
            if frame.empty:
                raise DataError("当前窗口内无匹配指标，请检查指标名称或使用 --all-periods")
            print(
                f"数据类型：{metadata['source_config']['data_type']}；来源与口径见 metadata.json",
                file=sys.stderr,
            )
            sys.stdout.write(frame.to_csv(index=False, lineterminator="\n", float_format="%.17g"))
        return 0
    except (DataError, OSError) as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        if args.command == "build":
            try:
                _write_run(
                    args.run_log, {"command": "build", "status": "failed", "reason": str(exc)}
                )
            except OSError as log_error:
                print(f"运行记录写入失败：{log_error}", file=sys.stderr)
        return 1
