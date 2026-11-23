import json
import os

from src.production_guard import write_heartbeat


def test_heartbeat_is_atomic_and_machine_readable(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    heartbeat = runtime / "heartbeat.json"
    lock = runtime / "perez_ai.lock"
    monkeypatch.setattr("src.production_guard.STATE_DIR", runtime)
    monkeypatch.setattr("src.production_guard.LOCK_PATH", lock)
    monkeypatch.setattr("src.production_guard.HEARTBEAT_PATH", heartbeat)
    lock.parent.mkdir(parents=True)
    lock.write_text(str(os.getpid()))

    payload = write_heartbeat("scanning", candidates=3)

    assert heartbeat.exists()
    saved = json.loads(heartbeat.read_text())
    assert saved["status"] == "scanning"
    assert saved["candidates"] == 3
    assert saved["pid"] == payload["pid"]
    assert isinstance(saved["epoch"], float)


def test_worker_heartbeat_does_not_overwrite_main_service_heartbeat(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    heartbeat = runtime / "heartbeat.json"
    worker_dir = runtime / "worker_heartbeats"
    lock = runtime / "perez_ai.lock"
    monkeypatch.setattr("src.production_guard.STATE_DIR", runtime)
    monkeypatch.setattr("src.production_guard.LOCK_PATH", lock)
    monkeypatch.setattr("src.production_guard.HEARTBEAT_PATH", heartbeat)
    monkeypatch.setattr("src.production_guard.WORKER_HEARTBEAT_DIR", worker_dir)
    runtime.mkdir(parents=True)
    heartbeat.write_text(json.dumps({"pid": 111, "status": "waiting_for_market_session"}))
    lock.write_text("111")

    payload = write_heartbeat("surge_paper_trade")

    assert json.loads(heartbeat.read_text())["pid"] == 111
    worker_file = worker_dir / f"{os.getpid()}.json"
    assert json.loads(worker_file.read_text())["pid"] == payload["pid"]
    assert json.loads(worker_file.read_text())["status"] == "surge_paper_trade"
