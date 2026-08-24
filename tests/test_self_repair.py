import json
import time
from types import SimpleNamespace

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


def _run_with_heartbeat(tmp_path, monkeypatch, status, pid=1234):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps({"epoch": time.time(), "status": status, "pid": pid}), encoding="utf-8")
    monkeypatch.setattr(self_repair, "HEARTBEAT", heartbeat)
    monkeypatch.setattr(self_repair, "STARTUP_GRACE_SECONDS", 0)
    monkeypatch.setattr(self_repair, "service_active", lambda: True)
    monkeypatch.setattr(self_repair, "service_main_pid", lambda: 1234)
    monkeypatch.setattr(self_repair, "restart_main_service", lambda reason: (_ for _ in ()).throw(AssertionError(reason)))
    return self_repair.run()


def test_fresh_scanned_heartbeat_is_healthy(tmp_path, monkeypatch):
    assert _run_with_heartbeat(tmp_path, monkeypatch, "scanned") == 0


def test_fresh_capital_check_heartbeat_is_healthy(tmp_path, monkeypatch):
    assert _run_with_heartbeat(tmp_path, monkeypatch, "capital_check") == 0


def test_stopped_heartbeat_requests_recovery(tmp_path, monkeypatch):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps({"epoch": time.time(), "status": "stopped", "pid": 1234}), encoding="utf-8")
    monkeypatch.setattr(self_repair, "HEARTBEAT", heartbeat)
    monkeypatch.setattr(self_repair, "STARTUP_GRACE_SECONDS", 0)
    monkeypatch.setattr(self_repair, "service_active", lambda: True)
    monkeypatch.setattr(self_repair, "service_main_pid", lambda: 1234)
    reasons = []
    monkeypatch.setattr(self_repair, "restart_main_service", lambda reason: reasons.append(reason) or True)
    assert self_repair.run() == 0
    assert reasons == ["heartbeat explicitly stopped"]


def test_fresh_heartbeat_with_wrong_pid_requests_recovery(tmp_path, monkeypatch):
    heartbeat = tmp_path / "heartbeat.json"
    heartbeat.write_text(json.dumps({"epoch": time.time(), "status": "scanned", "pid": 9999}), encoding="utf-8")
    monkeypatch.setattr(self_repair, "HEARTBEAT", heartbeat)
    monkeypatch.setattr(self_repair, "STARTUP_GRACE_SECONDS", 0)
    monkeypatch.setattr(self_repair, "service_active", lambda: True)
    monkeypatch.setattr(self_repair, "service_main_pid", lambda: 1234)
    reasons = []
    monkeypatch.setattr(self_repair, "restart_main_service", lambda reason: reasons.append(reason) or True)
    assert self_repair.run() == 0
    assert "does not match service MainPID 1234" in reasons[0]
