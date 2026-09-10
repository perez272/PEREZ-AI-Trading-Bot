#!/usr/bin/env python3
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE = ROOT / 'data/memory/perez_ai_memory.db'
TIER1 = ROOT / 'data/memory/tier1_option_moves.sqlite3'
INDEX = ROOT / 'dashboard/index.html'

from src.dashboard_control import append_audit, get_state, recent_audit, set_controls


def q(db, sql, args=(), default=None):
    try:
        with sqlite3.connect(db, timeout=2) as c:
            c.row_factory = sqlite3.Row
            return [dict(r) for r in c.execute(sql, args).fetchall()]
    except Exception:
        return default if default is not None else []


def count(db, table):
    rows = q(db, f'SELECT COUNT(*) AS n FROM {table}', default=[{'n': 0}])
    return int(rows[0]['n']) if rows else 0


def svc(name):
    try:
        return subprocess.check_output(['systemctl', 'is-active', name], text=True, timeout=2).strip()
    except Exception:
        return 'unknown'


def env(name):
    try:
        raw = subprocess.check_output(['systemctl', 'show', 'perez-ai.service', '-p', 'Environment', '--value'], text=True, timeout=2)
        for item in raw.split():
            if item.startswith(name + '='):
                return item.split('=', 1)[1]
    except Exception:
        pass
    return 'unknown'


def pick(rows, fields):
    return [{k: r.get(k) for k in fields} for r in rows]


def state():
    services = {
        'perez-ai.service': svc('perez-ai.service'),
        'perez-telegram-updater.service': svc('perez-telegram-updater.service'),
        'perez-tier1-option-observer.service': svc('perez-tier1-option-observer.service'),
        'perez-dashboard.service': svc('perez-dashboard.service'),
    }
    disk = shutil.disk_usage(ROOT)
    early_raw = q(TIER1, 'SELECT * FROM early_events ORDER BY rowid DESC LIMIT 30')
    move_raw = q(TIER1, 'SELECT * FROM move_events ORDER BY rowid DESC LIMIT 30')
    out_raw = q(CORE, 'SELECT * FROM outcomes ORDER BY rowid DESC LIMIT 20')
    rej_raw = q(CORE, 'SELECT * FROM rejections ORDER BY rowid DESC LIMIT 20')
    early = pick(early_raw, ['id','symbol','option_type','instrument_key','expiry','strike','ltp','score','move_1m_pct','move_3m_pct','move_5m_pct','volume_ratio','spread_pct','observed_ts','consumed','event_key'])
    moves = pick(move_raw, ['id','symbol','option_type','strike','window_minutes','change_pct','end_ltp','observed_ts'])
    outcomes = pick(out_raw, ['id','ts','symbol','contract','signal','score','pnl','pnl_percent','exit_reason'])
    rejections = pick(rej_raw, ['id','ts','symbol','score','options_score','reason'])
    return {
        'time': time.strftime('%Y-%m-%d %H:%M:%S IST'),
        'services': services,
        'mode': {'paper_mode': env('PAPER_MODE'), 'orders_enabled': env('ORDERS_ENABLED'), 'provider': env('MARKET_DATA_PROVIDER'), 'upstox_enabled': env('UPSTOX_ENABLED')},
        'resources': {'disk_used_pct': round((disk.used / disk.total) * 100, 1), 'disk_free_gb': round(disk.free / 1e9, 2)},
        'controls': get_state(),
        'counts': {
            'core': {'observations': count(CORE,'observations'), 'outcomes': count(CORE,'outcomes'), 'rejections': count(CORE,'rejections'), 'lessons': count(CORE,'lessons')},
            'tier1': {'observations': count(TIER1,'observations'), 'move_events': count(TIER1,'move_events'), 'early_events': count(TIER1,'early_events')},
        },
        'latest': {'early_event': early[0] if early else None, 'outcome': outcomes[0] if outcomes else None},
        'recent': {'outcomes': outcomes, 'rejections': rejections, 'early_events': early, 'move_events': moves},
        'audit': recent_audit(40),
    }


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, content_type, body):
        data = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in ('/api', '/api/state'):
            self._send(200, 'application/json; charset=utf-8', json.dumps(state(), default=str))
            return
        if path == '/' or path == '/index.html':
            try:
                self._send(200, 'text/html; charset=utf-8', INDEX.read_text(encoding='utf-8'))
            except Exception as exc:
                self._send(500, 'text/plain; charset=utf-8', f'index error: {exc}')
            return
        self._send(404, 'text/plain; charset=utf-8', 'Not found')

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path != '/api/action':
            self._send(404, 'application/json', json.dumps({'ok': False, 'error': 'Not found'}))
            return
        try:
            length = min(int(self.headers.get('Content-Length', '0')), 12000)
            body = json.loads(self.rfile.read(length) or b'{}')
            action = str(body.get('action','')).strip().upper()
            reason = str(body.get('reason','')).strip()
            event_key = str(body.get('event_key','')).strip()
            if not action:
                raise ValueError('action is required')

            if action == 'STOP_NEW_TRADES':
                result = set_controls({'new_entries_enabled': False}, action, reason)
            elif action == 'RESUME_NEW_TRADES':
                result = set_controls({'new_entries_enabled': True, 'emergency_mode': False}, action, reason)
            elif action == 'PAUSE_OBSERVER':
                result = set_controls({'observer_enabled': False}, action, reason)
            elif action == 'RESUME_OBSERVER':
                result = set_controls({'observer_enabled': True}, action, reason)
            elif action == 'EMERGENCY_SAFE_MODE':
                result = set_controls({'new_entries_enabled': False, 'scanner_enabled': False, 'observer_enabled': False, 'emergency_mode': True}, action, reason)
            elif action == 'RESUME_SAFE_MODE':
                result = set_controls({'new_entries_enabled': True, 'scanner_enabled': True, 'observer_enabled': True, 'emergency_mode': False}, action, reason)
            elif action in {'BULLISH_CE','BEARISH_PE','WAIT','NO_TRADE','WATCH','TRAP','MOMENTUM_CONFIRMED','REVERSAL_LIKELY','EXPLOSIVE_MOVE','MOMENTUM_EXHAUSTED','PAPER_BUY_REQUEST','PAPER_REJECT','WAIT_CONFIRMATION','WATCH_ONLY','GOOD_SIGNAL','BAD_SIGNAL','FALSE_BREAKOUT','LATE_ENTRY','EXCELLENT_ENTRY','MISSED_OPPORTUNITY'}:
                if action == 'PAPER_BUY_REQUEST':
                    label = 'PAPER BUY REQUEST — WILL NOT BYPASS RISK OR OPTION GATES'
                else:
                    label = action
                append_audit(label, reason, event_key, 'RECORDED', {'event_key': event_key} if event_key else None)
                result = get_state()
            elif action == 'RUN_HEALTH_AUDIT':
                append_audit(action, reason, 'dashboard', 'RECORDED')
                result = get_state()
            else:
                raise ValueError('unsupported dashboard action')

            self._send(200, 'application/json; charset=utf-8', json.dumps({'ok': True, 'action': action, 'controls': result, 'audit': recent_audit(10)}, default=str))
        except Exception as exc:
            self._send(400, 'application/json; charset=utf-8', json.dumps({'ok': False, 'error': str(exc)}))

    def log_message(self, fmt, *args):
        return


if __name__ == '__main__':
    port = int(os.getenv('PEREZ_DASHBOARD_PORT', '8787'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'PEREZ dashboard listening on 127.0.0.1:{port}', flush=True)
    server.serve_forever()
