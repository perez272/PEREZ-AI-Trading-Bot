import time

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade
from src.options_engine_adapter import evaluate_option_candidate
from src.high_conviction_discovery import discover


CAPITAL = 50000
MINIMUM_SCORE = 55
MAX_TRADES_PER_DAY = 3
MAX_DAILY_LOSS = 300.0
RESCAN_DELAY_SECONDS = 300

# OPTIONS PAPER-TRADE GATE
OPTIONS_MIN_SCORE = 80
OPTIONS_STOP_LOSS_PCT = 2.0
OPTIONS_TARGETS_PCT = (5.0, 10.0, 15.0, 20.0)


def main():
    print("=" * 60)
    print("PEREZ AI PAPER-TRADING BOT")
    print("Paper mode only — no real orders are placed.")
    print("=" * 60)

    while True:
        allowed, reason, summary = can_open_new_trade(
            MAX_TRADES_PER_DAY,
            MAX_DAILY_LOSS,
        )

        print(
            f"Today's closed trades: {summary['closed_trades']} | "
            f"Today's P/L: Rs {summary['pnl']:.2f}"
        )

        if not allowed:
            print(f"Bot stopped: {reason}")
            return

        results = scan_market()
        print_results(results)

        # ============================================================
        # STRICT FUNDAMENTAL -> MARKET -> PAPER TRADE GATE
        # ============================================================
        admitted, rejected = discover()

        print(
            f"Fundamental candidates admitted: {len(admitted)} | "
            f"rejected: {len(rejected)}"
        )

        if not admitted:
            print(
                "No HIGH-CONVICTION fundamental candidate. "
                "No paper trade will be created."
            )
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        admitted_symbols = {x["symbol"] for x in admitted}

        eligible_market = [
            x for x in results
            if x.get("symbol", "").upper() in admitted_symbols
        ]

        candidate = select_best_candidate(
            eligible_market,
            MINIMUM_SCORE
        )

        if not candidate:
            print(
                "High-conviction fundamental candidate exists, "
                "but no qualifying market signal."
            )
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        print(
            f"HIGH-CONVICTION PAPER CANDIDATE: "
            f"{candidate['symbol']} | "
            f"Score {candidate['score']}/100"
        )

        # HARD SAFETY: this integration can only create paper trades.
        if not candidate.get("symbol"):
            print("Safety rejection: candidate has no symbol.")
            time.sleep(RESCAN_DELAY_SECONDS)
            continue

        trade = create_trade(
            candidate["symbol"],
            candidate["close"],
            candidate["signal"],
            CAPITAL,
        )

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
