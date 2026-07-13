"""Flask WebUI - CarIoT ダッシュボード

エンドポイント:
  GET /              ダッシュボードHTML（認証不要）
  GET /api/status    センサーデータJSON（認証不要）
  GET /files         ファイル一覧（Basic認証必須）
  GET /files/dl/<p>  ファイルDL（Basic認証必須）
"""
import os
import threading
from datetime import datetime

from flask import Flask, jsonify, request, abort, send_from_directory, render_template_string
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

import bms as bms_module
import config
import history_store
import settings_store
import wifi_manager

app = Flask(__name__)
auth = HTTPBasicAuth()

_lock = threading.Lock()
_status: dict = {"mock": True, "charge_stopped": False}

_USERS = {config.WEBUI_USERNAME: generate_password_hash(config.WEBUI_PASSWORD)}


@auth.verify_password
def verify_password(username, password):
    if username in _USERS and check_password_hash(_USERS[username], password):
        return username


def set_status(data: dict):
    with _lock:
        _status.clear()
        _status.update(data)
        _status["updated_at"] = datetime.now().isoformat(timespec="seconds")


def get_status() -> dict:
    with _lock:
        return dict(_status)


# ---------------------------------------------------------------------------
# ダッシュボード
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>CarIoT</title>
<style>
:root{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#c9d1d9;--dm:#6e7681;
      --g:#3fb950;--y:#d29922;--r:#f85149;--bl:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,monospace;padding:12px;font-size:14px}
header{display:flex;align-items:center;justify-content:space-between;padding-bottom:10px;
       border-bottom:1px solid var(--bd);margin-bottom:12px}
h1{color:var(--bl);font-size:1.15rem;font-weight:600}
.badge{font-size:.7rem;padding:2px 8px;border-radius:10px;font-weight:700;margin-left:8px}
.live{background:#0d2618;color:var(--g);border:1px solid var(--g)}
.mock{background:#2d1f07;color:var(--y);border:1px solid var(--y)}
nav a{color:var(--bl);text-decoration:none;font-size:.85rem;margin-left:12px}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.card{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:12px}
.ct{color:var(--dm);font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px}
.row{display:flex;justify-content:space-between;align-items:baseline;padding:2px 0}
.lbl{color:var(--dm);font-size:.8rem}
.val{font-weight:600;font-variant-numeric:tabular-nums}
.g{color:var(--g)}.y{color:var(--y)}.r{color:var(--r)}
.soc-t{height:6px;background:var(--bd);border-radius:3px;margin-top:6px}
.soc-f{height:100%;border-radius:3px;transition:width .5s,background .5s}
.alert{border-radius:8px;padding:10px;text-align:center;font-size:.88rem;margin-bottom:10px}
.alert-r{background:#1f0d0d;border:1px solid var(--r);color:var(--r)}
.alert-y{background:#1f1a0d;border:1px solid var(--y);color:var(--y)}
footer{color:var(--dm);font-size:.72rem;text-align:center;
       padding-top:8px;border-top:1px solid var(--bd);margin-top:8px}
.stab{background:var(--bg);border:1px solid var(--bd);color:var(--dm);
      border-radius:4px;padding:3px 10px;font-size:.78rem;cursor:pointer}
.stab.on{background:#1f3555;color:var(--bl);border-color:var(--bl)}
.gnav{background:var(--bg);border:1px solid var(--bd);color:var(--dm);
      border-radius:4px;padding:4px 10px;font-size:.78rem;cursor:pointer}
.gnav:hover{border-color:var(--bl);color:var(--bl)}
.gnav:disabled{opacity:.35;cursor:default}
</style>
</head>
<body>
<header>
  <div><h1>CarIoT<span id="bdg" class="badge live">LIVE</span></h1></div>
  <nav><a href="/files">ファイル</a>&nbsp;&nbsp;<a href="/wifi">WiFi</a>&nbsp;&nbsp;<a href="/settings">設定</a></nav>
</header>
<div id="alert" style="display:none"></div>
<div class="g2">
  <div class="card">
    <div class="ct">&#9728; PV</div>
    <div class="row"><span class="lbl">電圧</span><span class="val g" id="pv-v">--</span></div>
    <div class="row"><span class="lbl">電流</span><span class="val g" id="pv-a">--</span></div>
    <div class="row"><span class="lbl">電力</span><span class="val g" id="pv-w">--</span></div>
  </div>
  <div class="card">
    <div class="ct">&#9889; 負荷</div>
    <div class="row"><span class="lbl">電圧</span><span class="val" id="ld-v">--</span></div>
    <div class="row"><span class="lbl">電流</span><span class="val" id="ld-a">--</span></div>
    <div class="row"><span class="lbl">電力</span><span class="val" id="ld-w">--</span></div>
  </div>
</div>
<div class="card" style="margin-bottom:10px">
  <div class="ct">&#128267; バッテリー&nbsp;<span id="chg" style="font-size:.75rem;text-transform:none;letter-spacing:0;color:var(--dm)"></span></div>
  <div class="g2" style="gap:8px;margin:0">
    <div>
      <div class="row"><span class="lbl">電圧</span><span class="val" id="bt-v">--</span></div>
      <div class="row"><span class="lbl">電流</span><span class="val" id="bt-a">--</span></div>
      <div class="row"><span class="lbl">電力</span><span class="val" id="bt-w">--</span></div>
    </div>
    <div>
      <div class="row"><span class="lbl">温度</span><span class="val" id="bt-t">--</span></div>
      <div class="row"><span class="lbl">SOC</span><span class="val" id="bt-s">--</span></div>
      <div class="soc-t"><div class="soc-f" id="soc-f"></div></div>
    </div>
  </div>
</div>
<div class="card" style="margin-bottom:10px">
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div class="ct" style="margin-bottom:0">&#128267; BMS監視 <span id="bms-ctrl-st"></span></div>
    <button class="gnav" id="bms-ctrl-btn" onclick="toggleBmsCtrl()">...</button>
  </div>
  <div id="bms-ctrl-warn" style="display:none;font-size:.75rem;color:var(--y);margin-top:6px">
    &#9888; OFF中はRaspiがBMSから切断されスマホ等から直接接続できますが、過電圧保護の監視も停止します
  </div>
</div>
<div class="g2" id="bms-wrap" style="margin-bottom:10px;display:none">
  <div class="card">
    <div class="ct">&#128267; BMS1</div>
    <div id="bms1-body"></div>
  </div>
  <div class="card">
    <div class="ct">&#128267; BMS2</div>
    <div id="bms2-body"></div>
  </div>
</div>
<footer id="ts">取得中...</footer>
<script>
const $=id=>document.getElementById(id);
const f=(v,d,u)=>v!=null?v.toFixed(d)+' '+u:'--';
function renderBMS(el,b){
  if(!b){el.innerHTML='<div class="row"><span class="lbl r">未取得</span></div>';return;}
  const on=b.online;
  const hasData=b.cells&&b.cells.length>0;
  const stale=!on&&hasData;
  const dot='<span class="'+(on?'g':'r')+'">&#9679;</span> ';
  let status=on?'ONLINE':'OFFLINE';
  if(!on&&b.last_seen){
    const mins=Math.round((Date.now()-new Date(b.last_seen).getTime())/60000);
    status+=' <span style="font-size:.72rem;color:var(--dm)">('+mins+'分前)</span>';
  }else if(!on&&!hasData){
    status+=' <span style="font-size:.72rem;color:var(--dm)">(取得中...)</span>';
  }
  const fade=stale?'opacity:0.6;':'';
  const pv=b.pack_v!=null?b.pack_v.toFixed(2)+' V':'--';
  const pa=b.pack_a!=null?(b.pack_a>=0?'+':'')+b.pack_a.toFixed(2)+' A':'--';
  const pw=b.pack_w!=null?(b.pack_w>=0?'+':'')+b.pack_w.toFixed(1)+' W':'--';
  const soc=b.soc!=null?b.soc+' %':'--';
  const ah=(b.remain_ah!=null&&b.full_ah!=null)
    ?b.remain_ah.toFixed(1)+' / '+b.full_ah.toFixed(1)+' Ah':'--';
  const tmp=b.temps&&b.temps.length?b.temps[0].toFixed(1)+' °C':'--';
  const delta=b.cell_delta!=null?(b.cell_delta*1000).toFixed(0)+' mV':'--';
  const dcls=b.cell_delta>0.05?'r':b.cell_delta>0.02?'y':'g';
  const cells=(b.cells||[]).map((v,i)=>{
    const c=v<3.0?'r':v<3.2?'y':'g';
    return '<div class="row" style="'+fade+'"><span class="lbl">C'+(i+1)+'</span><span class="val '+c+'">'+v.toFixed(3)+' V</span></div>';
  }).join('');
  el.innerHTML=dot+status
    +'<div class="row" style="'+fade+'"><span class="lbl">電圧</span><span class="val">'+pv+'</span></div>'
    +'<div class="row"><span class="lbl">SOC</span><span class="val">'+soc+'</span></div>'
    +'<div class="row" style="'+fade+'"><span class="lbl">残容量</span><span class="val">'+ah+'</span></div>'
    +'<div class="row"><span class="lbl">電流</span><span class="val">'+pa+'</span></div>'
    +'<div class="row"><span class="lbl">電力</span><span class="val">'+pw+'</span></div>'
    +'<div class="row"><span class="lbl">温度</span><span class="val">'+tmp+'</span></div>'
    +cells
    +'<div class="row" style="'+fade+'"><span class="lbl">バランス差</span><span class="val '+dcls+'">'+delta+'</span></div>';
}
let bmsEnabled=true;
function renderBmsCtrl(){
  const btn=$('bms-ctrl-btn'),st=$('bms-ctrl-st'),warn=$('bms-ctrl-warn');
  if(bmsEnabled){
    st.textContent='';st.className='';
    btn.textContent='ON（タップでOFF）';btn.className='gnav';
    warn.style.display='none';
  }else{
    st.textContent='OFF';st.className='r';
    btn.textContent='OFF（タップでON）';btn.className='gnav';btn.style.color='var(--r)';btn.style.borderColor='var(--r)';
    warn.style.display='block';
  }
}
async function refreshBmsCtrl(){
  try{
    const d=await fetch('/api/bms/ctrl').then(r=>r.json());
    bmsEnabled=d.enabled;
    renderBmsCtrl();
  }catch(e){}
}
async function toggleBmsCtrl(){
  const btn=$('bms-ctrl-btn');
  btn.disabled=true;
  try{
    const r=await fetch('/api/bms/ctrl',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({enabled:!bmsEnabled}),
    });
    if(r.ok){
      const d=await r.json();
      bmsEnabled=d.enabled;
      renderBmsCtrl();
    }else{
      alert('切替に失敗しました ('+r.status+')');
    }
  }catch(e){
    alert('通信エラー: '+e);
  }
  btn.disabled=false;
}
renderBmsCtrl();refreshBmsCtrl();

async function refresh(){
  try{
    const d=await fetch('/api/status').then(r=>r.json());
    $('bdg').textContent=d.mock?'MOCK':'LIVE';
    $('bdg').className='badge '+(d.mock?'mock':'live');
    $('pv-v').textContent=f(d.pv_voltage,2,'V');
    $('pv-a').textContent=f(d.pv_current,2,'A');
    $('pv-w').textContent=f(d.pv_power,1,'W');
    $('ld-v').textContent=f(d.load_voltage,2,'V');
    $('ld-a').textContent=f(d.load_current,2,'A');
    $('ld-w').textContent=f(d.load_power,1,'W');
    $('bt-v').textContent=f(d.bat_voltage,2,'V');
    $('bt-a').textContent=f(d.bat_current,2,'A');
    $('bt-w').textContent=f(d.bat_power,1,'W');
    $('chg').textContent=d.charge_status||'';
    const t=d.bat_temp;
    const te=$('bt-t');
    te.textContent=t!=null?t.toFixed(1)+' °C':'--';
    te.className='val '+(t>45?'r':t>40?'y':'g');
    const s=d.bat_soc;
    $('bt-s').textContent=s!=null?s+' %':'--';
    const bar=$('soc-f');
    bar.style.width=(s||0)+'%';
    bar.style.background=s>50?'#3fb950':s>20?'#d29922':'#f85149';
    const al=$('alert');
    if(d.charge_stopped){
      al.className='alert alert-r';al.style.display='block';
      al.textContent='⛔ 高温のため充電停止中 — '+(t?t.toFixed(1):'--')+' °C (45°C超)';
    }else if(t>40){
      al.className='alert alert-y';al.style.display='block';
      al.textContent='⚠ バッテリー温度警告: '+t.toFixed(1)+' °C';
    }else{al.style.display='none';}
    if(d.bms&&Object.keys(d.bms).length){
      $('bms-wrap').style.display='grid';
      renderBMS($('bms1-body'),d.bms.bms1||null);
      renderBMS($('bms2-body'),d.bms.bms2||null);
    }
    const age=d.updated_at?Math.round((Date.now()-new Date(d.updated_at).getTime())/1000):null;
    $('ts').textContent='最終更新: '+new Date().toLocaleTimeString('ja-JP')+(age!=null?' ('+age+'秒前)':'');
  }catch(e){$('ts').textContent='通信エラー '+new Date().toLocaleTimeString('ja-JP');}
}
refresh();setInterval(refresh,5000);
</script>

<div class="card" style="margin-top:10px" id="graph-card">
  <div class="ct">&#9889; 電力履歴</div>
  <div style="display:flex;gap:4px;margin-bottom:10px" id="stabs">
    <button class="stab" data-s="minute">分</button>
    <button class="stab" data-s="hour">時</button>
    <button class="stab on" data-s="day">日</button>
    <button class="stab" data-s="week">週</button>
    <button class="stab" data-s="month">月</button>
  </div>
  <div style="display:flex;flex-wrap:wrap;gap:10px;font-size:.7rem;color:var(--dm);margin-bottom:8px">
    <span><span style="display:inline-block;width:8px;height:8px;background:#3fb950;margin-right:3px;border-radius:1px"></span>PV</span>
    <span><span style="display:inline-block;width:8px;height:8px;background:#58a6ff;margin-right:3px;border-radius:1px"></span>充電</span>
    <span><span style="display:inline-block;width:8px;height:8px;background:#d29922;margin-right:3px;border-radius:1px"></span>Tracer負荷</span>
    <span><span style="display:inline-block;width:8px;height:8px;background:#f0883e;margin-right:3px;border-radius:1px"></span>BMS負荷</span>
    <span><span style="display:inline-block;width:14px;height:2px;background:#7F77DD;margin-right:3px;vertical-align:middle"></span>電圧(右V)</span>
    <span><span style="display:inline-block;width:14px;border-top:2px dashed #f85149;margin-right:3px;vertical-align:middle"></span>温度(右℃)</span>
  </div>
  <div style="position:relative;width:100%;height:220px">
    <canvas id="histChart" role="img" aria-label="PV・充電・消費の棒グラフとバッテリー電圧・温度のトレンド"></canvas>
    <div id="gcmsg" style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;color:var(--dm);font-size:.85rem">読み込み中...</div>
  </div>
  <div style="display:flex;align-items:center;justify-content:space-between;margin-top:8px">
    <button class="gnav" id="g-older">&#8592; 過去へ</button>
    <span id="g-range" style="font-size:.7rem;color:var(--dm);text-align:center;flex:1;padding:0 6px"></span>
    <button class="gnav" id="g-newer">次へ &#8594;</button>
  </div>
</div>

<script src="/static/chart.umd.min.js"></script>
<script>
(function(){
  var gScale='day', gBefore=null, gChart=null, gPoints=[], gStack=[];
  var LIMITS={minute:120,hour:72,day:60,week:52,month:24};
  var UNITS={minute:'W',hour:'Wh',day:'Wh',week:'Wh',month:'Wh'};
  var $=function(id){return document.getElementById(id);};

  function fmtTs(ts,s){
    var d=new Date(ts*1000),h=d.getHours(),m=d.getMinutes(),mo=d.getMonth()+1,dy=d.getDate();
    if(s==='minute')return ('0'+h).slice(-2)+':'+('0'+m).slice(-2);
    if(s==='hour')return mo+'/'+dy+' '+('0'+h).slice(-2)+'h';
    if(s==='day')return mo+'/'+dy;
    if(s==='week')return mo+'/'+dy+'~';
    return d.getFullYear()+'/'+(d.getMonth()+1);
  }
  function fmtRange(pts){
    if(!pts||!pts.length)return '';
    var a=new Date(pts[0].t*1000),b=new Date(pts[pts.length-1].t*1000);
    var fmt=function(d){return (d.getMonth()+1)+'/'+d.getDate()+' '+('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2);};
    return fmt(a)+' 〜 '+fmt(b);
  }

  function renderChart(data){
    var msg=$('gcmsg');
    if(!window.Chart){msg.textContent='Chart.jsが未設置 (setup_static.sh を実行してください)';return;}
    if(!data||!data.points||!data.points.length){msg.textContent='データなし';msg.style.display='flex';return;}
    msg.style.display='none';
    gPoints=data.points;
    var unit=UNITS[gScale];
    var labels=data.points.map(function(p){return fmtTs(p.t,gScale);});
    $('g-range').textContent=fmtRange(data.points);
    $('g-older').disabled=!data.has_more;
    $('g-newer').disabled=gStack.length===0;

    var ds=[
      {type:'line',label:'電圧',data:data.points.map(function(p){return p.bat_v;}),yAxisID:'y1',
       borderColor:'#7F77DD',borderWidth:2,pointRadius:0,tension:0.3,order:0},
      {type:'line',label:'温度',data:data.points.map(function(p){return p.bat_temp;}),yAxisID:'y2',
       borderColor:'#f85149',borderWidth:2,borderDash:[4,3],pointRadius:0,tension:0.3,order:0},
      {type:'bar',label:'PV',data:data.points.map(function(p){return p.pv;}),stack:'gen',
       backgroundColor:'#3fb950',order:1},
      {type:'bar',label:'充電',data:data.points.map(function(p){return p.chg;}),stack:'use',
       backgroundColor:'#58a6ff',order:1},
      {type:'bar',label:'Tracer負荷',data:data.points.map(function(p){return p.load_tr;}),stack:'use',
       backgroundColor:'#d29922',order:1},
      {type:'bar',label:'BMS負荷',data:data.points.map(function(p){return p.load_bms;}),stack:'use',
       backgroundColor:'#f0883e',order:1}
    ];
    if(gChart){gChart.destroy();gChart=null;}
    var canvas=$('histChart');
    gChart=new window.Chart(canvas,{
      data:{labels:labels,datasets:ds},
      options:{
        responsive:true,maintainAspectRatio:false,
        interaction:{mode:'index',intersect:false},
        plugins:{
          legend:{display:false},
          tooltip:{callbacks:{label:function(i){
            var u=(i.dataset.label==='電圧')?'V':(i.dataset.label==='温度')?'℃':unit;
            var v=i.parsed.y;
            return i.dataset.label+': '+(v==null?'--':v.toLocaleString())+' '+u;
          }}}
        },
        scales:{
          x:{stacked:true,grid:{display:false},
             ticks:{color:'#6e7681',font:{size:10},maxRotation:45,autoSkip:true,maxTicksLimit:12}},
          y:{stacked:true,position:'left',grid:{color:'rgba(255,255,255,0.08)'},
             ticks:{color:'#6e7681',font:{size:10}},
             title:{display:true,text:unit,color:'#6e7681',font:{size:10}}},
          y1:{position:'right',min:12.0,max:14.8,grid:{drawOnChartArea:false},
              ticks:{color:'#7F77DD',font:{size:10},callback:function(v){return v.toFixed(1)+'V';}}},
          y2:{position:'right',min:0,max:60,grid:{drawOnChartArea:false},
              ticks:{color:'#f85149',font:{size:10},callback:function(v){return v+'℃';}}}
        }
      }
    });
    var tx0=0;
    canvas.addEventListener('touchstart',function(e){tx0=e.touches[0].clientX;},{passive:true});
    canvas.addEventListener('touchend',function(e){
      var dx=e.changedTouches[0].clientX-tx0;
      if(dx<-40)doOlder();
      if(dx>40)doNewer();
    },{passive:true});
  }

  async function loadGraph(before){
    var msg=$('gcmsg');
    msg.style.display='flex';msg.textContent='読み込み中...';
    try{
      var url='/api/history?scale='+gScale+(before!=null?'&before='+before:'');
      var data=await fetch(url).then(function(r){return r.json();});
      renderChart(data);
    }catch(e){
      msg.style.display='flex';msg.textContent='取得エラー: '+e.message;
    }
  }

  function doOlder(){
    if(gPoints.length>0){gStack.push(gBefore);loadGraph(gPoints[0].t);}
  }
  function doNewer(){
    if(gStack.length>0){var b=gStack.pop();loadGraph(b);}
  }

  document.querySelectorAll('.stab').forEach(function(b){
    b.addEventListener('click',function(){
      gScale=b.dataset.s;gBefore=null;gStack=[];
      document.querySelectorAll('.stab').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on');
      loadGraph(null);
    });
  });
  $('g-older').addEventListener('click',doOlder);
  $('g-newer').addEventListener('click',doNewer);

  loadGraph(null);
})();
</script>
</body>
</html>"""

_FILES_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CarIoT Files</title>
<style>
:root{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#c9d1d9;--dm:#6e7681;--bl:#58a6ff;--y:#d29922}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,monospace;padding:12px;font-size:14px}
header{display:flex;justify-content:space-between;align-items:center;padding-bottom:10px;
       border-bottom:1px solid var(--bd);margin-bottom:12px}
h1{color:var(--bl);font-size:1.1rem}
nav a{color:var(--bl);text-decoration:none;font-size:.85rem}
a{color:var(--bl);text-decoration:none}
.path{font-size:.8rem;color:var(--dm);background:var(--sf);border:1px solid var(--bd);
      border-radius:6px;padding:8px;margin-bottom:10px;word-break:break-all}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{background:var(--sf);color:var(--dm);padding:8px;text-align:left;font-weight:normal;border-bottom:1px solid var(--bd)}
td{padding:8px;border-bottom:1px solid var(--bd)}
tr:hover td{background:var(--sf)}
.dir{color:var(--y)}
.sz{text-align:right;color:var(--dm);white-space:nowrap}
.mt{color:var(--dm);font-size:.78rem;white-space:nowrap}
.err{color:#f85149;padding:20px;text-align:center}
</style>
</head>
<body>
<header>
  <h1>&#128193; ファイル</h1>
  <nav><a href="/">ダッシュボード</a>&nbsp;&nbsp;<a href="/wifi">WiFi</a>&nbsp;&nbsp;<a href="/settings">設定</a></nav>
</header>
<div class="path">{{ rel_dir or '/' }}</div>
{% if error %}
<div class="err">{{ error }}</div>
{% else %}
<table>
<thead><tr><th>名前</th><th>更新日時</th><th class="sz">サイズ</th></tr></thead>
<tbody>
{% if rel_dir %}
<tr><td colspan="3"><a href="{{ parent_url }}">&#8593; 上へ (..)</a></td></tr>
{% endif %}
{% for it in items %}
<tr>
  <td>
    {% if it.is_dir %}<a class="dir" href="/files?dir={{ it.rel_path }}">&#128193; {{ it.name }}/</a>
    {% else %}<a href="/files/dl/{{ it.rel_path }}">{{ it.name }}</a>{% endif %}
  </td>
  <td class="mt">{{ it.mtime }}</td>
  <td class="sz">{{ it.size_str }}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}
</body>
</html>"""


_SETTINGS_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>CarIoT 設定</title>
<style>
:root{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#c9d1d9;--dm:#6e7681;
      --g:#3fb950;--y:#d29922;--r:#f85149;--bl:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,monospace;padding:12px;font-size:14px}
header{display:flex;align-items:center;justify-content:space-between;padding-bottom:10px;
       border-bottom:1px solid var(--bd);margin-bottom:14px}
h1{color:var(--bl);font-size:1.1rem}
nav a{color:var(--bl);text-decoration:none;font-size:.85rem;margin-left:12px}
.card{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:12px}
.card h2{font-size:.95rem;margin-bottom:12px;border-bottom:1px solid var(--bd);padding-bottom:8px}
.field{margin-bottom:14px}
.field label{display:block;color:var(--dm);font-size:.75rem;margin-bottom:5px;
              text-transform:uppercase;letter-spacing:.06em}
.ir{display:flex;align-items:center;gap:8px}
.ir input{background:var(--bg);border:1px solid var(--bd);color:var(--tx);border-radius:6px;
           padding:8px 10px;font-size:.95rem;width:100px;font-family:monospace}
.ir input:focus{outline:none;border-color:var(--bl)}
.unit{color:var(--dm);font-size:.85rem}
.hint{color:var(--dm);font-size:.73rem;margin-top:4px;line-height:1.4}
.calc{font-size:.82rem;padding:8px 10px;border-radius:6px;background:var(--bg);
       margin-top:10px;border:1px solid var(--bd)}
.etag{font-size:.68rem;background:#2d1f07;color:var(--y);border:1px solid var(--y);
       border-radius:10px;padding:2px 7px;font-weight:700;margin-left:6px;vertical-align:middle}
.wnote{font-size:.76rem;color:var(--dm);margin-bottom:12px;padding:8px;
        border:1px solid var(--bd);border-radius:6px;line-height:1.5}
.btn{width:100%;background:#1f6feb;color:white;border:none;border-radius:8px;
      padding:12px;font-size:1rem;cursor:pointer;font-weight:600;margin-top:4px}
.btn:hover{background:#388bfd}
#msg{border-radius:8px;padding:10px;text-align:center;font-size:.88rem;
      margin-bottom:8px;display:none}
.ok{background:#0d2618;border:1px solid var(--g);color:var(--g)}
.err{background:#1f0d0d;border:1px solid var(--r);color:var(--r)}
</style>
</head>
<body>
<header>
  <h1>&#9881; 設定</h1>
  <nav><a href="/">ダッシュボード</a><a href="/files">ファイル</a><a href="/wifi">WiFi</a></nav>
</header>

<div class="card">
  <h2>&#127777; 温度制御</h2>
  <div class="field">
    <label>充電停止温度</label>
    <div class="ir">
      <input type="number" id="temp_high" step="0.5" min="35" max="60">
      <span class="unit">°C</span>
    </div>
    <div class="hint">この温度を超えると充電を停止します（LiFePO4推奨: 45°C）</div>
  </div>
  <div class="field">
    <label>充電再開温度</label>
    <div class="ir">
      <input type="number" id="temp_low" step="0.5" min="20" max="58">
      <span class="unit">°C</span>
    </div>
    <div class="hint">この温度を下回ると充電を再開します（ヒステリシス制御）</div>
  </div>
  <div class="calc" id="hyst">ヒステリシス: 読み込み中...</div>
</div>

<div class="card">
  <h2>&#9889; Boost / Float 電圧制御 <span class="etag">充電制御時にEEPROM書き込み</span></h2>
  <div class="wnote">ここで保存しても即座にEEPROMへは書き込まれません。<br>温度閾値を超えて充電停止・再開が実行されたとき初めてTracerのEEPROMに書き込まれます。</div>
  <div class="field">
    <label>通常充電 Boost 電圧</label>
    <div class="ir">
      <input type="number" id="boost_normal" step="0.01" min="13.0" max="15.5">
      <span class="unit">V</span>
    </div>
    <div class="hint">LiFePO4 12Vシステム推奨: 14.00〜14.40V</div>
  </div>
  <div class="field">
    <label>Float 電圧</label>
    <div class="ir">
      <input type="number" id="float_voltage" step="0.01" min="10.0" max="15.5">
      <span class="unit">V</span>
    </div>
    <div class="hint">LiFePO4は Float 不要。静止電圧付近（13.30V）に設定すると満充電後に自然停止します</div>
  </div>
  <div class="field">
    <label>充電停止電圧（Boost を強制的に下げる値）</label>
    <div class="ir">
      <input type="number" id="boost_stop" step="0.01" min="10.0" max="13.9">
      <span class="unit">V</span>
    </div>
    <div class="hint">バッテリー静止電圧より低く設定（推奨: 12.00V）</div>
  </div>
</div>

<div class="card">
  <h2>&#128267; BMS セル過電圧保護</h2>
  <div class="field">
    <label>BMS負荷 無視閾値</label>
    <div class="ir">
      <input type="number" id="bms_load_thr" step="1" min="0" max="200">
      <span class="unit">W</span>
    </div>
    <div class="hint">この値未満のBMS負荷は二重計上とみなしチャートに表示しません（インバータ等の大出力は表示）</div>
  </div>
  <div class="field">
    <label>過電圧検出閾値（停止）</label>
    <div class="ir">
      <input type="number" id="bms_ov_stop" step="0.01">
      <span class="unit">V/cell</span>
    </div>
    <div class="hint">この値以上でTracerの充電を停止します（LiFePO4推奨: 3.65V）</div>
  </div>
  <div class="field">
    <label>過電圧復帰閾値</label>
    <div class="ir">
      <input type="number" id="bms_ov_resume" step="0.01">
      <span class="unit">V/cell</span>
    </div>
    <div class="hint">この値を下回ると充電を再開します（ヒステリシス: 推奨 0.05V以上）</div>
  </div>
  <div class="calc" id="ov_hyst">ヒステリシス: 読み込み中...</div>
</div>

<div id="msg"></div>
<button class="btn" id="save">保存する</button>

<script>
const $=id=>document.getElementById(id);
function upd(){
  const th=parseFloat($('temp_high').value),tl=parseFloat($('temp_low').value);
  const el=$('hyst');
  if(!isNaN(th)&&!isNaN(tl)){
    const h=(th-tl).toFixed(1);
    el.textContent='ヒステリシス: '+h+'°C　（再開: '+tl+'°C ←→ 停止: '+th+'°C）';
    el.style.color=h>=2?'var(--g)':'var(--r)';
  }
}
function updOv(){
  const st=parseFloat($('bms_ov_stop').value),re=parseFloat($('bms_ov_resume').value);
  const el=$('ov_hyst');
  if(!isNaN(st)&&!isNaN(re)){
    const h=(st-re).toFixed(3);
    el.textContent='ヒステリシス: '+h+'V　（復帰: '+re+'V ←→ 停止: '+st+'V）';
    el.style.color=parseFloat(h)>=0.03?'var(--g)':'var(--r)';
  }
}
$('temp_high').addEventListener('input',upd);
$('temp_low').addEventListener('input',upd);
$('bms_ov_stop').addEventListener('input',updOv);
$('bms_ov_resume').addEventListener('input',updOv);

async function load(){
  try{
    const d=await fetch('/api/settings').then(r=>r.json());
    $('temp_high').value=d.temp_high;
    $('temp_low').value=d.temp_low;
    $('boost_normal').value=d.boost_voltage_normal_v;
    $('float_voltage').value=d.float_voltage_v;
    $('boost_stop').value=d.boost_voltage_stop_v;
    $('bms_load_thr').value=d.bms_load_threshold_w;
    $('bms_ov_stop').value=d.bms_ov_stop_v;
    $('bms_ov_resume').value=d.bms_ov_resume_v;
    upd();updOv();
  }catch(e){$('hyst').textContent='読み込みエラー: '+e.message;}
}

$('save').addEventListener('click',async()=>{
  const body={
    temp_high:parseFloat($('temp_high').value),
    temp_low:parseFloat($('temp_low').value),
    boost_voltage_normal_v:parseFloat($('boost_normal').value),
    float_voltage_v:parseFloat($('float_voltage').value),
    boost_voltage_stop_v:parseFloat($('boost_stop').value),
    bms_load_threshold_w:parseFloat($('bms_load_thr').value),
    bms_ov_stop_v:parseFloat($('bms_ov_stop').value),
    bms_ov_resume_v:parseFloat($('bms_ov_resume').value),
  };
  const msg=$('msg');
  msg.style.display='block';
  try{
    const r=await fetch('/api/settings',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(body),
    });
    const d=await r.json();
    if(d.ok){
      msg.className='ok';
      msg.textContent='✅ 保存しました（次のポーリング10秒以内に反映）';
    }else{
      msg.className='err';msg.textContent='❌ '+d.error;
    }
  }catch(e){msg.className='err';msg.textContent='❌ 通信エラー: '+e.message;}
  setTimeout(()=>{msg.style.display='none';},5000);
});

load();
</script>
</body>
</html>"""


_WIFI_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>CarIoT WiFi</title>
<style>
:root{--bg:#0d1117;--sf:#161b22;--bd:#30363d;--tx:#c9d1d9;--dm:#6e7681;
      --g:#3fb950;--y:#d29922;--r:#f85149;--bl:#58a6ff;--or:#f0883e}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,monospace;padding:12px;font-size:14px}
header{display:flex;align-items:center;justify-content:space-between;padding-bottom:10px;
       border-bottom:1px solid var(--bd);margin-bottom:12px}
h1{color:var(--bl);font-size:1.1rem}
nav a{color:var(--bl);text-decoration:none;font-size:.85rem;margin-left:12px}
.card{background:var(--sf);border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:12px}
.card h2{font-size:.95rem;margin-bottom:10px;border-bottom:1px solid var(--bd);padding-bottom:8px}
.row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;
     border-bottom:1px solid var(--bd)}
.row:last-child{border-bottom:none}
.lbl{color:var(--dm);font-size:.8rem}
.val{font-weight:600}
.g{color:var(--g)}.y{color:var(--y)}.r{color:var(--r)}.or{color:var(--or)}
.ap-box{background:#1a1208;border:2px solid var(--or);border-radius:8px;padding:14px;margin-bottom:12px}
.ap-box h2{color:var(--or);font-size:.95rem;margin-bottom:10px}
.ap-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0}
.ap-val{font-size:1.1rem;font-weight:700;color:var(--or);letter-spacing:.05em}
.copy{background:transparent;border:1px solid var(--or);color:var(--or);border-radius:4px;
      padding:2px 8px;font-size:.75rem;cursor:pointer;margin-left:8px}
.copy:hover{background:var(--or);color:#000}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{background:var(--bg);color:var(--dm);padding:7px 8px;text-align:left;
   font-weight:normal;border-bottom:1px solid var(--bd)}
td{padding:7px 8px;border-bottom:1px solid var(--bd);vertical-align:middle}
tr:last-child td{border-bottom:none}
.pri{color:var(--bl);font-size:.8rem}
.btn-sm{border:none;border-radius:5px;padding:4px 10px;font-size:.78rem;cursor:pointer;font-weight:600}
.btn-conn{background:#1f6feb;color:white}.btn-conn:hover{background:#388bfd}
.btn-del{background:#4a0d0d;color:var(--r);border:1px solid var(--r)}.btn-del:hover{background:var(--r);color:#000}
.field{margin-bottom:10px}
.field label{display:block;color:var(--dm);font-size:.75rem;margin-bottom:4px;
              text-transform:uppercase;letter-spacing:.06em}
.field input{background:var(--bg);border:1px solid var(--bd);color:var(--tx);
              border-radius:6px;padding:8px 10px;font-size:.9rem;width:100%;font-family:monospace}
.field input:focus{outline:none;border-color:var(--bl)}
.pw-wrap{position:relative}
.pw-wrap input{padding-right:60px}
.pw-toggle{position:absolute;right:8px;top:50%;transform:translateY(-50%);
            background:none;border:none;color:var(--dm);cursor:pointer;font-size:.78rem}
.btn{width:100%;border:none;border-radius:8px;padding:11px;font-size:.95rem;
      cursor:pointer;font-weight:600;margin-top:4px}
.btn-blue{background:#1f6feb;color:white}.btn-blue:hover{background:#388bfd}
.btn-ap{background:#2a1a00;border:1px solid var(--or);color:var(--or)}.btn-ap:hover{background:var(--or);color:#000}
.btn-stop{background:#1f0d0d;border:1px solid var(--r);color:var(--r)}.btn-stop:hover{background:var(--r);color:#000}
.btn-scan{background:var(--bg);border:1px solid var(--bd);color:var(--dm)}.btn-scan:hover{border-color:var(--bl);color:var(--bl)}
#msg{border-radius:8px;padding:10px;text-align:center;font-size:.88rem;margin-bottom:10px;display:none}
.ok{background:#0d2618;border:1px solid var(--g);color:var(--g)}
.err{background:#1f0d0d;border:1px solid var(--r);color:var(--r)}
.warn{background:#1f1a0d;border:1px solid var(--y);color:var(--y)}
.empty{color:var(--dm);font-size:.85rem;padding:12px 0;text-align:center}
.scan-item{padding:5px 0;border-bottom:1px solid var(--bd);cursor:pointer;font-size:.85rem}
.scan-item:hover{color:var(--bl)}
.scan-item:last-child{border-bottom:none}
.sig{color:var(--dm);font-size:.75rem;margin-left:8px}
</style>
</head>
<body>
<header>
  <h1>&#128246; WiFi設定</h1>
  <nav><a href="/">ダッシュボード</a><a href="/files">ファイル</a><a href="/settings">設定</a></nav>
</header>

<div id="msg"></div>

<!-- 接続状態 -->
<div class="card" id="status-card">
  <h2>&#128268; 現在の状態</h2>
  <div class="row"><span class="lbl">接続先</span><span class="val g" id="s-ssid">読込中...</span></div>
  <div class="row"><span class="lbl">ローカルIP</span><span class="val" id="s-ip">--</span></div>
  <div class="row"><span class="lbl">モード</span><span class="val" id="s-mode">--</span></div>
</div>

<!-- APモード情報（APモード時のみ表示） -->
<div class="ap-box" id="ap-box" style="display:none">
  <h2>&#128241; スマホからのアクセス方法（APモード中）</h2>
  <div class="ap-row"><span class="lbl">SSID</span>
    <span><span class="ap-val" id="ap-ssid">CarIoT-AP</span>
    <button class="copy" onclick="copy('ap-ssid')">コピー</button></span>
  </div>
  <div class="ap-row" id="ap-pw-row" style="display:none"><span class="lbl">パスワード</span>
    <span><span class="ap-val" id="ap-pw"></span>
    <button class="copy" onclick="copy('ap-pw')">コピー</button></span>
  </div>
  <div class="ap-row" id="ap-open-row"><span class="lbl">パスワード</span>
    <span class="ap-val" style="color:var(--g)">なし（オープン）</span>
  </div>
  <div class="ap-row"><span class="lbl">URL</span>
    <span><span class="ap-val" id="ap-url">http://10.42.0.1:5000</span>
    <button class="copy" onclick="copy('ap-url')">コピー</button></span>
  </div>
  <div style="margin-top:10px;font-size:.78rem;color:var(--dm);line-height:1.5">
    ① スマホのWiFiを上記SSIDに接続　② ブラウザで上記URLを開く<br>
    WiFi設定完了後「APモード停止」を押すとRaspiが通常WiFiへ再接続します
  </div>
</div>

<!-- 保存済みネットワーク -->
<div class="card">
  <h2>&#128275; 保存済みネットワーク</h2>
  <div id="net-list"><div class="empty">読込中...</div></div>
  <div style="display:flex;gap:8px;margin-top:10px">
    <button class="btn btn-ap" style="flex:1" onclick="startAP()">APモード手動起動</button>
    <button class="btn btn-stop" style="flex:1" id="btn-stop-ap" onclick="stopAP()">APモード停止</button>
  </div>
</div>

<!-- ネットワーク追加 -->
<div class="card">
  <h2>&#10133; ネットワーク追加</h2>
  <div class="field">
    <label>SSID</label>
    <input type="text" id="new-ssid" placeholder="WiFiのSSID名">
  </div>
  <div class="field">
    <label>パスワード</label>
    <div class="pw-wrap">
      <input type="password" id="new-pw" placeholder="WiFiパスワード">
      <button class="pw-toggle" onclick="togglePw()">表示</button>
    </div>
  </div>
  <div class="field">
    <label>優先度（数値が大きいほど優先）</label>
    <input type="number" id="new-pri" value="10" min="0" max="100" style="width:100px">
  </div>
  <div style="display:flex;gap:8px">
    <button class="btn btn-scan" style="flex:0 0 auto;width:auto;padding:11px 16px" onclick="scanNets()">&#128268; スキャン</button>
    <button class="btn btn-blue" style="flex:1" onclick="addNet()">追加・保存</button>
  </div>
  <div id="scan-list" style="margin-top:10px;display:none">
    <div style="color:var(--dm);font-size:.75rem;margin-bottom:4px">タップでSSID入力欄へコピー</div>
    <div id="scan-items"></div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
const showMsg=(txt,cls,sec=4)=>{
  const m=$('msg');m.textContent=txt;m.className=cls;m.style.display='block';
  setTimeout(()=>m.style.display='none',sec*1000);
};
function copy(id){
  navigator.clipboard&&navigator.clipboard.writeText($(id).textContent);
  showMsg('コピーしました','ok',2);
}
function togglePw(){
  const i=$('new-pw');
  i.type=i.type==='password'?'text':'password';
}

async function loadStatus(){
  try{
    const d=await fetch('/api/wifi/status').then(r=>r.json());
    if(d.ap_mode){
      $('s-ssid').textContent='APモード中';
      $('s-ssid').className='val or';
      $('s-mode').textContent='APモード（ホットスポット）';
      $('s-mode').className='val or';
      $('ap-box').style.display='block';
      $('ap-ssid').textContent=d.ap_ssid||'CarIoT-AP';
      if(d.ap_password){
        $('ap-pw').textContent=d.ap_password;
        $('ap-pw-row').style.display='flex';
        $('ap-open-row').style.display='none';
      }else{
        $('ap-pw-row').style.display='none';
        $('ap-open-row').style.display='flex';
      }
      $('ap-url').textContent='http://'+(d.ap_ip||'192.168.1.1')+':5000';
    } else {
      $('ap-box').style.display='none';
      $('s-ssid').textContent=d.connected_ssid||'未接続';
      $('s-ssid').className='val '+(d.connected_ssid?'g':'r');
      $('s-mode').textContent=d.connected_ssid?'クライアントモード':'未接続';
      $('s-mode').className='val '+(d.connected_ssid?'g':'r');
    }
    $('s-ip').textContent=d.local_ip||'--';
  }catch(e){$('s-ssid').textContent='取得エラー';$('s-ssid').className='val r';}
}

async function loadNetworks(){
  try{
    const nets=await fetch('/api/wifi/networks').then(r=>r.json());
    const el=$('net-list');
    if(!nets.length){el.innerHTML='<div class="empty">保存済みネットワークなし</div>';return;}
    el.innerHTML='<table><thead><tr><th>SSID</th><th>優先度</th><th>操作</th></tr></thead><tbody>'+
      nets.map(n=>`<tr>
        <td>${n.name}</td>
        <td class="pri">${n.priority}</td>
        <td style="white-space:nowrap">
          <button class="btn-sm btn-conn" onclick="connTo('${n.name.replace(/'/g,"\\'")}')">接続</button>
          &nbsp;
          <button class="btn-sm btn-del" onclick="delNet('${n.name.replace(/'/g,"\\'")}')">削除</button>
        </td>
      </tr>`).join('')+'</tbody></table>';
  }catch(e){$('net-list').innerHTML='<div class="empty">読込エラー</div>';}
}

async function startAP(){
  if(!confirm('APモードを起動します。現在のWiFi接続が切断されます。よろしいですか？'))return;
  try{
    const r=await fetch('/api/wifi/ap/start',{method:'POST',headers:authHeader()});
    const d=await r.json();
    if(d.ok){showMsg('APモード起動しました。SSIDに接続してください','ok',6);loadStatus();}
    else showMsg('エラー: '+d.error,'err');
  }catch(e){showMsg('通信エラー: '+e.message,'err');}
}

async function stopAP(){
  try{
    const r=await fetch('/api/wifi/ap/stop',{method:'POST',headers:authHeader()});
    const d=await r.json();
    if(d.ok){showMsg('APモード停止しました。WiFiへ再接続中...','ok',6);setTimeout(loadStatus,3000);}
    else showMsg('エラー: '+d.error,'err');
  }catch(e){showMsg('通信エラー: '+e.message,'err');}
}

async function connTo(name){
  if(!confirm(name+' に接続します。WiFiが切り替わります（Tailscale経由なら数秒後に再接続）。'+'\\nAPモード中の場合はこのページが切断されます。'))return;
  try{
    const r=await fetch('/api/wifi/connect',{method:'POST',
      headers:{...authHeader(),'Content-Type':'application/json'},
      body:JSON.stringify({name})});
    const d=await r.json();
    if(d.ok)showMsg(name+' に接続しました（WiFi切替中）','ok',6);
    else showMsg('エラー: '+d.error,'err');
    setTimeout(loadStatus,3000);
  }catch(e){showMsg('接続処理中（WiFi切替による通信断の可能性あり）','warn',8);}
}

async function delNet(name){
  if(!confirm(name+' を削除しますか？'))return;
  try{
    const r=await fetch('/api/wifi/delete',{method:'POST',
      headers:{...authHeader(),'Content-Type':'application/json'},
      body:JSON.stringify({name})});
    const d=await r.json();
    if(d.ok){showMsg('削除しました','ok');loadNetworks();}
    else showMsg('エラー: '+d.error,'err');
  }catch(e){showMsg('通信エラー: '+e.message,'err');}
}

async function addNet(){
  const ssid=$('new-ssid').value.trim();
  const pw=$('new-pw').value;
  const pri=parseInt($('new-pri').value)||10;
  if(!ssid){showMsg('SSIDを入力してください','err');return;}
  if(!pw){showMsg('パスワードを入力してください','err');return;}
  try{
    const r=await fetch('/api/wifi/add',{method:'POST',
      headers:{...authHeader(),'Content-Type':'application/json'},
      body:JSON.stringify({ssid,password:pw,priority:pri})});
    const d=await r.json();
    if(d.ok){
      showMsg(ssid+' を保存しました','ok');
      $('new-ssid').value='';$('new-pw').value='';
      $('scan-list').style.display='none';
      loadNetworks();
    }else showMsg('エラー: '+d.error,'err');
  }catch(e){showMsg('通信エラー: '+e.message,'err');}
}

async function scanNets(){
  $('scan-list').style.display='block';
  $('scan-items').innerHTML='<div class="empty">スキャン中...</div>';
  try{
    const nets=await fetch('/api/wifi/scan').then(r=>r.json());
    if(!nets.length){$('scan-items').innerHTML='<div class="empty">見つかりませんでした</div>';return;}
    $('scan-items').innerHTML=nets.map(n=>
      `<div class="scan-item" onclick="$('new-ssid').value='${n.ssid.replace(/'/g,"\\'")}'" >
        ${n.ssid}<span class="sig">&#128246;${n.signal}%</span>
      </div>`
    ).join('');
  }catch(e){$('scan-items').innerHTML='<div class="empty">スキャンエラー</div>';}
}

function authHeader(){
  const creds=btoa('pi:'+prompt('WebUI パスワード（Basic認証）',''));
  return{Authorization:'Basic '+creds};
}

loadStatus();loadNetworks();
setInterval(loadStatus,8000);
</script>
</body>
</html>"""


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(_DASHBOARD_HTML)


@app.route("/api/status")
def api_status():
    return jsonify(get_status())


@app.route("/api/bms/ctrl", methods=["GET"])
def api_bms_ctrl_get():
    return jsonify({"enabled": bms_module.is_polling_enabled()})


@app.route("/api/bms/ctrl", methods=["POST"])
@auth.login_required
def api_bms_ctrl_post():
    data = request.get_json(silent=True) or {}
    enabled = data.get("enabled")
    if enabled is True:
        bms_module.enable_polling()
    elif enabled is False:
        bms_module.disable_polling()
    else:
        return jsonify({"ok": False, "error": "enabled(bool)は必須です"}), 400
    return jsonify({"ok": True, "enabled": bms_module.is_polling_enabled()})


@app.route("/api/history")
def api_history():
    scale = request.args.get("scale", "hour")
    if scale not in ("minute", "hour", "day", "week", "month"):
        return jsonify({"error": "invalid scale"}), 400
    try:
        before = int(request.args["before"]) if "before" in request.args else None
        limit = int(request.args.get("limit", 0))
    except ValueError:
        return jsonify({"error": "invalid params"}), 400
    try:
        return jsonify(history_store.query(scale, before, limit))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(settings_store.get())


@app.route("/api/settings", methods=["POST"])
@auth.login_required
def api_settings_post():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": False, "error": "JSON本文が必要です"}), 400
    ok, err = settings_store.update(data)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 400


@app.route("/settings")
@auth.login_required
def settings_page():
    return render_template_string(_SETTINGS_HTML)


@app.route("/files")
@auth.login_required
def files():
    base = os.path.realpath(config.STORAGE_BASE)
    rel_dir = request.args.get("dir", "").lstrip("/")
    target = os.path.realpath(os.path.join(base, rel_dir)) if rel_dir else base

    # パストラバーサル防止
    if not (target == base or target.startswith(base + os.sep)):
        abort(403)

    if not os.path.isdir(base):
        return render_template_string(_FILES_HTML, rel_dir="", items=[],
                                      parent_url="", error=f"{base} がマウントされていません")

    if not os.path.isdir(target):
        abort(404)

    entries = []
    try:
        for name in sorted(os.listdir(target)):
            full = os.path.join(target, name)
            stat = os.stat(full)
            rel = os.path.relpath(full, base).replace("\\", "/")
            entries.append({
                "name": name,
                "rel_path": rel,
                "is_dir": os.path.isdir(full),
                "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "size_str": "—" if os.path.isdir(full) else _fmt_size(stat.st_size),
            })
    except PermissionError as e:
        return render_template_string(_FILES_HTML, rel_dir=rel_dir, items=[],
                                      parent_url="/files", error=str(e))

    # ディレクトリを先に
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

    parent_url = "/files"
    if rel_dir:
        parent_rel = os.path.dirname(rel_dir)
        parent_url = f"/files?dir={parent_rel}" if parent_rel else "/files"

    return render_template_string(_FILES_HTML, rel_dir=rel_dir, items=entries,
                                  parent_url=parent_url, error=None)


@app.route("/wifi")
@auth.login_required
def wifi_page():
    return render_template_string(_WIFI_HTML)


@app.route("/api/wifi/status")
def api_wifi_status():
    return jsonify(wifi_manager.get_wifi_status())


@app.route("/api/wifi/networks")
def api_wifi_networks():
    return jsonify(wifi_manager.get_networks())


@app.route("/api/wifi/scan")
def api_wifi_scan():
    return jsonify(wifi_manager.scan_networks())


@app.route("/api/wifi/add", methods=["POST"])
@auth.login_required
def api_wifi_add():
    data = request.get_json(silent=True) or {}
    ssid = str(data.get("ssid", "")).strip()
    password = str(data.get("password", ""))
    priority = int(data.get("priority", 10))
    if not ssid or not password:
        return jsonify({"ok": False, "error": "ssidとpasswordは必須です"}), 400
    ok, err = wifi_manager.add_network(ssid, password, priority)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 400


@app.route("/api/wifi/delete", methods=["POST"])
@auth.login_required
def api_wifi_delete():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "nameは必須です"}), 400
    ok, err = wifi_manager.delete_network(name)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 400


@app.route("/api/wifi/connect", methods=["POST"])
@auth.login_required
def api_wifi_connect():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"ok": False, "error": "nameは必須です"}), 400
    ok, err = wifi_manager.connect_to(name)
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 400


@app.route("/api/wifi/ap/start", methods=["POST"])
@auth.login_required
def api_wifi_ap_start():
    ok, err = wifi_manager.start_ap()
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 500


@app.route("/api/wifi/ap/stop", methods=["POST"])
@auth.login_required
def api_wifi_ap_stop():
    ok, err = wifi_manager.stop_ap()
    if ok:
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": err}), 500


@app.route("/files/dl/<path:filepath>")
@auth.login_required
def download(filepath):
    base = os.path.realpath(config.STORAGE_BASE)
    target = os.path.realpath(os.path.join(base, filepath))

    if not (target == base or target.startswith(base + os.sep)):
        abort(403)
    if not os.path.isfile(target):
        abort(404)

    return send_from_directory(
        os.path.dirname(target),
        os.path.basename(target),
        as_attachment=True,
    )
