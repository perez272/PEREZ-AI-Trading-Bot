import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, reset_client, scan_market, select_best_candidate
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade, resolve_option_contract
from src.options_engine_adapter import evaluate_option_candidate
from src.high_conviction_discovery import discover


CAPITAL = 50000
MINIMUM_SCORE = 55
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 300.0
RESCAN_DELAY_SECONDS = 300
SCANNER_RECOVERY_DELAY_SECONDS = 15
MAX_EMPTY_SCAN_RECOVERIES = 3
HEARTBEAT_FILE = Path("data/runtime/main_heartbeat")

OPTIONS_MIN_SCORE = 80
OPTIONS_STOP_LOSS_PCT = 2.0
OPTIONS_TARGETS_PCT = (5.0, 10.0, 15.0, 20.0)


def touch_heartbeat():
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.touch()
    except OSError as exc:
        print(f"[SELF-HEAL] Heartbeat write failed: {exc!r}")


def wait_for_0915_ist():
    tz = ZoneInfo("Asia/Kolkata")
    start = dt_time(9, 15)
    while True:
        touch_heartbeat()
        now = datetime.now(tz)
        if now.time() >= start:
            print("09:15 IST reached — starting market-data initialization and live-data scan.")
            return
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR 09:15 IST — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def scan_with_recovery():
    """Run the scanner and automatically rebuild the broker session after failures."""
    for attempt in range(1, MAX_EMPTY_SCAN_RECOVERIES + 1):
        touch_heartbeat()
        try:
            results = scan_market()
            if results:
                touch_heartbeat()
                return results
            print(
                f"[SELF-HEAL] Scan returned no valid symbols "
                f"({attempt}/{MAX_EMPTY_SCAN_RECOVERIES}); refreshing broker client."
            )
        except Exception as exc:
            print(
                f"[SELF-HEAL] Scanner failure ({attempt}/{MAX_EMPTY_SCAN_RECOVERIES}): {exc!r}"
            )

        reset_client()
        touch_heartbeat()
        time.sleep(SCANNER_RECOVERY_DELAY_SECONDS)

    print("[SELF-HEAL] Scanner recovery exhausted; staying fail-closed and retrying next cycle.")
    return []


def main():
    wait_for_0915_ist()

    print("=" * 60)
    print("PEREZ AI PAPER-TRADING BOT")
    print("Paper mode only — no real orders are placed.")
    print("09:15 IST — market-data initialization / fresh-data scanning enabled.")
    print("Auto-reconnect / self-healing enabled for transient broker and scanner failures.")
    print("=" * 60)

    while True:
        try:
            touch_heartbeat()
            allowed, reason, summary = can_open_new_trade(MAX_TRADES_PER_DAY, MAX_DAILY_LOSS)
            print(
                f"Today's closed trades: {summary['closed_trades']} | "
                f"Today's P/L: Rs {summary['pnl']:.2f}"
            )
            if not allowed:
                print(f"Bot stopped: {reason}")
                return

            results = scan_with_recovery()
            if not results:
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            print_results(results)

            admitted, watchlist, rejected = discover()
            print(
                f"Fundamental candidates admitted: {len(admitted)} | "
                f"watchlist: {len(watchlist)} | rejected: {len(rejected)}"
            )

            if not admitted:
                print("No HIGH-CONVICTION fundamental candidate. No paper trade will be created.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            admitted_symbols = {x["symbol"] for x in admitted}
            eligible_market = [x for x in results if x.get("symbol", "").upper() in admitted_symbols]
            candidate = select_best_candidate(eligible_market, MINIMUM_SCORE)

            if not candidate:
                print("High-conviction fundamental candidate exists, but no qualifying market signal.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            print(f"HIGH-CONVICTION PAPER CANDIDATE: {candidate['symbol']} | Score {candidate['score']}/100")

            if not candidate.get("symbol"):
                print("Safety rejection: candidate has no symbol.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            option_type = "CE" if candidate["signal"] == "BUY CE" else "PE"

            contract_probe = resolve_option_contract(
                candidate["symbol"], candidate["close"], candidate["signal"]
            )

            if contract_probe.get("status") != "CONTRACT VALID":
                print("Options contract/LTP validation rejected candidate:", contract_probe)
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            gate_candidate = {
                "symbol": candidate["symbol"],
                "option_type": option_type,
                "expiry": contract_probe.get("expiry", ""),
                "ltp": contract_probe.get("ltp", 0),
                "exchange": contract_probe.get("exchange", "NFO"),
                "token": contract_probe.get("token", ""),
                "trend_score": candidate.get("score", 0),
                "momentum_score": candidate.get("score", 0),
                "volume_score": candidate.get("volume_ratio", 0),
                "vwap_score": candidate.get("score", 0),
                "index_confirmation": 8 if candidate.get("trend") else 0,
                "oi_score": 0,
                "oi_change_score": 0,
                "iv_score": 0,
                "liquidity_score": 0,
                "volatility_score": 0,
                "structure_score": 0,
                "news_confirmation": 0,
                "event_risk_penalty": 0,
                "spread_pct": 0,
                "slippage_pct": 0,
            }

            options_result = evaluate_option_candidate(gate_candidate)
            print(
                f"OPTIONS GATE: {options_result.get('options_score', 0)}/100 | "
                f"{options_result.get('options_gate', {}).get('decision', 'NO TRADE')}"
            )

            if not options_result.get("paper_trade_candidate"):
                print(
                    "Options gate rejected candidate:",
                    options_result.get("options_gate", {}).get("reasons", []),
                )
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            trade = create_trade(candidate["symbol"], candidate["close"], candidate["signal"], CAPITAL)
            if trade.get("status") != "PAPER TRADE ACTIVE":
                print("Trade was not created:", trade)
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            send_entry_alert(trade)
            result = run_monitor(trade)
            if result is None:
                print("Bot stopped manually.")
                return

            print("Trade cycle complete. Returning to scanner.")
            time.sleep(RESCAN_DELAY_SECONDS)

        except KeyboardInterrupt:
            print("Bot stopped by operator.")
            return
        except Exception as exc:
            print(f"[SELF-HEAL] Main loop recovered from error: {exc!r}")
            reset_client()
            touch_heartbeat()
            time.sleep(SCANNER_RECOVERY_DELAY_SECONDS)


if __name__ == "__main__":
    main()
