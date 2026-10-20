import json
from pathlib import Path

import pytest

from automated_reports.cli import main
from automated_reports.pipeline import build_snapshot
from automated_reports.processing.schema import SYNTHETIC_NOTICE, DataError
from automated_reports.storage import snapshot as storage
from automated_reports.storage.query import query_snapshot
from automated_reports.storage.snapshot import read_snapshot


def bytes_in(path):
    return {p.name: p.read_bytes() for p in path.iterdir()}


def test_snapshot_is_idempotent_and_provenance_is_retained(source_paths, tmp_path):
    destination = tmp_path / "snapshot"
    first = build_snapshot(*source_paths, destination)
    before = bytes_in(destination)
    second = build_snapshot(*source_paths, destination)
    assert first["changed"] and not second["changed"]
    assert first["metadata"] == second["metadata"]
    assert bytes_in(destination) == before
    frame, metadata = read_snapshot(destination)
    assert frame.data_type.eq("synthetic").all()
    assert frame.data_notice.eq(SYNTHETIC_NOTICE).all()
    assert metadata["source_config"]["sources"]["fixture-source"]["url"] is None


def test_invalid_input_does_not_replace_good_snapshot(source_paths, tmp_path):
    destination = tmp_path / "snapshot"
    build_snapshot(*source_paths, destination)
    before = bytes_in(destination)
    bad = tmp_path / "bad.csv"
    bad.write_text("not,the,right,columns\n1,2,3,4\n")
    with pytest.raises(DataError):
        build_snapshot(bad, source_paths[1], destination)
    assert bytes_in(destination) == before


def test_failed_install_rolls_back_previous_snapshot(source_paths, tmp_path, monkeypatch):
    destination = tmp_path / "snapshot"
    build_snapshot(*source_paths, destination)
    before = bytes_in(destination)
    manifest = json.loads(source_paths[1].read_text())
    manifest["case_name"] = "修改后的模拟案例"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(manifest))
    real_replace = storage.os.replace

    def fail_staged(source, target):
        if "staging" in str(source):
            raise OSError("simulated disk failure")
        return real_replace(source, target)

    monkeypatch.setattr(storage.os, "replace", fail_staged)
    with pytest.raises(OSError, match="disk failure"):
        build_snapshot(source_paths[0], changed, destination)
    assert bytes_in(destination) == before


def test_duckdb_fixed_window_and_filter_parameters(source_paths, tmp_path):
    build_snapshot(*source_paths, tmp_path / "snapshot")
    frame, _ = query_snapshot(tmp_path / "snapshot", "sales_yoy")
    assert len(frame) == 6
    assert frame.period_start.min() == "2024-01-01"
    assert frame.iloc[0].value == pytest.approx(0.5)
    all_rows, _ = query_snapshot(tmp_path / "snapshot", "sales_amount", all_periods=True)
    assert len(all_rows) == 18
    injection, _ = query_snapshot(tmp_path / "snapshot", "sales_amount' OR 1=1 --")
    assert injection.empty


@pytest.mark.parametrize("file", ["metrics.csv", "metadata.json"])
def test_corrupt_snapshot_is_rejected(source_paths, tmp_path, file):
    destination = tmp_path / "snapshot"
    build_snapshot(*source_paths, destination)
    path = destination / file
    if file == "metrics.csv":
        path.write_text(path.read_text().replace("150", "151"))
    else:
        meta = json.loads(path.read_text())
        meta["source_config"]["case_name"] = "tampered"
        path.write_text(json.dumps(meta))
    with pytest.raises(DataError, match="不一致"):
        read_snapshot(destination)


def test_existing_unrelated_files_are_never_deleted(source_paths, tmp_path):
    destination = tmp_path / "snapshot"
    destination.mkdir()
    personal = destination / "personal.txt"
    personal.write_text("do not remove")
    with pytest.raises(DataError):
        build_snapshot(*source_paths, destination)
    assert personal.read_text() == "do not remove"


def test_publish_rejects_extra_files_for_changed_snapshot(source_paths, tmp_path):
    destination = tmp_path / "snapshot"
    build_snapshot(*source_paths, destination)
    extra = destination / "personal.txt"
    extra.write_text("keep")
    # 不变版本可以读；有其他文件时绝不执行目录替换。
    manifest = json.loads(source_paths[1].read_text())
    manifest["case_name"] = "new"
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(manifest))
    with pytest.raises(DataError, match="其他文件"):
        build_snapshot(source_paths[0], changed, destination)
    assert extra.read_text() == "keep"


def test_build_cli_success_failure_log_and_query(source_paths, tmp_path, capsys):
    snapshot, log = tmp_path / "snapshot", tmp_path / "runs.jsonl"
    args = [
        "build",
        "--input",
        str(source_paths[0]),
        "--manifest",
        str(source_paths[1]),
        "--output",
        str(snapshot),
        "--run-log",
        str(log),
    ]
    assert main(args) == 0
    assert json.loads(capsys.readouterr().out)["data_type"] == "synthetic"
    assert main(["validate", "--snapshot", str(snapshot)]) == 0
    assert json.loads(capsys.readouterr().out)["valid"]
    assert main(["query", "--snapshot", str(snapshot), "--metric", "sales_yoy"]) == 0
    assert SYNTHETIC_NOTICE in capsys.readouterr().out
    args[args.index("--input") + 1] = str(tmp_path / "not-found.csv")
    assert main(args) == 1
    assert "操作失败" in capsys.readouterr().err
    events = [json.loads(line) for line in log.read_text().splitlines()]
    assert [e["status"] for e in events] == ["success", "failed"]
    assert main(["validate", "--snapshot", str(snapshot)]) == 0


def test_source_inside_output_is_rejected(source_paths):
    with pytest.raises(DataError, match="输出目录内"):
        build_snapshot(source_paths[0], source_paths[1], source_paths[0].parent)


def test_snapshot_csv_export_keeps_simulation_markers(source_paths, tmp_path):
    destination = tmp_path / "snapshot"
    build_snapshot(*source_paths, destination)
    csv = (destination / "metrics.csv").read_text()
    assert "data_type,data_notice" in csv
    assert SYNTHETIC_NOTICE in csv
    assert "https://example" not in csv


def test_absent_snapshot_is_friendly_error(tmp_path, capsys):
    assert main(["query", "--snapshot", str(tmp_path / "missing")]) == 1
    assert "无法加载快照" in capsys.readouterr().err


def test_snapshot_output_symlink_rejected(source_paths, tmp_path):
    actual = tmp_path / "actual"
    build_snapshot(*source_paths, actual)
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(DataError, match="符号链接"):
        build_snapshot(*source_paths, link)
    assert Path(actual / "metrics.csv").exists()


def test_log_write_failure_does_not_misreport_published_snapshot(
    source_paths,
    tmp_path,
    capsys,
):
    log_directory = tmp_path / "log-directory"
    log_directory.mkdir()
    destination = tmp_path / "snapshot"
    assert (
        main(
            [
                "build",
                "--input",
                str(source_paths[0]),
                "--manifest",
                str(source_paths[1]),
                "--output",
                str(destination),
                "--run-log",
                str(log_directory),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert "运行记录写入失败" in captured.err
    assert json.loads(captured.out)["status"] == "success"
    read_snapshot(destination)
