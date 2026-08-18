import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate
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

OPTIONS_MIN_SCORE = 80
OPTIONS_STOP_LOSS_PCT = 2.0
OPTIONS_TARGETS_PCT = (5.0, 10.0, 15.0, 20.0)


def wait_for_0940_ist():
    tz = ZoneInfo("Asia/Kolkata")
    start = dt_time(9, 40)
    while True:
        now = datetime.now(tz)
        if now.time() >= start:
            print("09:40 IST reached — starting live-data scan.")
            return
        target = now.replace(hour=9, minute=40, second=0, microsecond=0)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR 09:40 IST — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def main():
    wait_for_0940_ist()

    print("=" * 60)
    print("PEREZ AI PAPER-TRADING BOT")
    print("Paper mode only — no real orders are placed.")
    print("=" * 60)

    while True:
        allowed, reason, summary = can_open_new_trade(MAX_TRADES_PER_DAY, MAX_DAILY_LOSS)
        print(
            f"Today's closed trades: {summary['closed_trades']} | "
            f"Today's P/L: Rs {summary['pnl']:.2f}"
        )
        if not allowed:
            print(f"Bot stopped: {reason}")
            return

        results = scan_market()
        print_results(results)

        admitted, rejected = discover()
        print(f"Fundamental candidates admitted: {len(admitted)} | rejected: {len(rejected)}")

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

        # Validate contract/LTP only. This does NOT create a paper trade.
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

        # Final creation happens ONLY after all gates pass.
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


if __name__ == "__main__":
    main()
