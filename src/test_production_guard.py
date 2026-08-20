import json
from pathlib import Path

from src.production_guard import write_heartbeat


def test_heartbeat_is_atomic_and_machine_readable(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    heartbeat = runtime / "heartbeat.json"
    monkeypatch.setattr("src.production_guard.STATE_DIR", runtime)
    monkeypatch.setattr("src.production_guard.HEARTBEAT_PATH", heartbeat)

    payload = write_heartbeat("scanning", candidates=3)

    assert heartbeat.exists()
    saved = json.loads(heartbeat.read_text())
    assert saved["status"] == "scanning"
    assert saved["candidates"] == 3
    assert saved["pid"] == payload["pid"]
    assert isinstance(saved["epoch"], float)
