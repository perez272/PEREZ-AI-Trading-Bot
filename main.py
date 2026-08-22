import os
import time
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate, get_client
from src.production_guard import acquire_single_instance, release_single_instance, write_heartbeat
from src.capital_manager import get_available_capital
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade, resolve_option_contract
from src.options_engine_adapter import evaluate_option_candidate
from src.high_conviction_discovery import discover
from src.ai_memory import remember_observation, remember_outcome, remember_rejection, learned_confidence
from src.regime_engine import regime_summary
from src.ensemble_engine import ensemble_score, decision_band
from src.upgrade_config import (
    RESCAN_DELAY_SECONDS,
    MINIMUM_SCORE,
    MAX_TRADES_PER_DAY,
    OPTIONS_MIN_SCORE,
    OPTION_MAX_PREMIUM,
)

IST = ZoneInfo("Asia/Kolkata")
PAPER_MODE = os.getenv("PAPER_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


def wait_for_0915_ist():
    start = dt_time(9, 15)
    while True:
        now = datetime.now(IST)
        if now.time() >= start:
            print("09:15 IST reached — starting market-data initialization and live-data scan.")
            return
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR 09:15 IST — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def main():
    lock = acquire_single_instance()
    write_heartbeat("starting")
    try:
        wait_for_0915_ist()
        print("=" * 72)
        print("PEREZ AI PAPER-TRADING BOT — ADAPTIVE AI / REGIME / OPTIONS")
        print(f"Execution mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
        print("Paper mode only — no real orders are placed." if PAPER_MODE else "LIVE mode — capital is tied to Angel One RMS.")
        print(f"Capital source: {'PAPER_CAPITAL virtual balance' if PAPER_MODE else 'Angel One RMS available cash'}")
        print(f"Preferred option premium: <= Rs {OPTION_MAX_PREMIUM:.2f}")
        print("Full available capital: used for whole affordable lots when a trade passes all gates")
        print(f"Market score threshold: {MINIMUM_SCORE} | Options threshold: {OPTIONS_MIN_SCORE}")
        print(f"Rescan interval: {RESCAN_DELAY_SECONDS}s")
        print("Persistent AI learning memory: ENABLED")
        print("Regime engine: ENABLED | Ensemble engine: ENABLED | Rejection learning: ENABLED")
        print("Live-order authority: DISABLED")
        print("=" * 72)

        while True:
            write_heartbeat("capital_check")
            try:
                capital = get_available_capital(get_client(), paper_mode=PAPER_MODE)
            except Exception as exc:
                write_heartbeat("capital_error", error=str(exc))
                print(f"CAPITAL CHECK FAILED — no scan/trade allowed: {exc}")
                time.sleep(30)
                continue

            daily_loss_limit = capital * 0.02
            print(f"{'Virtual' if PAPER_MODE else 'Available'} capital: Rs {capital:.2f} | Dynamic 2% daily loss limit: Rs {daily_loss_limit:.2f}")
            allowed, reason, summary = can_open_new_trade(MAX_TRADES_PER_DAY, None, capital)
            print(f"Today's closed trades: {summary['closed_trades']} | Today's P/L: Rs {summary['pnl']:.2f}")

            if not allowed:
                write_heartbeat("blocked", reason=reason, capital=capital)
                print(f"Bot waiting: {reason}")
                time.sleep(min(60, RESCAN_DELAY_SECONDS))
                continue

            write_heartbeat("scanning", capital=capital)
            try:
                results = scan_market()
            except Exception as exc:
                write_heartbeat("scan_error", error=str(exc), capital=capital)
                print(f"MARKET SCAN FAILED — skipping this cycle: {exc}")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            print_results(results)
            write_heartbeat("scanned", candidates=len(results), capital=capital)

            try:
                admitted, rejected = discover()
            except Exception as exc:
                admitted, rejected = [], []
                write_heartbeat("discovery_error", error=str(exc), capital=capital)
                print(f"FUNDAMENTAL DISCOVERY FAILED — continuing with market-only scan: {exc}")
            print(f"Fundamental candidates admitted: {len(admitted)} | rejected: {len(rejected)}")

            candidate = select_best_candidate(results, MINIMUM_SCORE)
            if not candidate:
                print("No qualifying underlying market signal.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            regime = regime_summary(candidate)
            learned = learned_confidence(candidate.get("symbol"), regime["regime"])
            preliminary, _ = ensemble_score(candidate, options_score=0, learned_confidence=learned, regime_bonus=70 if regime["structure"] == "TRENDING" else 50)
            band = decision_band(preliminary)
            candidate["regime"] = regime["regime"]
            candidate["ensemble_score"] = preliminary
            print(f"AI ENSEMBLE: {preliminary:.0f}/100 | {band} | Regime={regime['regime']} | Learned confidence={learned:.0f}%")

            if preliminary < MINIMUM_SCORE:
                try:
                    remember_rejection(candidate, f"ENSEMBLE_BELOW_{MINIMUM_SCORE}", regime=regime["regime"])
                except Exception as exc:
                    print(f"AI MEMORY WARNING — rejection not stored: {exc}")
                print(f"AI ensemble rejected candidate below {MINIMUM_SCORE}/100.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            print(f"HIGH-CONVICTION UNDERLYING CANDIDATE: {candidate['symbol']} | Market {candidate['score']}/100 | Ensemble {preliminary:.0f}/100")
            option_type = "CE" if candidate["signal"] == "BUY CE" else "PE"
            try:
                contract_probe = resolve_option_contract(candidate["symbol"], candidate["close"], candidate["signal"])
            except Exception as exc:
                print(f"OPTION CONTRACT LOOKUP FAILED — skipping candidate: {exc}")
                try:
                    remember_rejection(candidate, "OPTION_CONTRACT_LOOKUP_FAILED", regime=regime["regime"])
                except Exception:
                    pass
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            if contract_probe.get("status") != "CONTRACT VALID":
                print("Affordable options scanner rejected underlying:", contract_probe)
                try:
                    remember_rejection(candidate, "INVALID_OR_UNAFFORDABLE_CONTRACT", regime=regime["regime"])
                except Exception:
                    pass
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            print(
                f"AFFORDABLE OPTION: {contract_probe['contract']} "
                f"Strike={contract_probe['strike']} LTP=Rs {contract_probe['ltp']:.2f} "
                f"Expiry={contract_probe['expiry']} Lotsize={contract_probe['lotsize']}"
            )

            gate_candidate = {
                "symbol": candidate["symbol"],
                "option_type": option_type,
                "expiry": contract_probe.get("expiry", ""),
                "ltp": contract_probe.get("ltp", 0),
                "exchange": contract_probe.get("exchange", "NFO"),
                "token": contract_probe.get("token", ""),
                "trend_score": candidate.get("score", 0),
                "momentum_score": candidate.get("score", 0),
                "breakout_score": candidate.get("breakout_score", candidate.get("score", 0)),
                "mean_reversion_score": candidate.get("mean_reversion_score", 50),
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

            try:
                options_result = evaluate_option_candidate(gate_candidate)
            except Exception as exc:
                print(f"OPTIONS GATE FAILED — skipping candidate: {exc}")
                try:
                    remember_rejection(candidate, "OPTIONS_GATE_EXCEPTION", regime=regime["regime"])
                except Exception:
                    pass
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            try:
                remember_observation(candidate, options_result, regime=regime["regime"])
            except Exception as exc:
                print(f"AI MEMORY WARNING — observation not stored: {exc}")

            gate = options_result.get("options_gate", {})
            options_score = float(options_result.get("options_score", 0) or 0)
            final_score, _ = ensemble_score(
                candidate,
                options_score=options_score,
                learned_confidence=learned,
                regime_bonus=70 if regime["structure"] == "TRENDING" else 50,
            )
            candidate["ensemble_score"] = final_score
            print(f"OPTIONS GATE: {options_score:.0f}/100 | {gate.get('decision', 'NO TRADE')}")
            print(f"FINAL ENSEMBLE: {final_score:.0f}/100 | {decision_band(final_score)}")

            if not options_result.get("paper_trade_candidate"):
                reasons = gate.get("reasons", [])
                print("Options gate rejected candidate:", reasons)
                try:
                    remember_rejection(candidate, "OPTIONS_GATE: " + ",".join(map(str, reasons)), options_result, regime["regime"])
                except Exception as exc:
                    print(f"AI MEMORY WARNING — rejection not stored: {exc}")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            if final_score < MINIMUM_SCORE:
                print(f"Final ensemble rejected candidate below {MINIMUM_SCORE}/100.")
                try:
                    remember_rejection(candidate, f"FINAL_ENSEMBLE_BELOW_{MINIMUM_SCORE}", options_result, regime["regime"])
                except Exception:
                    pass
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            write_heartbeat("creating_trade", symbol=candidate["symbol"], capital=capital)
            try:
                trade = create_trade(
                    candidate["symbol"],
                    candidate["close"],
                    candidate["signal"],
                    capital,
                    resolved=contract_probe,
                )
            except Exception as exc:
                print(f"TRADE CREATION FAILED — no trade opened: {exc}")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            if trade.get("status") != "PAPER TRADE ACTIVE":
                print("Trade was not created:", trade)
                try:
                    remember_rejection(candidate, "TRADE_CREATION_REJECTED", options_result, regime["regime"])
                except Exception:
                    pass
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            trade["score"] = candidate.get("score", 0)
            trade["ensemble_score"] = final_score
            trade["options_score"] = options_result.get("options_score", 0)
            trade["ai_confidence"] = learned
            trade["regime"] = regime["regime"]
            trade["ai_memory_enabled"] = True
            trade["live_orders"] = False
            print(
                f"PAPER TRADE: {trade['contract']} | quantity={trade['quantity']} | "
                f"investment=Rs {trade['investment']:.2f} | capital utilization={trade['capital_utilization_pct']:.2f}%"
            )
            try:
                send_entry_alert(trade)
            except Exception as exc:
                print(f"TELEGRAM ALERT FAILED — trade remains paper-managed: {exc}")

            write_heartbeat("monitoring", symbol=trade.get("symbol"), contract=trade.get("contract"))
            try:
                result = run_monitor(trade)
            except Exception as exc:
                print(f"TRADE MONITOR FAILED — returning to scanner: {exc}")
                result = True

            if result is None:
                write_heartbeat("stopped")
                print("Bot stopped manually.")
                return

            if isinstance(result, dict) and result.get("closed"):
                try:
                    remember_outcome(trade, result, regime=trade.get("regime", "unknown"))
                    print("AI MEMORY: paper-trade outcome stored for future learning.")
                except Exception as exc:
                    print(f"AI MEMORY WARNING — outcome not stored: {exc}")

            print("Trade cycle complete. Returning to scanner.")
            write_heartbeat("trade_complete", symbol=trade.get("symbol"))
            time.sleep(RESCAN_DELAY_SECONDS)
    finally:
        write_heartbeat("stopped")
        release_single_instance(lock)


if __name__ == "__main__":
    main()
