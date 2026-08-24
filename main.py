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
from src.index_momentum_strategy import select_index_momentum_candidate, build_dynamic_exits
from src.upgrade_config import (
    RESCAN_DELAY_SECONDS, MINIMUM_SCORE, MAX_TECHNICAL_BYPASS_SCORE,
    MAX_TRADES_PER_DAY, OPTIONS_MIN_SCORE, OPTION_MAX_PREMIUM,
    ENTRY_START, LAST_ENTRY, INDEX_MOMENTUM_ENABLED, INDEX_MOMENTUM_MIN_SCORE,
)

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
PAPER_MODE = os.getenv("PAPER_MODE", "true").strip().lower() in {"1", "true", "yes", "on"}
FUNDAMENTAL_GATE_REQUIRED = os.getenv("FUNDAMENTAL_GATE_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _is_weekday(now):
    return now.weekday() < 5


def _in_entry_window(now):
    return _is_weekday(now) and ENTRY_START <= now.time() <= LAST_ENTRY


def _next_weekday_0915(now):
    candidate = now.replace(hour=9, minute=15, second=0, microsecond=0)
    if now.time() >= MARKET_CLOSE or not _is_weekday(now):
        candidate += timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate += timedelta(days=1)
    return candidate


def wait_for_0915_ist():
    while True:
        now = datetime.now(IST)
        if _is_weekday(now) and MARKET_OPEN <= now.time() < MARKET_CLOSE:
            print("09:15 IST reached — starting market-data initialization and live-data scan.")
            return
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)
        if not (_is_weekday(now) and now.time() < MARKET_OPEN):
            target = _next_weekday_0915(now)
        seconds = max(1, int((target - now).total_seconds()))
        print(f"WAITING FOR NEXT MARKET SESSION — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def wait_for_entry_window():
    while True:
        now = datetime.now(IST)
        if _in_entry_window(now):
            return
        if _is_weekday(now) and now.time() < ENTRY_START:
            target = now.replace(hour=ENTRY_START.hour, minute=ENTRY_START.minute, second=0, microsecond=0)
        else:
            target = _next_weekday_0915(now)
        seconds = max(1, int((target - now).total_seconds()))
        write_heartbeat("waiting_entry_window", next_entry=target.isoformat())
        print(f"WAITING FOR ENTRY WINDOW — {seconds}s remaining")
        time.sleep(min(seconds, 60))


def _fundamental_admission(admitted, symbol, score=0, momentum_strategy=False):
    if momentum_strategy:
        return True, "INDEX_MOMENTUM_STRATEGY"
    if not FUNDAMENTAL_GATE_REQUIRED:
        return True, "TECHNICAL_GATE_MODE"
    if not CANDIDATE_FILE.exists():
        return False, "FUNDAMENTAL_CANDIDATE_FILE_MISSING"
    admitted_symbols = {str(item.get("symbol", "")).upper().strip() for item in admitted}
    if symbol.upper().strip() in admitted_symbols:
        return True, "FUNDAMENTALLY_ADMITTED"
    if score >= MAX_TECHNICAL_BYPASS_SCORE:
        return True, "HIGH_CONVICTION_TECHNICAL_BYPASS"
    return False, "UNDERLYING_NOT_FUNDAMENTALLY_ADMITTED"


def _build_option_gate_candidate(candidate, contract_probe, mtf_direction, momentum_strategy=False):
    if momentum_strategy:
        trend_score = 15
        momentum_score = 10
        volume_score = 8 if candidate.get("volume_ratio", 0) >= 1.2 else 4
        structure_score = 5 if candidate.get("momentum_score", 0) >= 80 else 3
        index_confirmation = 8 if ((candidate["signal"] == "BUY CE" and mtf_direction == "BULLISH") or (candidate["signal"] == "BUY PE" and mtf_direction == "BEARISH")) else 0
    else:
        trend_score = momentum_score = volume_score = structure_score = index_confirmation = 0
    return {
        "symbol": candidate["symbol"],
        "option_type": "CE" if candidate["signal"] == "BUY CE" else "PE",
        "expiry": contract_probe.get("expiry", ""),
        "ltp": contract_probe.get("ltp", 0),
        "exchange": contract_probe.get("exchange", "NFO"),
        "token": contract_probe.get("token", ""),
        "underlying_signal": candidate["signal"],
        "mtf_direction": mtf_direction,
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "volume_score": volume_score,
        "vwap_score": 0,
        "index_confirmation": index_confirmation,
        "oi_score": 0,
        "oi_change_score": 0,
        "iv_score": 0,
        "liquidity_score": 0,
        "volatility_score": 0,
        "structure_score": structure_score,
        "news_confirmation": 0,
        "event_risk_penalty": 0,
        "spread_pct": 0,
        "slippage_pct": 0,
    }


def _candidate_queue(results, admitted):
    """Build a ranked queue instead of stopping after one rejected candidate."""
    candidates = []
    index_candidate = select_index_momentum_candidate(results, INDEX_MOMENTUM_MIN_SCORE) if INDEX_MOMENTUM_ENABLED else None
    if index_candidate:
        candidates.append((index_candidate, True))
    technical = select_best_candidate(results, MINIMUM_SCORE)
    if technical and (not index_candidate or technical["symbol"] != index_candidate["symbol"]):
        candidates.append((technical, False))
    candidates.sort(key=lambda pair: (1 if pair[1] else 0, pair[0].get("momentum_score", 0), pair[0].get("score", 0)), reverse=True)
    return candidates


def main():
    lock = acquire_single_instance()
    write_heartbeat("starting")
    try:
        wait_for_0915_ist()
        print("=" * 72)
        print("PEREZ AI PAPER-TRADING BOT — BROAD SCANNER + MOMENTUM + CORE STRATEGIES")
        print(f"Execution mode: {'PAPER' if PAPER_MODE else 'LIVE'}")
        print("Paper mode only — no real orders are placed." if PAPER_MODE else "LIVE mode — capital is tied to Angel One RMS.")
        print(f"Preferred option premium: <= Rs {OPTION_MAX_PREMIUM:.2f}")
        print(f"Market score threshold: {MINIMUM_SCORE} | Options threshold: {OPTIONS_MIN_SCORE}")
        print(f"Index momentum: {'ENABLED' if INDEX_MOMENTUM_ENABLED else 'DISABLED'} | minimum={INDEX_MOMENTUM_MIN_SCORE}")
        print(f"Entry window: {ENTRY_START.strftime('%H:%M')}-{LAST_ENTRY.strftime('%H:%M')} IST, weekdays only")
        print(f"Fundamental hard gate: {'ENABLED' if FUNDAMENTAL_GATE_REQUIRED else 'OFF — technical high-conviction admission enabled'}")
        print("=" * 72)

        while True:
            wait_for_entry_window()
            write_heartbeat("capital_check")
            try:
                capital = get_available_capital(get_client(), paper_mode=PAPER_MODE)
            except Exception as exc:
                write_heartbeat("capital_error", error=str(exc))
                print(f"CAPITAL CHECK FAILED — no scan/trade allowed: {exc}")
                time.sleep(30)
                continue

            print(f"{'Virtual' if PAPER_MODE else 'Available'} capital: Rs {capital:.2f} | Dynamic 2% daily loss limit: Rs {capital * 0.02:.2f}")
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
            scan_stats = get_scan_stats()
            write_heartbeat("scanned", candidates=len(results), capital=capital, **{
                "market_data_api_attempts": scan_stats["api_attempts"],
                "market_data_live_refreshes": scan_stats["live_refreshes"],
                "market_data_cache_hits": scan_stats["cache_hits"],
                "market_data_fresh_candles": scan_stats["fresh_candles"],
                "market_data_fresh_to_decision": scan_stats["fresh_to_decision_engine"],
                "decision_evaluations": scan_stats["decision_evaluations"],
                "market_data_blocked_or_failed": scan_stats["api_blocked_or_failed"],
                "market_data_invalid_or_stale": scan_stats["stale_or_invalid"],
            })

            try:
                admitted, rejected = discover()
            except Exception as exc:
                admitted, rejected = [], []
                write_heartbeat("discovery_error", error=str(exc), capital=capital)
                print(f"FUNDAMENTAL DISCOVERY FAILED — continuing with technical admission: {exc}")
            print(f"Fundamental candidates admitted: {len(admitted)} | rejected: {len(rejected)}")

            queue = _candidate_queue(results, admitted)
            if not queue:
                print("No qualifying candidate after market-data, MTF, score and freshness gates.")
                time.sleep(RESCAN_DELAY_SECONDS)
                continue

            trade_opened = False
            for candidate, momentum_strategy in queue:
                symbol = candidate["symbol"]
                admitted_ok, admission_reason = _fundamental_admission(admitted, symbol, candidate.get("score", 0), momentum_strategy)
                if not admitted_ok:
                    write_heartbeat("fundamental_reject", symbol=symbol, reason=admission_reason)
                    print(f"FUNDAMENTAL GATE REJECTED {symbol}: {admission_reason}")
                    continue

                print(f"HIGH-CONVICTION UNDERLYING CANDIDATE: {symbol} | Score {candidate.get('score', 0)}/100 | Momentum={candidate.get('momentum_score', 0)}")
                try:
                    contract_probe = resolve_option_contract(symbol, candidate["close"], candidate["signal"])
                except Exception as exc:
                    print(f"OPTION CONTRACT LOOKUP FAILED for {symbol}: {exc}")
                    continue
                if contract_probe.get("status") != "CONTRACT VALID":
                    print(f"OPTION CONTRACT REJECTED for {symbol}: {contract_probe}")
                    continue

                print(f"AFFORDABLE OPTION: {contract_probe['contract']} Strike={contract_probe['strike']} LTP=Rs {contract_probe['ltp']:.2f} Expiry={contract_probe['expiry']} Lotsize={contract_probe['lotsize']}")
                mtf_direction = candidate.get("m15_trend") if candidate.get("m15_trend") == candidate.get("h1_trend") else "MIXED"
                gate_candidate = _build_option_gate_candidate(candidate, contract_probe, mtf_direction, momentum_strategy)
                try:
                    options_result = evaluate_option_candidate(gate_candidate)
                except Exception as exc:
                    print(f"OPTIONS GATE FAILED for {symbol}: {exc}")
                    continue
                gate = options_result.get("options_gate", {})
                print(f"OPTIONS GATE: {options_result.get('options_score', 0)}/100 | {gate.get('decision', 'NO TRADE')} | {', '.join(gate.get('reasons', []))}")
                if not options_result.get("paper_trade_candidate"):
                    continue

                live_ltp = float(options_result.get("ltp", 0) or 0)
                if live_ltp <= 0 or live_ltp > OPTION_MAX_PREMIUM:
                    print(f"LIVE OPTION PRICE CHANGED — no trade for {symbol}: Rs {live_ltp:.2f}")
                    continue
                contract_probe["ltp"] = live_ltp

                write_heartbeat("creating_trade", symbol=symbol, capital=capital, strategy=candidate.get("strategy", "CORE"))
                try:
                    trade = create_trade(symbol, candidate["close"], candidate["signal"], capital, resolved_contract=contract_probe)
                except Exception as exc:
                    print(f"TRADE CREATION FAILED for {symbol}: {exc}")
                    continue
                if trade.get("status") != "PAPER TRADE ACTIVE":
                    print("Trade was not created:", trade)
                    continue

                if momentum_strategy:
                    exits = build_dynamic_exits(live_ltp, candidate.get("atr", 0), live_ltp)
                    trade.update({"initial_stop_loss": exits["stop_loss"], "stop_loss": exits["stop_loss"], "target1": exits["target1"], "target2": exits["target2"], "target": exits["target2"], "strategy": "INDEX_MOMENTUM_SCALP", "momentum_score": candidate.get("momentum_score", 0), "momentum_reasons": candidate.get("momentum_reasons", [])})

                trade.update({"options_score": options_result.get("options_score", 0), "fundamental_admitted": admission_reason == "FUNDAMENTALLY_ADMITTED", "underlying_score": candidate.get("score", 0), "option_live_ltp_at_gate": live_ltp, "mtf_direction": mtf_direction})
                print(f"PAPER TRADE: {trade['contract']} | strategy={trade.get('strategy', 'CORE')} | quantity={trade['quantity']} | investment=Rs {trade['investment']:.2f}")
                print(f"EXITS: SL={trade['stop_loss']:.2f} | T1={trade['target1']:.2f} | T2={trade['target2']:.2f}")
                try:
                    send_entry_alert(trade)
                except Exception as exc:
                    print(f"TELEGRAM ALERT FAILED — trade remains paper-managed: {exc}")

                write_heartbeat("monitoring", symbol=trade.get("symbol"), contract=trade.get("contract"), strategy=trade.get("strategy", "CORE"))
                try:
                    result = run_monitor(trade)
                except Exception as exc:
                    write_heartbeat("monitor_error", symbol=trade.get("symbol"), error=str(exc))
                    print(f"TRADE MONITOR FAILED — lifecycle unresolved; halting scanner: {exc}")
                    return
                if result is None:
                    write_heartbeat("stopped")
                    print("Bot stopped manually.")
                    return
                print("Trade cycle complete. Returning to scanner.")
                write_heartbeat("trade_complete", symbol=trade.get("symbol"))
                trade_opened = True
                break

            if not trade_opened:
                print("All qualifying candidates were rejected by contract/options/capital gates — no trade.")
            time.sleep(RESCAN_DELAY_SECONDS)
    finally:
        write_heartbeat("stopped")
        release_single_instance(lock)


if __name__ == "__main__":
    main()
