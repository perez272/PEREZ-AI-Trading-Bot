(()=>{'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'—').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const num=(v,d=2)=>Number.isFinite(Number(v))?Number(v).toFixed(d):'—';
function message(text){$('stocks').innerHTML='<tr><td colspan="7" class="empty">'+esc(text)+'</td></tr>';$('options').innerHTML='<tr><td colspan="8" class="empty">Live option-chain data unavailable</td></tr>';$('sectors').innerHTML='<p class="hint">'+esc(text)+'</p>';$('impacts').innerHTML='<div class="impact"><div><b>Underlying → options</b><p>Waiting for live quote and option-chain data.</p></div><span class="badge neutral">Unavailable</span></div>';}
function render(d){
 const badge=document.querySelector('.demo'); badge.textContent=d.status==='LIVE'?'LIVE · UPSTOX':'LIVE FEED · '+d.status;badge.className='pill '+(d.status==='LIVE'?'':'demo');
 $('updated').textContent='As of '+(d.as_of||'—')+' · Upstox';
 const metrics=document.querySelectorAll('.metrics .card .metric');
 if(d.status!=='LIVE'){message(d.reason||'No live market data.');metrics.forEach(x=>x.textContent='—');return;}
 const rows=d.symbols||[],opts=d.options||[];
 metrics[0].textContent=rows.length?rows.filter(x=>Number(x.change_pct)>0).length+'/'+rows.length:'—';
 metrics[1].textContent=rows.filter(x=>Math.abs(Number(x.change_pct)||0)>=1).length;
 metrics[2].textContent=rows.filter(x=>Number(x.relative_volume)>=2).length;
 metrics[3].textContent=opts.filter(x=>x.side==='CE').length;
 metrics[4].textContent=opts.filter(x=>x.side==='PE').length;
 $('stocks').innerHTML=rows.map(x=>{const ch=x.change_pct;return '<tr><td><span class="symbol">'+esc(x.symbol)+'</span><span class="small">'+esc(x.sector)+'</span></td><td>₹'+num(x.price)+'</td><td class="'+(ch>=0?'up':'down')+'">'+(ch==null?'—':(ch>0?'+':'')+num(ch)+'%')+'</td><td>'+num(x.relative_volume,2)+'×</td><td>'+num(x.buy_qty,0)+' / '+num(x.sell_qty,0)+'</td><td><span class="score mid">—</span></td><td class="amber">OBSERVE</td></tr>';}).join('')||'<tr><td colspan="7" class="empty">No live quotes returned</td></tr>';
 $('options').innerHTML=opts.map(x=>'<tr><td class="symbol">'+esc(x.symbol)+'</td><td>'+esc(x.strike)+' '+esc(x.side)+' · '+esc(x.expiry)+'</td><td>₹'+num(x.ltp)+'</td><td>—</td><td>'+num(x.volume,0)+'</td><td>'+num(x.iv)+'</td><td>OI/volume context only; not buyer/writer classification</td><td><span class="badge neutral">UNRANKED</span></td></tr>').join('')||'<tr><td colspan="8" class="empty">No live option chain returned for mapped underlyings</td></tr>';
 $('sectors').innerHTML=(d.sectors||[]).map(x=>'<div class="sector-row"><span>'+esc(x.sector)+'</span><div class="bar"><span style="width:'+Math.min(100,Math.abs(x.avg_change_pct)*15)+'%;background:'+(x.avg_change_pct>=0?'var(--green)':'var(--red)')+'"></span></div><b class="'+(x.avg_change_pct>=0?'up':'down')+'">'+num(x.avg_change_pct)+'%</b></div>').join('')||'<p class="hint">No sector coverage</p>';
 $('impacts').innerHTML='<div class="impact"><div><b>Underlying breadth</b><p>'+rows.length+' mapped symbols with live quotes</p></div><span class="badge neutral">Observed</span></div><div class="impact"><div><b>Options contracts</b><p>'+opts.length+' option legs returned; no directional buyer/writer inference</p></div><span class="badge neutral">Observed</span></div>';
}
async function refresh(){try{const r=await fetch('/api/market-intelligence',{cache:'no-store'});const d=await r.json();render(d);}catch(e){message('Dashboard API request failed: '+e.message);}}
refresh();setInterval(refresh,30000);
})();