(()=>{'use strict';
const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v==null?'—':'₹'+Number(v).toLocaleString('en-IN',{maximumFractionDigits:2});
const num=v=>v==null?'—':Number(v).toLocaleString('en-IN',{maximumFractionDigits:2});
const style=document.createElement('style');
style.textContent=`
#ai-sim-workspace{margin-top:10px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.35fr);gap:9px}
#ai-sim-workspace .sim-panel{background:var(--panel,#0d1728);border:1px solid var(--border,#24344e);padding:11px;min-width:0}
#ai-sim-workspace .sim-head{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-bottom:9px}
#ai-sim-workspace .sim-title{font-size:11px;font-weight:900;letter-spacing:.8px}
#ai-sim-workspace .sim-muted{color:var(--muted,#8fa1bc);font-size:10px}
#ai-sim-workspace .sim-tabs{display:flex;gap:5px;margin:8px 0}
#ai-sim-workspace .sim-tab{border:1px solid var(--border,#24344e);background:#101d30;color:#dce8fa;padding:7px 9px;font-size:10px;font-weight:800;cursor:pointer}
#ai-sim-workspace .sim-tab[aria-selected="true"]{border-color:var(--cyan,#72cfff);color:var(--cyan,#72cfff)}
#ai-sim-workspace .sim-card{border:1px solid #20324b;background:#091322;padding:10px;margin-top:8px}
#ai-sim-workspace .sim-card h4{margin:0 0 5px;font-size:11px}
#ai-sim-workspace .sim-meta{display:flex;gap:10px;flex-wrap:wrap;color:var(--muted,#8fa1bc);font-size:9px;margin:5px 0}
#ai-sim-workspace .sim-levels{display:flex;gap:6px;flex-wrap:wrap;margin:7px 0}
#ai-sim-workspace .sim-level{font-size:9px;padding:4px 6px;border:1px solid #2a3b55;color:#dce8fa}
#ai-sim-workspace .sim-chart{width:100%;height:170px;display:block;background:#07101d;border:1px solid #1b2b42;margin-top:8px}
#ai-sim-workspace .sim-empty{padding:14px;border:1px dashed #2a3b55;color:var(--muted,#8fa1bc);font-size:10px;text-align:center}
#ai-sim-workspace .sim-scroll{overflow:auto;max-height:230px}
#ai-sim-workspace table{width:100%;border-collapse:collapse;font-size:10px}
#ai-sim-workspace th,#ai-sim-workspace td{padding:6px;border-bottom:1px solid #1d2a40;text-align:left;white-space:nowrap}
#ai-sim-workspace th{color:var(--muted,#8fa1bc);font-size:9px}
@media(max-width:950px){#ai-sim-workspace{grid-template-columns:1fr}}
`;
document.head.appendChild(style);
const mount=document.getElementById('ai-sim-mount');
if(!mount||document.getElementById('ai-sim-workspace'))return;
const root=document.createElement('section');
root.id='ai-sim-workspace';
root.innerHTML=`
<div class="sim-panel">
 <div class="sim-head"><div><div class="sim-title">MARKET PULSE · UPSTOX LIVE</div><div class="sim-muted">Verified quotes only · read-only</div></div><span id="sim-market-status" class="pill">LOADING</span></div>
 <div id="sim-market-summary" class="sim-muted">Fetching market snapshot…</div>
 <div class="sim-scroll"><table><thead><tr><th>Symbol</th><th>LTP</th><th>Change</th><th>Volume</th></tr></thead><tbody id="sim-market-rows"><tr><td colspan="4">Loading…</td></tr></tbody></table></div>
 <div class="sim-head" style="margin-top:10px"><div class="sim-title">OPTION CHAIN SNAPSHOT</div><span class="sim-muted">Up to 20 volume-ranked rows</span></div>
 <div class="sim-scroll"><table><thead><tr><th>Underlying</th><th>Contract</th><th>Expiry</th><th>LTP</th><th>IV</th><th>Delta</th></tr></thead><tbody id="sim-option-rows"><tr><td colspan="6">Loading…</td></tr></tbody></table></div>
 <div id="sim-market-note" class="sim-muted" style="margin-top:8px">No demo quotes are displayed.</div>
</div>
<div class="sim-panel">
 <div class="sim-head"><div><div class="sim-title">AI OPTIONS SIMULATION</div><div class="sim-muted">Recorded evidence · counterfactual analysis · no orders</div></div><span id="sim-data-status" class="pill">LOADING</span></div>
 <div class="sim-tabs"><button class="sim-tab" data-view="rejected" aria-selected="true">REJECTED SETUPS</button><button class="sim-tab" data-view="paper" aria-selected="false">PAPER TRADES</button></div>
 <div id="sim-disclaimer" class="sim-muted">Loading recorded simulation evidence…</div>
 <div id="sim-list"><div class="sim-empty">Loading scenarios…</div></div>
</div>`;
mount.innerHTML='';mount.appendChild(root);
let payload={rejected_scenarios:[],paper_trades:[]},view='rejected';
function chart(item){
 const pts=(item.path||[]).filter(p=>Number.isFinite(Number(p.price)));
 const levels=[['Entry',item.entry,'#72cfff'],['Stop',item.stop_loss,'#ff7183'],['Target 1',item.target1,'#55e3a0'],['Target 2',item.target2,'#ffd166']];
 const vals=[...pts.map(p=>Number(p.price)),...levels.map(x=>x[1]).filter(v=>v!=null).map(Number)];
 if(!vals.length)return '<div class="sim-empty">No recorded option prices or trade levels. A price curve cannot be plotted without source data.</div>';
 let lo=Math.min(...vals),hi=Math.max(...vals);if(lo===hi){lo-=1;hi+=1}const pad=(hi-lo)*.12;lo-=pad;hi+=pad;
 const y=v=>145-(Number(v)-lo)/(hi-lo)*125;
 let svg='<svg class="sim-chart" viewBox="0 0 720 170" role="img" aria-label="Recorded option price path and trade levels"><line x1="45" y1="145" x2="700" y2="145" stroke="#30425e"/>';
 for(let i=0;i<5;i++){let yy=20+i*31;svg+='<line x1="45" y1="'+yy+'" x2="700" y2="'+yy+'" stroke="#1b2b42"/>'}
 levels.forEach(([label,v,color])=>{if(v==null)return;let yy=y(v);svg+='<line x1="45" y1="'+yy+'" x2="700" y2="'+yy+'" stroke="'+color+'" stroke-dasharray="6 4"/><text x="48" y="'+Math.max(12,yy-4)+'" fill="'+color+'" font-size="10">'+label+' '+esc(num(v))+'</text>'});
 if(pts.length){const horizon=p=>{const m=String(p.time||'').match(/^\+(\d+(?:\.\d+)?)m$/);return m?Number(m[1]):null};const hs=pts.map(horizon),maxH=Math.max(1,...hs.filter(v=>v!==null));const xpos=i=>hs[i]===null?45+i*(655/Math.max(1,pts.length-1)):45+(hs[i]/maxH)*655;let coords=pts.map((p,i)=>(xpos(i)+','+y(p.price))).join(' ');svg+='<polyline points="'+coords+'" fill="none" stroke="#72cfff" stroke-width="2.5"/>';pts.forEach((p,i)=>{let x=xpos(i);svg+='<circle cx="'+x+'" cy="'+y(p.price)+'" r="3.5" fill="#72cfff"><title>'+esc(p.time||p.event||'Recorded')+': '+esc(p.price)+'</title></circle>'})}
 svg+='</svg>';return svg;
}
function card(x){
 const title=x.contract||x.symbol||'Unidentified contract';
 const meta=[x.entry_time||x.time,x.status||x.data_quality,x.strategy].filter(Boolean).map(esc).join(' · ');
 const levels=[['ENTRY',x.entry],['STOP',x.stop_loss],['T1',x.target1],['T2',x.target2]].map(([k,v])=>'<span class="sim-level">'+k+': '+esc(num(v))+'</span>').join('');
 const pnl=x.pnl==null?(x.return_pct==null?'P&L unavailable':'Observed option return: '+Number(x.return_pct).toFixed(2)+'% (not rupee P&L)'):('Recorded P&L: '+money(x.pnl));
 const note=x.kind==='REJECTED'?(x.data_quality==='RECORDED_SHADOW_PATH'?'Recorded post-rejection option prices at 1/3/5/10/15 minutes. MFE '+(x.mfe_pct??'—')+'% · MAE '+(x.mae_pct??'—')+'%.':(x.missing_fields?.length?'Missing recorded fields: '+x.missing_fields.join(', '):'No post-rejection price path recorded.')):(x.data_quality==='RECORDED_PATH'?'Recorded lifecycle prices only.':'Entry/level evidence only; no continuous price path recorded.');
 return '<article class="sim-card"><h4>'+esc(title)+'</h4><div class="sim-meta">'+meta+'</div><div class="sim-levels">'+levels+'</div>'+chart(x)+'<div class="sim-meta"><b>'+esc(pnl)+'</b><span>'+esc(note)+'</span></div><div class="sim-meta">Source: '+esc(x.source||'Unavailable')+'</div></article>';
}
function render(){const rows=view==='paper'?payload.paper_trades:payload.rejected_scenarios;const list=document.getElementById('sim-list');list.innerHTML=rows?.length?rows.map(card).join(''):'<div class="sim-empty">'+(view==='paper'?'No paper-trade lifecycle entries found.':'No rejected setups were recorded in the rejection table.')+'</div>';document.querySelectorAll('#ai-sim-workspace .sim-tab').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.view===view)));}
document.querySelectorAll('#ai-sim-workspace .sim-tab').forEach(b=>b.addEventListener('click',()=>{view=b.dataset.view;render()}));
async function market(){const status=document.getElementById('sim-market-status');try{const r=await fetch('/api/market-intelligence',{cache:'no-store'});const d=await r.json();status.textContent=d.status||'UNKNOWN';const rows=d.symbols||[];document.getElementById('sim-market-summary').textContent=(d.provider||'Provider')+' · '+(d.as_of||'timestamp unavailable')+' · '+rows.length+' live quotes';document.getElementById('sim-market-rows').innerHTML=rows.length?rows.slice(0,30).map(x=>'<tr><td>'+esc(x.symbol)+'</td><td>'+esc(num(x.price))+'</td><td>'+esc(x.change_pct==null?'—':x.change_pct+'%')+'</td><td>'+esc(num(x.volume))+'</td></tr>').join(''):'<tr><td colspan="4">'+esc(d.reason||'No verified quotes available')+'</td></tr>';const opts=d.options||[];document.getElementById('sim-option-rows').innerHTML=opts.length?opts.slice(0,20).map(x=>'<tr><td>'+esc(x.symbol)+'</td><td>'+esc(x.strike)+' '+esc(x.side)+'</td><td>'+esc(x.expiry)+'</td><td>'+esc(num(x.ltp))+'</td><td>'+esc(num(x.iv))+'</td><td>'+esc(num(x.delta))+'</td></tr>').join(''):'<tr><td colspan="6">No verified option-chain rows available.</td></tr>';document.getElementById('sim-market-note').textContent=d.demo===false?'Source: '+(d.source||'Upstox API')+'. Snapshot timestamp: '+(d.as_of||'unavailable')+'.':'Market data source not verified; values suppressed.'}catch(e){status.textContent='UNAVAILABLE';document.getElementById('sim-market-summary').textContent='Market Pulse unavailable: '+e.message}}
async function simulations(){try{const r=await fetch('/api/ai-options-simulations',{cache:'no-store'});payload=await r.json();document.getElementById('sim-data-status').textContent=payload.status||'UNKNOWN';document.getElementById('sim-disclaimer').textContent=payload.disclaimer||'Recorded evidence only; no orders.';render()}catch(e){document.getElementById('sim-data-status').textContent='UNAVAILABLE';document.getElementById('sim-list').innerHTML='<div class="sim-empty">Simulation data unavailable: '+esc(e.message)+'</div>'}}
market();simulations();setInterval(market,15000);setInterval(simulations,15000);
})();