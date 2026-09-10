#!/usr/bin/env python3
import json, os, shutil, sqlite3, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
ROOT=Path('/home/ubuntu/PEREZ-AI-Trading-Bot')
CORE=ROOT/'data/memory/perez_ai_memory.db'; TIER1=ROOT/'data/memory/tier1_option_moves.sqlite3'

def q(db,sql,args=(),default=None):
    try:
        with sqlite3.connect(db,timeout=2) as c:
            c.row_factory=sqlite3.Row
            r=c.execute(sql,args).fetchall(); return [dict(x) for x in r]
    except Exception: return default if default is not None else []
def count(db,t):
    r=q(db,f'SELECT COUNT(*) n FROM {t}',default=[{'n':0}]); return r[0]['n'] if r else 0
def svc(n):
    try:return subprocess.check_output(['systemctl','is-active',n],text=True,timeout=2).strip()
    except Exception:return 'unknown'
def env(n):
    try:
        s=subprocess.check_output(['systemctl','show','perez-ai.service','-p','Environment','--value'],text=True,timeout=2)
        for x in s.split():
            if x.startswith(n+'='): return x.split('=',1)[1]
    except Exception:pass
    return 'unknown'
def state():
    s={'perez-ai.service':svc('perez-ai.service'),'perez-telegram-updater.service':svc('perez-telegram-updater.service'),'perez-tier1-option-observer.service':svc('perez-tier1-option-observer.service')}
    du=shutil.disk_usage(ROOT)
    return {'time':time.strftime('%Y-%m-%d %H:%M:%S IST'),
      'services':s,'mode':{'paper_mode':env('PAPER_MODE'),'orders_enabled':env('ORDERS_ENABLED'),'provider':env('MARKET_DATA_PROVIDER'),'upstox_enabled':env('UPSTOX_ENABLED')},
      'resources':{'disk_used_pct':round((du.used/du.total)*100,1),'disk_free_gb':round(du.free/1e9,2)},
      'counts':{'core':{'observations':count(CORE,'observations'),'outcomes':count(CORE,'outcomes'),'rejections':count(CORE,'rejections'),'lessons':count(CORE,'lessons')},'tier1':{'observations':count(TIER1,'observations'),'move_events':count(TIER1,'move_events'),'early_events':count(TIER1,'early_events')}},
      'latest':{'outcome':(q(CORE,'SELECT * FROM outcomes ORDER BY rowid DESC LIMIT 1') or [None])[0],'early_event':(q(TIER1,'SELECT * FROM early_events ORDER BY rowid DESC LIMIT 1') or [None])[0]},
      'recent':{'outcomes':q(CORE,'SELECT * FROM outcomes ORDER BY rowid DESC LIMIT 20'),'rejections':q(CORE,'SELECT * FROM rejections ORDER BY rowid DESC LIMIT 20'),'early_events':q(TIER1,'SELECT * FROM early_events ORDER BY rowid DESC LIMIT 30'),'move_events':q(TIER1,'SELECT * FROM move_events ORDER BY rowid DESC LIMIT 30)}}
HTML=(ROOT/'dashboard/index.html').read_text()
class H(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def do_GET(self):
        if self.path.split('?')[0] in ('/api','/api/state'):
            b=json.dumps(state(),default=str).encode(); self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b); return
        b=HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.send_header('Content-Length',str(len(b))); self.end_headers(); self.wfile.write(b)
ThreadingHTTPServer(('127.0.0.1',8787),H).serve_forever()
