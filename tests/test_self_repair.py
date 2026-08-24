import json
import time

from src import self_repair


def test_heartbeat_age_is_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(self_repair, "HEARTBEAT", tmp_path / "heartbeat.json")
    assert self_repair.heartbeat_age() is None


def test_heartbeat_age_reads_epoch(tmp_path, monkeypatch):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps({"epoch": time.time() - 5}), encoding="utf-8")
    monkeypatch.setattr(self_repair, "HEARTBEAT", heartbeat)
    age = self_repair.heartbeat_age()
    assert age is not None
    assert 0 <= age < 10


def test_restart_is_never_attempted_when_disabled(monkeypatch, capsys):
    monkeypatch.setattr(self_repair, "ALLOW_RESTART", False)
    called = []
    monkeypatch.setattr(self_repair, "_systemctl", lambda *args: called.append(args))
    assert self_repair.restart_main_service("test") is False
    assert called == []
    assert "automatic restart disabled" in capsys.readouterr().out
