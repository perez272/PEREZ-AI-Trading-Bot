"""Deterministic proof that a PAPER trade can close and reach AI memory.

This is deliberately isolated from the production memory database and from
broker APIs. It proves the real execution -> monitor -> outcome-memory path
without fabricating a market result inside production state.
"""
from pathlib import Path
import tempfile

from src import ai_memory, live_trade_monitor
from src.trade_engine import create_trade


def main():
    original_db = ai_memory.DB_PATH
    with tempfile.TemporaryDirectory(prefix="perez-learning-proof-") as tmp:
        ai_memory.DB_PATH = Path(tmp) / "memory.db"

        resolved = {
            "status": "CONTRACT VALID",
            "contract": "NIFTY-PROOF-CE",
            "exchange": "NFO",
            "token": "PROOF",
            "expiry": "2026-08-27",
            "strike": 25000,
            "lotsize": 1,
            "ltp": 10.0,
        }
        trade = create_trade("NIFTY", 25000.0, "BUY CE", 50000.0, resolved=resolved)
        if trade.get("status") != "PAPER TRADE ACTIVE":
            raise AssertionError(f"paper trade was not created: {trade}")

        # Use the real monitor and real ai_memory closure path, but inject a
        # deterministic quote so the proof never depends on broker availability.
        result = live_trade_monitor.run_monitor(
            trade,
            poll_seconds=0,
            get_ltp=lambda exchange, contract, token: 11.0,
            notify=False,
            log_path=str(Path(tmp) / "trades.csv"),
        )

        assert result and result["closed"] is True
        assert result["exit_reason"] == "TARGET2"
        assert result["pnl"] == 1.0

        summary = ai_memory.learning_summary()
        assert summary["overall"]["n"] == 1
        assert summary["overall"]["wins"] == 1
        assert summary["overall"]["pnl"] == 1.0
        assert summary["recent"][0]["trade_id"] == trade["trade_id"]

        # Prove idempotency: a duplicate closure cannot be learned twice.
        duplicate = ai_memory.remember_outcome(trade, result, regime="PROOF")
        assert duplicate["stored"] is False and duplicate["duplicate"] is True
        assert ai_memory.learning_summary()["overall"]["n"] == 1

        print("=== PEREZ AI LEARNING PROOF: PASS ===")
        print(f"trade_id          : {trade['trade_id']}")
        print(f"paper_entry       : Rs {trade['entry']:.2f}")
        print(f"paper_exit        : Rs {result['current']:.2f}")
        print(f"exit_reason       : {result['exit_reason']}")
        print(f"realized_pnl      : Rs {result['pnl']:.2f}")
        print(f"completed_trades  : {summary['overall']['n']}")
        print(f"wins              : {summary['overall']['wins']}")
        print("duplicate_guard   : PASS")
        print("production_db     : NOT TOUCHED")

    ai_memory.DB_PATH = original_db


if __name__ == "__main__":
    main()
