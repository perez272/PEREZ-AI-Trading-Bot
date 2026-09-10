"""Paper-only bridge worker for fresh Tier-1 early explosive events."""
from __future__ import annotations
import os,signal,time
from datetime import datetime
from src.dashboard_control import entries_allowed,append_audit
from src.capital_manager import get_available_capital
from src.market_scanner import get_client
from src.production_guard import write_heartbeat
from src.risk_manager import can_open_new_trade
from src.telegram_alert import send_entry_alert
from src.tier1_option_observer import get_tier1_option_observer
from src.surge_trade_bridge import create_surge_trade,_release_event
from src.live_trade_monitor import run_monitor
from src.trading_risk_manager import TradingRiskManager
from src.rejection_recorder import record_rejection
from src.upgrade_config import MAX_TRADES_PER_DAY,ENTRY_START,LAST_ENTRY
from src.session_clock import IST,is_weekday
from src.dashboard_telemetry import record_stage
RUNNING=True
POLL_SECONDS=max(1,int(os.getenv("SURGE_TRADE_BRIDGE_INTERVAL_SECONDS","2")))
RISK_MANAGER=TradingRiskManager()
def _stop(*_args):
    global RUNNING; RUNNING=False
def _in_entry_session():
    now=datetime.now(IST); return is_weekday(now) and ENTRY_START<=now.time()<=LAST_ENTRY
def _process_once():
    if not entries_allowed() or not _in_entry_session(): return False
    try:
        client=get_client(); capital=get_available_capital(client,paper_mode=True)
        allowed,_reason,_summary=can_open_new_trade(MAX_TRADES_PER_DAY,None,capital)
        if not allowed:return False
    except Exception as exc:
        write_heartbeat("surge_bridge_capital_error",error=str(exc)); return False
    observer=get_tier1_option_observer(); events=observer.get_pending_early_events(limit=5)
    if not events:return False
    events.sort(key=lambda e:float(e.get("score",0) or 0),reverse=True)
    for event in events:
        event_id=int(event["id"]); symbol=str(event.get("symbol") or ""); option_type=str(event.get("option_type") or "").upper(); event_key=str(event.get("event_key") or "")
        record_stage(event_key,"DETECTED","OK",symbol=symbol,option_type=option_type,score=event.get("score"),contract=event.get("contract"),detection_ts=event.get("detection_ts"),observed_ts=event.get("observed_ts"))
        record_stage(event_key,"BRIDGE_PICKUP","OK",symbol=symbol,option_type=option_type,score=event.get("score"),contract=event.get("contract"))
        try: trade,result=create_surge_trade(event,capital,RISK_MANAGER)
        except Exception as exc:
            record_stage(event_key,"GATE_EVALUATION","ERROR",symbol=symbol,option_type=option_type,score=event.get("score"),error=str(exc)); print(f"[SURGE BRIDGE] evaluation failed for {symbol} {option_type}: {exc}"); continue
        gate=result.get("gate",{}) if isinstance(result,dict) else {}
        record_stage(event_key,"GATE_EVALUATION","PASS" if trade is not None else "BLOCKED",symbol=symbol,option_type=option_type,score=gate.get("score",event.get("score")),contract=event.get("contract"),reason=result.get("reason") if isinstance(result,dict) else None,gate_reasons=gate.get("reasons",[]))
        if trade is None:
            reason_text=str(result.get("reason") or "SURGE_REJECTED")
            if reason_text!="EVENT_ALREADY_CLAIMED":
                print(f"[SURGE BRIDGE] {symbol} {option_type} rejected: {reason_text}")
                try: record_rejection(symbol=symbol,score=event.get("score"),reason=f"SURGE:{reason_text}",features={"event":event,"result":result})
                except Exception as exc: print(f"[SURGE BRIDGE] rejection persistence failed: {exc}")
            if result.get("terminal"): observer.mark_early_event_consumed(event_id)
            continue
        trade["strategy"]="SURGE_EARLY_EXPLOSIVE"; trade["surge_score"]=gate.get("score",0); trade["surge_reasons"]=gate.get("reasons",[])
        record_stage(event_key,"PAPER_ENTRY","PASS",symbol=symbol,option_type=option_type,score=trade.get("surge_score"),contract=trade.get("contract"),quantity=trade.get("quantity"))
        append_audit("SURGE_PAPER_TRADE_CREATED",f"{symbol} {option_type} score={trade['surge_score']}",event_key,"RECORDED")
        write_heartbeat("surge_paper_trade",symbol=symbol,contract=trade.get("contract"),strategy=trade["strategy"])
        print(f"[SURGE BRIDGE] PAPER TRADE {trade.get('contract')} score={trade['surge_score']} qty={trade.get('quantity')}")
        try: send_entry_alert(trade)
        except Exception as exc: print(f"[SURGE BRIDGE] Telegram entry alert failed: {exc}")
        record_stage(event_key,"MONITOR_START","OK",symbol=symbol,option_type=option_type,score=trade.get("surge_score"),contract=trade.get("contract"))
        try: result_monitor=run_monitor(trade)
        except Exception as exc:
            _release_event(event_id); record_stage(event_key,"MONITOR_END","ERROR",symbol=symbol,option_type=option_type,error=str(exc)); write_heartbeat("surge_monitor_error",symbol=symbol,error=str(exc)); print(f"[SURGE BRIDGE] monitor failed; event claim released for recovery: {exc}"); return True
        if result_monitor is None:
            _release_event(event_id); record_stage(event_key,"MONITOR_END","INTERRUPTED",symbol=symbol,option_type=option_type); return True
        record_stage(event_key,"MONITOR_END","OK",symbol=symbol,option_type=option_type,contract=trade.get("contract"),pnl=result_monitor.get("pnl",0),exit_reason=result_monitor.get("exit_reason","") )
        record_stage(event_key,"OUTCOME","OK",symbol=symbol,option_type=option_type,contract=trade.get("contract"),pnl=result_monitor.get("pnl",0),pnl_percent=result_monitor.get("pnl_percent",0),exit_reason=result_monitor.get("exit_reason","") )
        observer.mark_early_event_consumed(event_id)
        append_audit("SURGE_PAPER_TRADE_CLOSED",f"{symbol} {option_type} pnl={result_monitor.get('pnl',0)} reason={result_monitor.get('exit_reason','')}",event_key,"RECORDED")
        return True
    return False
def main():
    signal.signal(signal.SIGTERM,_stop); signal.signal(signal.SIGINT,_stop); print("PEREZ AI Surge Trade Bridge — PAPER ONLY")
    while RUNNING:
        try: did_work=_process_once()
        except Exception as exc: print(f"[SURGE BRIDGE] cycle failed safely: {exc}"); did_work=False
        time.sleep(1 if did_work else POLL_SECONDS)
if __name__=="__main__": main()
