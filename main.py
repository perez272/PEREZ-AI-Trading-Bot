import os
import time
from datetime import datetime, time as dt_time, timedelta
from zoneinfo import ZoneInfo

from src.live_trade_monitor import run_monitor
from src.market_scanner import print_results, scan_market, select_best_candidate, get_client, get_scan_stats
from src.production_guard import acquire_single_instance, release_single_instance, write_heartbeat
from src.capital_manager import get_available_capital
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.trade_engine import create_trade, resolve_option_contract
from src.options_engine_adapter import evaluate_option_candidate
from src.high_conviction_discovery import discover, CANDIDATE_FILE
from src.upgrade_config import RESCAN_DELAY_SECONDS, MINIMUM_SCORE, MAX_TRADES_PER_DAY, OPTIONS_MIN_SCORE, OPTION_MAX_PREMIUM, ENTRY_START, LAST_ENTRY

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
PAPER_MODE = os.getenv("PAPER_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}


def _is_weekday(now): return now.weekday() < 5

def _in_entry_window(now): return _is_weekday(now) and ENTRY_START <= now.time() <= LAST_ENTRY

def _next_weekday_0915(now):
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now.time() >= MARKET_CLOSE or not _is_weekday(now):
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5: candidate += timedelta(days=1)
    return candidate


def wait_for_0915_ist():
    while True:
        now = datetime.now(IST)
        if _is_weekday(now) and MARKET_OPEN <= now.time() < MARKET_CLOSE:
            print("09:15 IST reached — starting market-data initialization and live-data scan.")
            return
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if not (_is_weekday(now) and now.time() < MARKET_OPEN): target = _next_weekday_0915(now)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR NEXT MARKET SESSION — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def wait_for_entry_window():
    while True:
        now = datetime.now(IST)
        if _in_entry_window(now): return
        if _is_weekday(now) and now.time() < ENTRY_START:
            target = now.replace(hour=ENTRY_START.hour, minute=ENTRY_START.minute, second=0, microsecond=0)
        else: target = _next_weekday_0915(now)
        seconds = max(1, int((target - now).total_seconds()))
        write_heartbeat("waiting_entry_window", next_entry=target.isoformat())
        print(f"WAITING FOR ENTRY WINDOW — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def _fundamental_admission(admitted, symbol):
    if not CANDIDATE_FILE.exists(): return False, "FUNDAMENTAL_CANDIDATE_FILE_MISSING"
    admitted_symbols = {str(item.get("symbol", "")).upper().strip() for item in admitted}
    return (True, "FUNDAMENTALLY_ADMITTED") if symbol.upper().strip() in admitted_symbols else (False, "UNDERLYING_NOT_FUNDAMENTALLY_ADMITTED")


def main():
    lock = acquire_single_instance(); write_heartbeat("starting")
    try:
        wait_for_0915_ist()
        print("=" * 72)
        print("PEREZ AI PAPER-TRADING BOT — DYNAMIC CAPITAL / AFFORDABLE OPTIONS")
        print(f"Execution mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
        print("Paper mode only — no real orders are placed." if PAPER_MODE else "LIVE mode — capital is tied to Angel One RMS.")
        print(f"Capital source: {'PAPER_CAPITAL virtual balance' if PAPER_MODE else 'Angel One RMS available cash'}")
        print(f"Preferred option premium: <= Rs {OPTION_MAX_PREMIUM:.2f}")
        print(f"Market score threshold: {MINIMUM_SCORE} | Options threshold: {OPTIONS_MIN_SCORE}")
        print(f"Entry window: {ENTRY_START.strftime('%H:%M')}-{LAST_ENTRY.strftime('%H:%M')} IST, weekdays only")
        print(f"Rescan interval: {RESCAN_DELAY_SECONDS}s")
        print("=" * 72)

        while True:
            wait_for_entry_window(); write_heartbeat("capital_check")
            try: capital = get_available_capital(get_client(), paper_mode=PAPER_MODE)
            except Exception as exc:
                write_heartbeat("capital_error", error=str(exc)); print(f"CAPITAL CHECK FAILED — no scan/trade allowed: {exc}"); time.sleep(30); continue
            print(f"{'Virtual' if PAPER_MODE else 'Available'} capital: Rs {capital:.2f} | Dynamic 2% daily loss limit: Rs {capital * 0.02:.2f}")
            allowed, reason, summary = can_open_new_trade(MAX_TRADES_PER_DAY, None, capital)
            print(f"Today's closed trades: {summary['closed_trades']} | Today's P/L: Rs {summary['pnl']:.2f}")
            if not allowed:
                write_heartbeat("blocked", reason=reason, capital=capital); print(f"Bot waiting: {reason}"); time.sleep(min(60, RESCAN_DELAY_SECONDS)); continue

            write_heartbeat("scanning", capital=capital)
            try: results = scan_market()
            except Exception as exc:
                write_heartbeat("scan_error", error=str(exc), capital=capital); print(f"MARKET SCAN FAILED — skipping this cycle: {exc}"); time.sleep(RESCAN_DELAY_SECONDS); continue
            print_results(results)
            scan_stats = get_scan_stats()
            write_heartbeat(
                "scanned",
                candidates=len(results),
                capital=capital,
                market_data_api_attempts=scan_stats["api_attempts"],
                market_data_live_refreshes=scan_stats["live_refreshes"],
                market_data_cache_hits=scan_stats["cache_hits"],
                market_data_fresh_candles=scan_stats["fresh_candles"],
                market_data_fresh_to_decision=scan_stats["fresh_to_decision_engine"],
                decision_evaluations=scan_stats["decision_evaluations"],
                market_data_blocked_or_failed=scan_stats["api_blocked_or_failed"],
                market_data_invalid_or_stale=scan_stats["stale_or_invalid"],
            )

            try: admitted, rejected = discover()
            except Exception as exc:
                write_heartbeat("discovery_error", error=str(exc), capital=capital); print(f"FUNDAMENTAL DISCOVERY FAILED — fail-closed: {exc}"); time.sleep(RESCAN_DELAY_SECONDS); continue
            print(f"Fundamental candidates admitted: {len(admitted)} | rejected: {len(rejected)}")

            candidate = select_best_candidate(results, MINIMUM_SCORE)
            if not candidate:
                print("No qualifying underlying market signal."); time.sleep(RESCAN_DELAY_SECONDS); continue
            admitted_ok, admission_reason = _fundamental_admission(admitted, candidate["symbol"])
            if not admitted_ok:
                write_heartbeat("fundamental_reject", symbol=candidate["symbol"], reason=admission_reason)
                print(f"FUNDAMENTAL GATE REJECTED {candidate['symbol']}: {admission_reason}"); time.sleep(RESCAN_DELAY_SECONDS); continue

            print(f"HIGH-CONVICTION UNDERLYING CANDIDATE: {candidate['symbol']} | Score {candidate['score']}/100")
            try: contract_probe = resolve_option_contract(candidate["symbol"], candidate["close"], candidate["signal"])
            except Exception as exc:
                print(f"OPTION CONTRACT LOOKUP FAILED — skipping candidate: {exc}"); time.sleep(RESCAN_DELAY_SECONDS); continue
            if contract_probe.get("status") != "CONTRACT VALID":
                print("Affordable options scanner rejected underlying:", contract_probe); time.sleep(RESCAN_DELAY_SECONDS); continue
            print(f"AFFORDABLE OPTION: {contract_probe['contract']} Strike={contract_probe['strike']} LTP=Rs {contract_probe['ltp']:.2f} Expiry={contract_probe['expiry']} Lotsize={contract_probe['lotsize']}")

            mtf_direction = candidate.get("m15_trend") if candidate.get("m15_trend") == candidate.get("h1_trend") else "MIXED"
            gate_candidate = {
                "symbol": candidate["symbol"], "option_type": "CE" if candidate["signal"] == "BUY CE" else "PE",
                "expiry": contract_probe.get("expiry", ""), "ltp": contract_probe.get("ltp", 0),
                "exchange": contract_probe.get("exchange", "NFO"), "token": contract_probe.get("token", ""),
                "underlying_signal": candidate["signal"], "mtf_direction": mtf_direction,
                "trend_score": 0, "momentum_score": 0, "volume_score": 0, "vwap_score": 0,
                "index_confirmation": 8 if ((candidate["signal"] == "BUY CE" and mtf_direction == "BULLISH") or (candidate["signal"] == "BUY PE" and mtf_direction == "BEARISH")) else 0,
                "oi_score": 0, "oi_change_score": 0, "iv_score": 0, "liquidity_score": 0,
                "volatility_score": 0, "structure_score": 0, "news_confirmation": 0,
                "event_risk_penalty": 0, "spread_pct": 0, "slippage_pct": 0,
            }
            try: options_result = evaluate_option_candidate(gate_candidate)
            except Exception as exc:
                print(f"OPTIONS GATE FAILED — skipping candidate: {exc}"); time.sleep(RESCAN_DELAY_SECONDS); continue
            gate = options_result.get("options_gate", {})
            print(f"OPTIONS GATE: {options_result.get('options_score', 0)}/100 | {gate.get('decision', 'NO TRADE')}")
            if not options_result.get("paper_trade_candidate"):
                print("Options gate rejected candidate:", gate.get("reasons", [])); time.sleep(RESCAN_DELAY_SECONDS); continue

            # The gate uses a fresh FULL quote. Reuse that exact live price for
            # sizing and re-check the premium cap before creating the paper trade.
            live_ltp = float(options_result.get("ltp", 0) or 0)
            if live_ltp <= 0 or live_ltp > OPTION_MAX_PREMIUM:
                print(f"LIVE OPTION PRICE CHANGED — no trade: Rs {live_ltp:.2f} exceeds allowed premium or is invalid")
                time.sleep(RESCAN_DELAY_SECONDS); continue
            contract_probe["ltp"] = live_ltp

            write_heartbeat("creating_trade", symbol=candidate["symbol"], capital=capital)
            try: trade = create_trade(candidate["symbol"], candidate["close"], candidate["signal"], capital, resolved_contract=contract_probe)
            except Exception as exc:
                print(f"TRADE CREATION FAILED — no trade opened: {exc}"); time.sleep(RESCAN_DELAY_SECONDS); continue
            if trade.get("status") != "PAPER TRADE ACTIVE":
                print("Trade was not created:", trade); time.sleep(RESCAN_DELAY_SECONDS); continue
            trade.update({"options_score": options_result.get("options_score", 0), "fundamental_admitted": True, "underlying_score": candidate.get("score", 0), "option_live_ltp_at_gate": live_ltp, "mtf_direction": mtf_direction})
            print(f"PAPER TRADE: {trade['contract']} | quantity={trade['quantity']} | investment=Rs {trade['investment']:.2f} | capital utilization={trade['capital_utilization_pct']:.2f}%")
            try: send_entry_alert(trade)
            except Exception as exc: print(f"TELEGRAM ALERT FAILED — trade remains paper-managed: {exc}")

            write_heartbeat("monitoring", symbol=trade.get("symbol"), contract=trade.get("contract"))
            try: result = run_monitor(trade)
            except Exception as exc:
                write_heartbeat("monitor_error", symbol=trade.get("symbol"), error=str(exc)); print(f"TRADE MONITOR FAILED — lifecycle unresolved; halting scanner: {exc}"); return
            if result is None:
                write_heartbeat("stopped"); print("Bot stopped manually."); return
            print("Trade cycle complete. Returning to scanner."); write_heartbeat("trade_complete", symbol=trade.get("symbol")); time.sleep(RESCAN_DELAY_SECONDS)
    finally:
        write_heartbeat("stopped"); release_single_instance(lock)


if __name__ == "__main__": main()
