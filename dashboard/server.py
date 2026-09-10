#!/usr/bin/env python3
import json
import os
import shutil
import sqlite3
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path('/home/ubuntu/PEREZ-AI-Trading-Bot')
CORE = ROOT / 'data/memory/perez_ai_memory.db'
TIER1 = ROOT / 'data/memory/tier1_option_moves.sqlite3'
INDEX = ROOT / 'dashboard/index.html'


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
        return subprocess.check_output(
            ['systemctl', 'is-active', name], text=True, timeout=2
        ).strip()
    except Exception:
        return 'unknown'


def env(name):
    try:
        raw = subprocess.check_output(
            ['systemctl', 'show', 'perez-ai.service', '-p', 'Environment', '--value'],
            text=True, timeout=2
        )
        for item in raw.split():
            if item.startswith(name + '='):
                return item.split('=', 1)[1]
    except Exception:
        pass
    return 'unknown'


def state():
    services = {
        'perez-ai.service': svc('perez-ai.service'),
        'perez-telegram-updater.service': svc('perez-telegram-updater.service'),
        'perez-tier1-option-observer.service': svc('perez-tier1-option-observer.service'),
    }
    disk = shutil.disk_usage(ROOT)

    early = q(TIER1, 'SELECT * FROM early_events ORDER BY rowid DESC LIMIT 30')
    moves = q(TIER1, 'SELECT * FROM move_events ORDER BY rowid DESC LIMIT 30')
    outcomes = q(CORE, 'SELECT * FROM outcomes ORDER BY rowid DESC LIMIT 20')
    rejections = q(CORE, 'SELECT * FROM rejections ORDER BY rowid DESC LIMIT 20')

    return {
        'time': time.strftime('%Y-%m-%d %H:%M:%S IST'),
        'services': services,
        'mode': {
            'paper_mode': env('PAPER_MODE'),
            'orders_enabled': env('ORDERS_ENABLED'),
            'provider': env('MARKET_DATA_PROVIDER'),
            'upstox_enabled': env('UPSTOX_ENABLED'),
        },
        'resources': {
            'disk_used_pct': round((disk.used / disk.total) * 100, 1),
            'disk_free_gb': round(disk.free / 1e9, 2),
        },
        'counts': {
            'core': {
                'observations': count(CORE, 'observations'),
                'outcomes': count(CORE, 'outcomes'),
                'rejections': count(CORE, 'rejections'),
                'lessons': count(CORE, 'lessons'),
            },
            'tier1': {
                'observations': count(TIER1, 'observations'),
                'move_events': count(TIER1, 'move_events'),
                'early_events': count(TIER1, 'early_events'),
            },
        },
        'latest': {
            'early_event': early[0] if early else None,
            'outcome': outcomes[0] if outcomes else None,
        },
        'recent': {
            'outcomes': outcomes,
            'rejections': rejections,
            'early_events': early,
            'move_events': moves,
        },
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

    def log_message(self, fmt, *args):
        return


if __name__ == '__main__':
    port = int(os.getenv('PEREZ_DASHBOARD_PORT', '8787'))
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'PEREZ dashboard listening on 127.0.0.1:{port}', flush=True)
    server.serve_forever()
