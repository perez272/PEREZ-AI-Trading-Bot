from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Optional
import json
import os

UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class PositionRiskState:
    trade_id: str
    entry_price: float
    highest_price: float
    trailing_stop: Optional[float] = None
    sl_triggers: int = 0
    reentries: int = 0
    active: bool = True
    created_at: str = ""
    last_update_at: str = ""


@dataclass
class GlobalRiskState:
    consecutive_losses: int = 0
    circuit_breaker_until: Optional[str] = None
    last_failure_trade_id: Optional[str] = None
    updated_at: str = ""


class TradingRiskManager:

    def __init__(
        self,
        state_file="data/runtime/trading_risk_state.json",
        trailing_stop_pct=15.0,
        max_sl_triggers_per_lineage=2,
        max_consecutive_losses=3,
        circuit_breaker_hours=2.0,
    ):
        if not 0 < trailing_stop_pct < 100:
            raise ValueError("trailing_stop_pct must be between 0 and 100")
        if max_sl_triggers_per_lineage < 1:
            raise ValueError("max_sl_triggers_per_lineage must be >= 1")
        if max_consecutive_losses < 1:
            raise ValueError("max_consecutive_losses must be >= 1")
        if circuit_breaker_hours <= 0:
            raise ValueError("circuit_breaker_hours must be > 0")

        self.state_file = Path(state_file)
        self.trailing_stop_pct = float(trailing_stop_pct)
        self.max_sl_triggers_per_lineage = int(max_sl_triggers_per_lineage)
        self.max_consecutive_losses = int(max_consecutive_losses)
        self.circuit_breaker_hours = float(circuit_breaker_hours)

        self._lock = RLock()
        self.positions = {}
        self.global_state = GlobalRiskState()

        self._load_state()

    # ------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "global_state": asdict(self.global_state),
            "positions": {
                k: asdict(v) for k, v in self.positions.items()
            },
        }

        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, self.state_file)

    def _load_state(self):
        if not self.state_file.exists():
            self._save_state()
            return

        try:
            raw = json.loads(self.state_file.read_text())

            self.global_state = GlobalRiskState(
                **raw.get("global_state", {})
            )

            self.positions = {
                trade_id: PositionRiskState(**data)
                for trade_id, data
                in raw.get("positions", {}).items()
            }

        except Exception as exc:
            raise RuntimeError(
                f"Cannot safely load risk state: {exc}"
            ) from exc

    # ------------------------------------------------------------
    # Circuit breaker
    # ------------------------------------------------------------

    def is_circuit_breaker_active(self):
        with self._lock:
            until = self.global_state.circuit_breaker_until

            if not until:
                return False

            try:
                breaker_until = datetime.fromisoformat(until)
            except ValueError:
                return True

            if utc_now() < breaker_until:
                return True

            self.global_state.circuit_breaker_until = None
            self.global_state.updated_at = utc_now().isoformat()
            self._save_state()

            return False

    def circuit_breaker_remaining(self):
        with self._lock:
            until = self.global_state.circuit_breaker_until

            if not until:
                return timedelta(0)

            try:
                remaining = (
                    datetime.fromisoformat(until) - utc_now()
                )
            except ValueError:
                return timedelta.max

            if remaining.total_seconds() <= 0:
                self.global_state.circuit_breaker_until = None
                self.global_state.updated_at = utc_now().isoformat()
                self._save_state()
                return timedelta(0)

            return remaining

    def _activate_circuit_breaker(self, trade_id):
        now = utc_now()

        until = now + timedelta(
            hours=self.circuit_breaker_hours
        )

        self.global_state.circuit_breaker_until = until.isoformat()
        self.global_state.last_failure_trade_id = trade_id
        self.global_state.updated_at = now.isoformat()

        self._save_state()

    # ------------------------------------------------------------
    # Master entry gate
    # ------------------------------------------------------------

    def can_open_trade(self, trade_id, lineage_id=None):
        with self._lock:

            if self.is_circuit_breaker_active():
                remaining = self.circuit_breaker_remaining()

                return (
                    False,
                    "CIRCUIT_BREAKER_ACTIVE:"
                    f"{remaining.total_seconds():.0f}s",
                )

            key = lineage_id or trade_id
            existing = self.positions.get(key)

            if existing:
                if not existing.active:
                    return False, "TRADE_LINEAGE_CLOSED"

                if (
                    existing.sl_triggers
                    >= self.max_sl_triggers_per_lineage
                ):
                    return (
                        False,
                        "TRADE_LINEAGE_SL_LIMIT_REACHED",
                    )

            return True, "OK"

    # ------------------------------------------------------------
    # Entry registration
    # ------------------------------------------------------------

    def register_entry(
        self,
        trade_id,
        entry_price,
        lineage_id=None,
    ):
        if entry_price <= 0:
            raise ValueError("entry_price must be > 0")

        with self._lock:
            key = lineage_id or trade_id
            existing = self.positions.get(key)
            now = utc_now().isoformat()

            if existing:
                if not existing.active:
                    raise RuntimeError(
                        "Cannot re-enter closed trade lineage"
                    )

                if (
                    existing.sl_triggers
                    >= self.max_sl_triggers_per_lineage
                ):
                    raise RuntimeError(
                        "Maximum SL triggers reached"
                    )

                existing.reentries += 1
                existing.entry_price = entry_price
                existing.highest_price = entry_price
                existing.trailing_stop = None
                existing.last_update_at = now

                self._save_state()
                return existing

            position = PositionRiskState(
                trade_id=key,
                entry_price=entry_price,
                highest_price=entry_price,
                created_at=now,
                last_update_at=now,
            )

            self.positions[key] = position
            self._save_state()

            return position

    # ------------------------------------------------------------
    # Dynamic trailing stop
    # ------------------------------------------------------------

    def update_trailing_stop(
        self,
        trade_id,
        current_price,
    ):
        if current_price <= 0:
            raise ValueError("current_price must be > 0")

        with self._lock:
            position = self.positions.get(trade_id)

            if not position:
                raise KeyError(
                    f"Unknown trade_id: {trade_id}"
                )

            if not position.active:
                return position.trailing_stop, False

            now = utc_now()

            # Trailing begins only after the trade becomes profitable.
            if current_price <= position.entry_price:
                position.last_update_at = now.isoformat()
                self._save_state()
                return position.trailing_stop, False

            # Highest-watermark tracking.
            if current_price > position.highest_price:
                position.highest_price = current_price

            stop = (
                position.highest_price
                * (1.0 - self.trailing_stop_pct / 100.0)
            )

            # Stop can only move upward.
            if position.trailing_stop is None:
                position.trailing_stop = stop
            else:
                position.trailing_stop = max(
                    position.trailing_stop,
                    stop,
                )

            position.last_update_at = now.isoformat()
            self._save_state()

            return (
                position.trailing_stop,
                current_price <= position.trailing_stop,
            )

    # ------------------------------------------------------------
    # SL lineage limit
    # ------------------------------------------------------------

    def record_stop_loss(self, trade_id):
        with self._lock:
            position = self.positions.get(trade_id)

            if not position:
                raise KeyError(
                    f"Unknown trade_id: {trade_id}"
                )

            position.sl_triggers += 1

            if (
                position.sl_triggers
                >= self.max_sl_triggers_per_lineage
            ):
                position.active = False
                self._save_state()

                return (
                    False,
                    "TRADE_LINEAGE_EXHAUSTED:"
                    f"{position.sl_triggers}/"
                    f"{self.max_sl_triggers_per_lineage}",
                )

            self._save_state()

            return (
                True,
                "REENTRY_ALLOWED:"
                f"{position.sl_triggers}/"
                f"{self.max_sl_triggers_per_lineage}",
            )

    # ------------------------------------------------------------
    # Global consecutive-loss tracker
    # ------------------------------------------------------------

    def record_trade_result(self, trade_id, pnl, stop_loss=False):
        with self._lock:
            now = utc_now()

            position = self.positions.get(trade_id)

            if position:
                # SL lineage state is managed by record_stop_loss().
                # Other completed trades close their lineage here.
                if not stop_loss:
                    position.active = False
                position.last_update_at = now.isoformat()

            if pnl > 0:
                self.global_state.consecutive_losses = 0
                self.global_state.last_failure_trade_id = None

            else:
                self.global_state.consecutive_losses += 1
                self.global_state.last_failure_trade_id = trade_id

                if (
                    self.global_state.consecutive_losses
                    >= self.max_consecutive_losses
                ):
                    self._activate_circuit_breaker(trade_id)
                    return

            self.global_state.updated_at = now.isoformat()
            self._save_state()

    # ------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------

    def status(self):
        remaining = self.circuit_breaker_remaining()

        return {
            "consecutive_losses":
                self.global_state.consecutive_losses,

            "circuit_breaker_active":
                remaining.total_seconds() > 0,

            "circuit_breaker_remaining_seconds":
                max(0, int(remaining.total_seconds())),

            "trailing_stop_pct":
                self.trailing_stop_pct,

            "max_sl_triggers_per_lineage":
                self.max_sl_triggers_per_lineage,

            "active_positions":
                sum(
                    1
                    for p in self.positions.values()
                    if p.active
                ),
        }
