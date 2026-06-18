<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Касса · детектор отклонений</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/xlsx/0.18.5/xlsx.full.min.js"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Golos+Text:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --paper:#EAE3D5; --surface:#F6F2E9; --surface2:#FBF8F1;
  --ink:#1A1813; --ink2:#6B655A; --hair:#D6CDBC;
  --red:#B23A2E; --amber:#A9781B; --lime:#5F7D17; --steel:#34424A;
  --redbg:#F6E2DD; --amberbg:#F4E9D2; --limebg:#E7ECD4; --steelbg:#E2E7E6;
  --display:'Space Grotesk',sans-serif; --body:'Golos Text',sans-serif; --mono:'JetBrains Mono',monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.5;
  background-image:repeating-linear-gradient(0deg,transparent,transparent 27px,rgba(26,24,19,.035) 27px,rgba(26,24,19,.035) 28px);}
.wrap{max-width:1080px;margin:0 auto;padding:24px 18px 80px}
a{color:var(--steel)}
h1,h2,h3{font-family:var(--display);font-weight:700;letter-spacing:-.01em;margin:0}
.mono{font-family:var(--mono);font-variant-numeric:tabular-nums}
.muted{color:var(--ink2)}

header{border-bottom:2px solid var(--ink);padding-bottom:16px;margin-bottom:26px}
.kick{font-family:var(--mono);font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--ink2)}
h1{font-size:clamp(26px,5vw,40px);line-height:1.02;margin-top:8px}
.sub{margin-top:10px;max-width:62ch;color:var(--ink2)}
.privacy{display:inline-flex;align-items:center;gap:8px;margin-top:14px;font-size:12.5px;
  font-family:var(--mono);color:var(--lime);border:1px solid var(--lime);border-radius:2px;padding:4px 9px;background:var(--limebg)}
.privacy b{color:var(--ink)}

.step{margin:22px 0;border:1px solid var(--hair);background:var(--surface);border-radius:3px}
.step.lead{border-color:var(--ink);border-width:1.5px}
.step-body{padding:16px}
.hidden{display:none !important}

#drop{border:2px dashed var(--hair);border-radius:3px;padding:38px 18px;text-align:center;cursor:pointer;
  transition:border-color .15s,background .15s}
#drop:hover,#drop.drag{border-color:var(--lime);background:var(--limebg)}
#drop .big{font-family:var(--display);font-size:19px;font-weight:600}
#drop .hint{color:var(--ink2);font-size:13px;margin-top:6px}

#status{margin-top:14px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{display:inline-flex;gap:7px;align-items:center;font-family:var(--mono);font-size:12.5px;
  background:var(--surface2);border:1px solid var(--hair);padding:5px 10px;border-radius:2px}
.chip.ok{border-color:var(--lime);background:var(--limebg)} .chip.ok b{color:var(--lime)}
.chip.warn{border-color:var(--amber);background:var(--amberbg)} .chip.warn b{color:var(--amber)}
.chip b{color:var(--ink)}
.hintline{font-size:12.5px;color:var(--ink2);margin-top:10px}
.hintline a{cursor:pointer;text-decoration:underline}

details.settings{margin:22px 0;border:1px dashed var(--hair);background:var(--surface);border-radius:3px}
details.settings>summary{cursor:pointer;list-style:none;padding:13px 16px;font-family:var(--mono);font-size:12.5px;
  letter-spacing:.04em;color:var(--steel);display:flex;align-items:center;gap:9px}
details.settings>summary::-webkit-details-marker{display:none}
details.settings>summary::before{content:"▸";color:var(--ink2)}
details.settings[open]>summary::before{content:"▾"}
.settings .step-body{border-top:1px dashed var(--hair)}

label.fld{display:block;font-size:12.5px;font-weight:600;margin:0 0 5px}
label.fld .req{color:var(--red)}
select,input[type=text],input[type=number]{width:100%;font-family:var(--mono);font-size:13px;color:var(--ink);
  background:var(--surface2);border:1px solid var(--hair);border-radius:2px;padding:8px 9px}
select:focus,input:focus{outline:2px solid var(--steel);outline-offset:1px;border-color:var(--steel)}
.grid{display:grid;gap:14px 16px}
.g2{grid-template-columns:repeat(2,1fr)} .g3{grid-template-columns:repeat(3,1fr)} .g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:720px){.g2,.g3,.g4{grid-template-columns:1fr}}
.fieldset{border:1px solid var(--hair);border-radius:3px;padding:14px;margin-top:14px;background:var(--surface2)}
.fieldset>.lg{font-family:var(--mono);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink2);margin-bottom:12px}
.row-check{display:flex;align-items:center;gap:9px;margin:2px 0 0}
.row-check input{width:17px;height:17px;accent-color:var(--lime)}
.note{font-size:12px;color:var(--ink2);margin-top:6px}

.tablewrap{overflow:auto;border:1px solid var(--hair);border-radius:2px;max-height:220px;margin-top:4px}
table.prev{border-collapse:collapse;font-family:var(--mono);font-size:11.5px;white-space:nowrap}
table.prev th,table.prev td{border:1px solid var(--hair);padding:3px 7px;text-align:left}
table.prev th{background:var(--steelbg);position:sticky;top:0;color:var(--steel)}

.btn{font-family:var(--display);font-weight:600;font-size:15px;border:1.5px solid var(--ink);background:var(--ink);color:var(--surface2);
  padding:10px 18px;border-radius:2px;cursor:pointer;transition:transform .05s, background .15s}
.btn:hover{background:#000} .btn:active{transform:translateY(1px)}
.btn.ghost{background:transparent;color:var(--ink)} .btn.ghost:hover{background:var(--ink);color:var(--surface2)}
.btnrow{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}

#results{margin-top:28px}
.readout{background:var(--ink);border-radius:4px;padding:22px 24px;color:var(--surface2);position:relative;overflow:hidden}
.readout .lbl{font-family:var(--mono);font-size:12px;letter-spacing:.2em;text-transform:uppercase;color:#9a9384}
.readout .figure{font-family:var(--mono);font-weight:700;font-size:clamp(40px,9vw,76px);line-height:1;margin:8px 0 2px;
  display:flex;align-items:center;gap:.18em;letter-spacing:-.02em}
.lamp{width:.34em;height:.34em;border-radius:50%;flex:0 0 auto;box-shadow:0 0 14px currentColor}
.fig-neg{color:#E8857A} .fig-pos{color:#E6C062} .fig-zero{color:#A6C04A}
.readout .ccy{font-size:.28em;color:#9a9384;align-self:flex-end;margin-bottom:.4em}
.readout .verdict{font-family:var(--body);font-size:14.5px;color:#d9d3c6;max-width:70ch;margin-top:6px}
.readout .scan{position:absolute;inset:0;pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(255,255,255,.02) 3px,rgba(255,255,255,.02) 4px)}

.sec-h{font-family:var(--mono);font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink2);
  margin:30px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--hair)}
.bento{display:grid;gap:14px;grid-template-columns:repeat(2,1fr)}
@media(max-width:720px){.bento{grid-template-columns:1fr}}
.card{border:1px solid var(--hair);border-left-width:4px;border-radius:3px;background:var(--surface);padding:15px 16px}
.card.proven{border-left-color:var(--red)} .card.likely{border-left-color:var(--amber)}
.card.zone{border-left-color:var(--steel)} .card.fact{border-left-color:var(--lime)}
.card.span2{grid-column:1/-1}
.card .ch{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:6px}
.card .ct{font-family:var(--display);font-weight:600;font-size:15.5px}
.sev{font-family:var(--mono);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;padding:2px 7px;border-radius:2px;white-space:nowrap}
.sev.proven{background:var(--redbg);color:var(--red)} .sev.likely{background:var(--amberbg);color:var(--amber)}
.sev.zone{background:var(--steelbg);color:var(--steel)} .sev.fact{background:var(--limebg);color:var(--lime)}
.card .amt{font-family:var(--mono);font-weight:700;font-size:20px}
.amt.neg{color:var(--red)} .amt.pos{color:var(--amber)}
.card .desc{font-size:13.5px;color:#403c34;margin-top:7px}
.card details{margin-top:10px} .card summary{cursor:pointer;font-size:12.5px;color:var(--steel);font-family:var(--mono)}
.minitable{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:11.5px;margin-top:9px}
.minitable th,.minitable td{border:1px solid var(--hair);padding:4px 7px;text-align:left;white-space:nowrap}
.minitable th{background:var(--surface2);color:var(--steel)}
.minitable td.r,.minitable th.r{text-align:right}
.tred{color:var(--red);font-weight:700}

.reveal{opacity:0;transform:translateY(8px);animation:rv .4s ease forwards}
@keyframes rv{to{opacity:1;transform:none}}
@media(prefers-reduced-motion:reduce){.reveal{animation:none;opacity:1;transform:none}}

footer{margin-top:46px;padding-top:16px;border-top:1px solid var(--hair);font-size:12px;color:var(--ink2)}
.err{background:var(--redbg);border:1px solid var(--red);color:var(--red);padding:10px 13px;border-radius:2px;font-size:13.5px;margin-top:12px;font-family:var(--mono)}
@media print{body{background:#fff}.step,#drop,.btnrow,header .privacy,details.settings{display:none}.readout{background:#fff;color:#000;border:2px solid #000}}
</style>
</head>
<body>
<div class="wrap">

  <header>
    <div class="kick">1С · карточка счёта 50.2 · форензик-сверка</div>
    <h1>Детектор отклонений кассы</h1>
    <p class="sub">Перетащите стандартную выгрузку карточки счёта — структура распознаётся сама, отчёт строится сразу. Находит точку и величину отклонения остатка (в минус и в плюс) и ранжирует вероятные ошибки ввода.</p>
    <span class="privacy">●&nbsp; <b>Данные не покидают браузер</b> — разбор идёт локально</span>
  </header>

  <!-- STEP 1: drop -->
  <section class="step lead">
    <div class="step-body">
      <div id="drop" tabindex="0" role="button" aria-label="Загрузить файл">
        <div class="big">Перетащите файл выгрузки сюда → готовый отчёт</div>
        <div class="hint">.xlsx / .xls / .csv · обрабатывается на вашем устройстве · разметка не требуется</div>
        <input id="file" type="file" accept=".xlsx,.xls,.csv" class="hidden">
      </div>
      <div id="status"></div>
    </div>
  </section>

  <!-- RESULTS -->
  <div id="results"></div>

  <!-- SETTINGS / manual override (collapsed) -->
  <details class="settings" id="settings">
    <summary>Настройки и разметка — для нестандартного файла или плюсового отклонения</summary>
    <div class="step-body">
      <div class="grid g2">
        <div><label class="fld" for="sheetsel">Лист</label><select id="sheetsel"></select></div>
        <div><label class="fld" for="hdrrow">Строк сверху пропустить</label><input id="hdrrow" type="number" value="0" min="0" step="1"></div>
      </div>
      <div class="tablewrap"><table class="prev" id="prevtab"></table></div>
      <div class="note">Предпросмотр первых строк выбранного листа.</div>

      <div class="fieldset">
        <div class="lg">Столбцы реестра (по умолчанию — зашитая структура)</div>
        <div class="grid g4">
          <div><label class="fld">Дата <span class="req">*</span></label><select id="m_date"></select></div>
          <div><label class="fld">Документ <span class="req">*</span></label><select id="m_doc"></select></div>
          <div><label class="fld">Счёт по дебету</label><select id="m_dacc"></select></div>
          <div><label class="fld">Сумма по дебету <span class="req">*</span></label><select id="m_damt"></select></div>
          <div><label class="fld">Счёт по кредиту</label><select id="m_cacc"></select></div>
          <div><label class="fld">Сумма по кредиту <span class="req">*</span></label><select id="m_camt"></select></div>
          <div><label class="fld">Остаток (Сальдо)</label><select id="m_bal"></select></div>
          <div><label class="fld">Сторона (Д / К)</label><select id="m_side"></select></div>
        </div>
      </div>

      <div class="fieldset">
        <div class="lg">Счета (зашиты; меняйте только под другую конфигурацию 1С)</div>
        <div class="grid g3">
          <div><label class="fld">Анализируемая касса <span class="req">*</span></label><input id="a_cash" type="text" placeholder="50.2"></div>
          <div><label class="fld">Инкассация / в банк</label><input id="a_dep" type="text" placeholder="57.1.1, 51"></div>
          <div><label class="fld">Возвраты клиентам</label><input id="a_ref" type="text" placeholder="76.9.1, 62.10.1"></div>
          <div><label class="fld">Продажи (выручка)</label><input id="a_sale" type="text" placeholder="90.1.1"></div>
          <div><label class="fld">Авансы / предоплаты</label><input id="a_adv" type="text" placeholder="62.4.1"></div>
          <div><label class="fld">Переводы между кассами</label><input id="a_xfer" type="text" placeholder="50.1"></div>
        </div>
      </div>

      <div class="fieldset">
        <div class="lg">Операционные данные (УТ)</div>
        <div class="row-check"><input id="ut_on" type="checkbox"><label for="ut_on" style="font-weight:600;font-size:13.5px">В файле есть колонки УТ (определяется автоматически)</label></div>
        <div id="utfields" class="grid g4 hidden" style="margin-top:14px">
          <div><label class="fld">Дата (УТ)</label><select id="u_date"></select></div>
          <div><label class="fld">Сумма (УТ)</label><select id="u_amt"></select></div>
          <div><label class="fld">Получатель (УТ)</label><select id="u_to"></select></div>
          <div><label class="fld">Ключ «инкассация» в получателе</label><input id="u_key" type="text" value="ентральн"></div>
        </div>
      </div>

      <div class="fieldset">
        <div class="lg">Эталон для плюсового отклонения — необязательно</div>
        <div class="grid g2">
          <div><label class="fld">Ожидаемый / фактический остаток на закрытие</label><input id="expbal" type="number" step="0.01" placeholder="напр. 0 или сумма размена"></div>
          <div style="align-self:end" class="note">Если книга показывает <b>больше</b>, чем по факту — минуса нет, и нужен эталон. Для кассы минус ловится без него.</div>
        </div>
      </div>

      <div class="btnrow">
        <button class="btn" id="recalc">Пересчитать</button>
        <button class="btn ghost" id="reset">Сбросить</button>
      </div>
      <div id="maperr"></div>
    </div>
  </details>

  <footer>
    Зашитая структура: B — дата, C — документ, E/F — дебет, G/H — кредит, I — сторона, J — остаток; M/N/O — УТ. Счета: касса 50.2, инкассация 57.1.1/51, возвраты 76.9.1/62.10.1, продажи 90.1.1, авансы 62.4.1. На входе проверяется соответствие структуры; УТ подключается, если колонки заполнены. Что не доказуемо — помечается зоной проверки, а не выдаётся за точную ошибку.
  </footer>
</div>

<script>
"use strict";
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let WB=null, ROWS=[], NCOLS=0;
const COL=i=>{let s="";i++;while(i>0){let m=(i-1)%26;s=String.fromCharCode(65+m)+s;i=(i-(m+1))/26;}return s;};
const colSelects=["m_date","m_doc","m_dacc","m_damt","m_cacc","m_camt","m_bal","m_side","u_date","u_amt","u_to"];

/* fixed structure (0-based columns): B1 C2 E4 F5 G6 H7 I8 J9 · M12 N13 O14 */
const FIXED={
  cols:{m_date:1,m_doc:2,m_dacc:4,m_damt:5,m_cacc:6,m_camt:7,m_bal:9,m_side:8,u_date:12,u_amt:13,u_to:14},
  cash:"50.2", dep:["57.1.1","51"], ref:["76.9.1","62.10.1"], sale:["90.1.1"], adv:["62.4.1"], xfer:["50.1"], utKey:"ентральн"
};

/* ---------- helpers ---------- */
function toNum(v){
  if(v==null||v==="")return null;
  if(typeof v==="number")return v;
  let s=String(v).replace(/\u00a0/g," ").replace(/\s/g,"").replace(",",".");
  s=s.replace(/[^0-9.\-]/g,"");
  if(s===""||s==="-"||s===".")return null;
  let n=parseFloat(s); return isNaN(n)?null:n;
}
function toDate(v){
  if(v==null||v==="")return null;
  if(v instanceof Date)return new Date(v.getFullYear(),v.getMonth(),v.getDate());
  if(typeof v==="number"){const d=XLSX.SSF?XLSX.SSF.parse_date_code(v):null;if(d&&d.y)return new Date(d.y,d.m-1,d.d);}
  const m=String(v).match(/(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{4})/);
  if(m)return new Date(+m[3],+m[2]-1,+m[1]);
  return null;
}
const dkey=d=>d?d.getFullYear()+"-"+String(d.getMonth()+1).padStart(2,"0")+"-"+String(d.getDate()).padStart(2,"0"):"";
const dru=d=>d?String(d.getDate()).padStart(2,"0")+"."+String(d.getMonth()+1).padStart(2,"0")+"."+d.getFullYear():"";
const fmt=n=>(n<0?"−":"")+Math.abs(n).toLocaleString("ru-RU",{minimumFractionDigits:2,maximumFractionDigits:2});
const timeOf=s=>{const m=String(s).match(/(\d{1,2}:\d{2}:\d{2})/);return m?m[1]:"";};
const docnumOf=s=>{const t=String(s).replace(/№/g," ").split(/\s+/).find(x=>/^\d+$/.test(x));return t||null;};
const isAcct=v=>/^\d{2}(\.\d+){0,3}$/.test(String(v||"").trim());
function setAccts(id,arr){const el=$("#"+id);el.value=arr.join(", ");el.placeholder=arr.join(", ");}
const accSet=id=>new Set(($("#"+id).value||$("#"+id).placeholder||"").split(",").map(s=>s.trim()).filter(Boolean));

/* ---------- file load ---------- */
function handleFile(file){
  const r=new FileReader();
  r.onload=e=>{
    try{
      WB=XLSX.read(e.target.result,{type:"binary",cellDates:true});
      const sel=$("#sheetsel");sel.innerHTML="";
      WB.SheetNames.forEach(n=>{const o=document.createElement("option");o.value=n;o.textContent=n;sel.appendChild(o);});
      sel.value=WB.SheetNames.includes("Лист1")?"Лист1":WB.SheetNames[0];
      $("#fname_holder")&&($("#fname_holder").textContent=file.name);
      window._fname=file.name;
      loadSheet();
    }catch(err){renderStatus(null,["не удалось прочитать файл: "+err.message]);}
  };
  r.readAsBinaryString(file);
}
function loadSheet(){
  const ws=WB.Sheets[$("#sheetsel").value];
  ROWS=XLSX.utils.sheet_to_json(ws,{header:1,raw:true,defval:null,blankrows:true});
  NCOLS=ROWS.reduce((m,r)=>Math.max(m,r.length),0);
  renderPreview(); buildColSelects(); applyFixedConfig(); validateAndRun();
}
function renderPreview(){
  const skip=+$("#hdrrow").value||0;
  const t=$("#prevtab");t.innerHTML="";
  const head=document.createElement("tr");head.innerHTML="<th>#</th>"+Array.from({length:NCOLS},(_,i)=>"<th>"+COL(i)+"</th>").join("");
  t.appendChild(head);
  ROWS.slice(skip,skip+22).forEach((row,i)=>{
    const tr=document.createElement("tr");
    tr.innerHTML="<td class='muted'>"+(skip+i+1)+"</td>"+Array.from({length:NCOLS},(_,c)=>{
      let v=row?row[c]:null;if(v instanceof Date)v=dru(v);
      return "<td>"+(v==null?"":String(v).slice(0,26))+"</td>";}).join("");
    t.appendChild(tr);
  });
}
function buildColSelects(){
  const opts="<option value=''>—</option>"+Array.from({length:NCOLS},(_,i)=>"<option value='"+i+"'>"+COL(i)+(sampleOf(i)?" · "+sampleOf(i):"")+"</option>").join("");
  colSelects.forEach(id=>{const el=$("#"+id);const cur=el.value;el.innerHTML=opts;el.value=cur;});
}
function sampleOf(c){
  const skip=+$("#hdrrow").value||0;
  for(const row of ROWS.slice(skip)){let v=row?row[c]:null;if(v!=null&&v!==""){if(v instanceof Date)v=dru(v);return String(v).slice(0,14);}}
  return "";
}

/* ---------- fixed config + validation ---------- */
function applyFixedConfig(){
  for(const [id,c] of Object.entries(FIXED.cols)) $("#"+id).value=String(c);
  $("#a_cash").value=FIXED.cash; setAccts("a_dep",FIXED.dep); setAccts("a_ref",FIXED.ref);
  setAccts("a_sale",FIXED.sale); setAccts("a_adv",FIXED.adv); setAccts("a_xfer",FIXED.xfer);
  $("#u_key").value=FIXED.utKey;
  const ut=utPresent(); $("#ut_on").checked=ut; $("#utfields").classList.toggle("hidden",!ut);
}
function utPresent(){
  const skip=+$("#hdrrow").value||0;
  for(const row of ROWS.slice(skip)){if(!row)continue;
    if(toNum(row[FIXED.cols.u_amt])!=null&&toDate(row[FIXED.cols.u_date]))return true;}
  return false;
}
function detectPivot(){
  const skip=+$("#hdrrow").value||0;const D={},C={};
  for(const row of ROWS.slice(skip)){if(!row)continue;
    const da=String(row[FIXED.cols.m_dacc]??"").trim(),ca=String(row[FIXED.cols.m_cacc]??"").trim();
    if(isAcct(da)&&toNum(row[FIXED.cols.m_damt])!=null)D[da]=(D[da]||0)+1;
    if(isAcct(ca)&&toNum(row[FIXED.cols.m_camt])!=null)C[ca]=(C[ca]||0)+1;}
  return Object.keys({...D,...C}).filter(a=>D[a]&&C[a]).sort((a,b)=>(D[b]+C[b])-(D[a]+C[a]))[0]||null;
}
function validateStructure(){
  const skip=+$("#hdrrow").value||0;let doc=0,acc=0,cash=0;
  for(const row of ROWS.slice(skip)){if(!row)continue;
    if(/ордер|передача|кассовый|накладн/i.test(String(row[FIXED.cols.m_doc]||"")))doc++;
    const da=String(row[FIXED.cols.m_dacc]??"").trim(),ca=String(row[FIXED.cols.m_cacc]??"").trim();
    if(isAcct(da)||isAcct(ca))acc++;
    if(da===FIXED.cash||ca===FIXED.cash)cash++;}
  const problems=[];let cashUsed=FIXED.cash,auto=null;
  if(doc<3)problems.push("в столбце C не найден признак документов («ордер»/«Передача»)");
  if(acc<3)problems.push("в столбцах E/G не найдены коды счетов");
  if(cash<1){auto=detectPivot();if(auto){$("#a_cash").value=auto;cashUsed=auto;}else problems.push("счёт кассы "+FIXED.cash+" в файле не найден");}
  return {ok:problems.length===0,problems,cashUsed,auto};
}
function validateAndRun(){
  $("#maperr").innerHTML="";
  const v=validateStructure();
  renderStatus(v);
  if(v.ok){ $("#settings").open=false; runAnalysis(); }
  else { autodetect(); $("#settings").open=true; $("#results").innerHTML=""; }
}
function renderStatus(v,hardErrs){
  const el=$("#status");
  if(hardErrs){el.innerHTML="<div class='err'>"+hardErrs.join("; ")+"</div>";return;}
  if(!v){el.innerHTML="";return;}
  if(v.ok){
    const ut=$("#ut_on").checked;
    el.innerHTML=`<div class="chips">
      <span class="chip">📄 <span class="mono">${window._fname||""}</span></span>
      <span class="chip ok">✓ <b>структура распознана</b></span>
      <span class="chip">касса <b>${v.cashUsed}</b>${v.auto?" (определена автоматически)":""}</span>
      <span class="chip">УТ: <b>${ut?"есть":"нет"}</b></span>
    </div>
    <div class="hintline">Нестандартный файл или плюсовое отклонение? Откройте <a onclick="document.getElementById('settings').open=true;document.getElementById('settings').scrollIntoView({behavior:'smooth'})">«Настройки и разметка»</a>.</div>`;
  } else {
    el.innerHTML=`<div class="err">Файл не похож на ожидаемую структуру: ${v.problems.join("; ")}.<br>Поля размечены по догадке — проверьте их в «Настройки и разметка» ниже и нажмите «Пересчитать».</div>`;
  }
}

/* ---------- autodetect (fallback for nonstandard files) ---------- */
function autodetect(){
  const skip=+$("#hdrrow").value||0, sample=ROWS.slice(skip,skip+400);
  const sc={date:[],doc:[],acct:[],num:[],side:[]};
  for(let c=0;c<NCOLS;c++){
    let date=0,doc=0,acct=0,num=0,side=0,ne=0;
    for(const row of sample){const v=row?row[c]:null;if(v==null||v==="")continue;ne++;
      if(toDate(v)&&(v instanceof Date||/\d{1,2}[.\/-]\d{1,2}[.\/-]\d{4}/.test(String(v))))date++;
      if(/ордер|передача|накладн|кассовый/i.test(String(v)))doc++;
      if(isAcct(v))acct++;
      if(typeof v==="number"||/^-?[\d \u00a0]+[.,]\d+$/.test(String(v)))num++;
      if(["Д","К","Дебет","Кредит"].includes(String(v).trim()))side++;}
    if(!ne)continue;
    sc.date.push([c,date]);sc.doc.push([c,doc]);sc.acct.push([c,acct]);sc.num.push([c,num]);sc.side.push([c,side]);
  }
  const best=a=>a.filter(x=>x[1]>0).sort((p,q)=>q[1]-p[1]).map(x=>x[0]);
  const dates=best(sc.date),docs=best(sc.doc),accts=best(sc.acct).sort((a,b)=>a-b),nums=best(sc.num).sort((a,b)=>a-b),sides=best(sc.side);
  const set=(id,v)=>{if(v!=null&&v!=="")$("#"+id).value=v;};
  if(dates.length)set("m_date",[...dates].sort((a,b)=>a-b)[0]);
  if(docs.length)set("m_doc",docs[0]);
  if(accts[0]!=null)set("m_dacc",accts[0]);
  if(accts[1]!=null)set("m_cacc",accts[1]);
  const numAfter=ac=>nums.find(n=>n===ac+1)??nums.find(n=>n>ac);
  if(accts[0]!=null)set("m_damt",numAfter(accts[0]));
  if(accts[1]!=null)set("m_camt",numAfter(accts[1]));
  if(sides.length)set("m_side",sides[0]);
  if(sides[0]!=null){const b=nums.filter(n=>n>sides[0]);if(b.length)set("m_bal",b[0]);}
  detectAccts();
}
function detectAccts(){
  const da=+$("#m_dacc").value,ca=+$("#m_cacc").value,dv=+$("#m_damt").value,cv=+$("#m_camt").value;
  const skip=+$("#hdrrow").value||0;const fC={},fD={},both={};
  for(const row of ROWS.slice(skip)){if(!row)continue;
    const dacc=String(row[da]??"").trim(),cacc=String(row[ca]??"").trim();
    if(isAcct(dacc)&&toNum(row[dv])!=null){fD[dacc]=(fD[dacc]||0)+1;both[dacc]=(both[dacc]||0)+1;}
    if(isAcct(cacc)&&toNum(row[cv])!=null){fC[cacc]=(fC[cacc]||0)+1;both[cacc]=(both[cacc]||0)+1;}}
  const cash=Object.keys(both).filter(a=>fD[a]&&fC[a]).sort((a,b)=>both[b]-both[a])[0]||Object.keys(both).sort((a,b)=>both[b]-both[a])[0];
  if(cash)$("#a_cash").value=cash;
  const topC=Object.keys(fC).filter(a=>a!==cash).sort((x,y)=>fC[y]-fC[x]);
  const topD=Object.keys(fD).filter(a=>a!==cash).sort((x,y)=>fD[y]-fD[x]);
  const g=(c,re)=>c.filter(a=>re.test(a));
  setAccts("a_dep",[...new Set(g(topC,/^57|^51/).concat(topC))].slice(0,2));
  setAccts("a_ref",g(topC,/^76|^62\.10/).length?g(topC,/^76|^62\.10/).slice(0,3):topC.slice(0,2));
  setAccts("a_sale",g(topD,/^90/).length?g(topD,/^90/).slice(0,1):topD.slice(0,1));
  setAccts("a_adv",g(topD,/^62\.4|^62\.02/).length?g(topD,/^62\.4|^62\.02/).slice(0,1):topD.slice(1,2));
  const xf=Object.keys(both).filter(a=>/^50\.1|^50\.01/.test(a));if(xf.length)setAccts("a_xfer",xf);
}

/* ---------- normalize ---------- */
function normalize(){
  const gi=id=>{const v=$("#"+id).value;return v===""?-1:+v;};
  const M={date:gi("m_date"),doc:gi("m_doc"),dacc:gi("m_dacc"),damt:gi("m_damt"),cacc:gi("m_cacc"),camt:gi("m_camt"),bal:gi("m_bal"),side:gi("m_side")};
  const cash=($("#a_cash").value||$("#a_cash").placeholder||"").trim();
  if(M.date<0||M.doc<0||M.damt<0||M.camt<0||!cash)throw new Error("Заполните обязательные поля (дата, документ, суммы, касса).");
  const skip=+$("#hdrrow").value||0;const txns=[];let cur=null,opening=0;
  for(let i=skip;i<ROWS.length;i++){
    const row=ROWS[i];if(!row)continue;
    const dateCell=row[M.date],docCell=row[M.doc];
    if(/сальдо\s*(на)?\s*начал/i.test(String(dateCell))||/сальдо\s*(на)?\s*начал/i.test(String(docCell))){
      const b=toNum(row[M.bal]);if(b!=null)opening=b;continue;}
    if(/оборот|сальдо|итог/i.test(String(dateCell))&&toNum(row[M.damt])==null&&toNum(row[M.camt])==null)continue;
    const d=toDate(dateCell);if(d)cur=d;
    const hasDoc=docCell!=null&&String(docCell).trim()!=="";
    const dAmt=toNum(row[M.damt]),cAmt=toNum(row[M.camt]);
    if(!hasDoc&&dAmt==null&&cAmt==null)continue;
    const dAcc=String(row[M.dacc]??"").trim(),cAcc=String((M.cacc>=0?row[M.cacc]:row[M.dacc])??"").trim();
    const sideRaw=M.side>=0?String(row[M.side]??"").trim():"";
    let debCash=0,credCash=0,counter=null;
    if(dAcc===cash&&dAmt!=null){debCash=dAmt;counter=String(row[M.cacc]??"").trim()||null;}
    else if(String(row[M.cacc]??"").trim()===cash&&cAmt!=null){credCash=cAmt;counter=dAcc||null;}
    else{
      if(dAmt!=null&&cAmt==null){if(/К|Кредит/i.test(sideRaw)){credCash=dAmt;counter=cAcc||null;}else{debCash=dAmt;counter=cAcc||null;}}
      else if(cAmt!=null){credCash=cAmt;counter=dAcc||null;}
      else continue;
    }
    if(debCash===0&&credCash===0)continue;
    let bal=toNum(row[M.bal]),signed=bal;
    if(bal!=null&&M.side>=0&&/К|Кредит/i.test(sideRaw))signed=-bal;
    txns.push({row:i+1,date:cur,debCash,credCash,counter,docnum:docnumOf(docCell),time:timeOf(docCell),signed});
  }
  let ut=[];
  if($("#ut_on").checked){
    const ud=gi("u_date"),ua=gi("u_amt"),uo=gi("u_to");
    if(ud>=0&&ua>=0)for(let i=skip;i<ROWS.length;i++){const row=ROWS[i];if(!row)continue;
      const a=toNum(row[ua]),d=toDate(row[ud]);if(a==null||!d)continue;
      ut.push({date:d,amt:Math.round(a*100)/100,to:uo>=0?String(row[uo]??"").trim():""});}
  }
  return {txns,ut,cash,opening};
}

/* ---------- engine ---------- */
function analyze(){
  const {txns,ut,cash,opening}=normalize();
  if(!txns.length)throw new Error("Не найдено ни одной операции по счёту "+cash+". Проверьте разметку.");
  const dep=accSet("a_dep"),ref=accSet("a_ref"),sale=accSet("a_sale"),adv=accSet("a_adv");
  const R={cash,nTx:txns.length,findings:[],opening};
  let sumD=0,sumC=0;txns.forEach(t=>{sumD+=t.debCash;sumC+=t.credCash;});
  R.sumD=sumD;R.sumC=sumC;
  const reported=txns[txns.length-1].signed;
  R.closeReported=(reported!=null)?reported:(opening+sumD-sumC);
  const expRaw=$("#expbal").value;
  if(expRaw!==""){R.expected=+expRaw;R.deviation=R.closeReported-R.expected;R.devMode="expected";}
  else{R.deviation=opening+sumD-sumC;R.devMode="zero";}

  let run=opening,mis=0;
  txns.forEach(t=>{run=Math.round((run+t.debCash-t.credCash)*100)/100;
    if(t.signed!=null&&Math.abs(run-t.signed)>0.015)mis++;});
  R.mismatch=mis;

  const neg=txns.filter(t=>t.signed!=null&&t.signed<-0.005);R.negCount=neg.length;
  let floor=Infinity;R.ratchet=[];
  txns.forEach(t=>{if(t.signed!=null&&t.signed<floor-0.005&&t.signed<0){floor=t.signed;R.ratchet.push({row:t.row,date:t.date,bal:t.signed,counter:t.counter,doc:t.docnum});}});
  R.minBal=txns.reduce((m,t)=>(t.signed!=null&&t.signed<m)?t.signed:m,Infinity);if(R.minBal===Infinity)R.minBal=null;

  const utKey=new RegExp($("#u_key").value||"ентральн","i");
  const utDep=ut.filter(u=>u.to&&utKey.test(u.to)), utRef=ut.filter(u=>u.to&&!utKey.test(u.to));
  const utCountSameDay=(d,amt)=>ut.filter(u=>dkey(u.date)===dkey(d)&&Math.abs(u.amt-amt)<0.005).length;

  const seqSpike=new Set();
  (function(){
    const ser=txns.filter(t=>t.docnum&&/^\d+$/.test(t.docnum)&&+t.docnum<1e7&&(t.credCash>0||t.debCash>0)).map(t=>({row:t.row,n:+t.docnum}));
    for(let k=0;k<ser.length;k++){const lo=Math.max(0,k-6),hi=Math.min(ser.length,k+7);
      const ne=ser.slice(lo,hi).filter((_,j)=>lo+j!==k).map(x=>x.n).sort((a,b)=>a-b);
      if(ne.length<4)continue;const med=ne[Math.floor(ne.length/2)];
      if(ser[k].n>med+2500)seqSpike.add(ser[k].row);}
  })();

  function doubles(side){
    const g={};txns.forEach(t=>{const a=t[side];if(a>0){const k=dkey(t.date)+"|"+a.toFixed(2);(g[k]=g[k]||[]).push(t);}});
    const out=[];Object.values(g).forEach(arr=>{
      if(arr.length<2)return;const accs=new Set(arr.map(x=>x.counter));if(accs.size<2)return;
      const amt=arr[0][side],odd=arr.some(x=>x.time==="23:59:59"),outseq=arr.some(x=>seqSpike.has(x.row));
      let utConfirm=null;if(ut.length){const c=utCountSameDay(arr[0].date,amt);utConfirm=(c>=1&&c<arr.length)?(arr.length-Math.max(c,1)):null;}
      out.push({date:arr[0].date,amt,rows:arr,odd,outseq,utConfirm,side});});
    return out;
  }
  function pushDouble(d,dir){
    const signals=1+(d.odd?1:0)+(d.outseq?1:0)+(d.utConfirm!=null?1:0);
    const proven=d.utConfirm!=null||(d.odd&&d.outseq);
    const amtExtra=(d.utConfirm!=null?d.utConfirm:1)*d.amt;
    R.findings.push({
      sev:proven?"proven":(signals>=2?"likely":"low"),kind:"double",dir,
      title:(dir==="cred"?"Задвоение выплаты ":"Задвоение прихода ")+fmt(d.amt),
      amount:dir==="cred"?-amtExtra:+amtExtra,date:d.date,
      rows:d.rows.map(x=>({row:x.row,counter:x.counter,doc:x.docnum,time:x.time,amt:(x.credCash||x.debCash)})),
      desc:(dir==="cred"?"Одна сумма проведена по разным корр-счетам в один день.":"Один приход проведён дважды.")+
        (d.utConfirm!=null?" В УТ за день меньше операций на эту сумму, чем в 1С — подтверждено.":
         d.odd||d.outseq?" Доп. признак: метка 23:59:59 / номер вне очереди.":" Доп. признаков нет — возможно, два разных документа на одну сумму.")
    });
  }
  doubles("credCash").forEach(d=>pushDouble(d,"cred"));
  doubles("debCash").forEach(d=>pushDouble(d,"deb"));

  const byDoc={};txns.forEach(t=>{if(t.docnum){(byDoc[t.docnum]=byDoc[t.docnum]||[]).push(t);}});
  Object.entries(byDoc).forEach(([dn,arr])=>{if(arr.length>1)R.findings.push({sev:"proven",kind:"dupdoc",title:"Дубль номера документа "+dn,amount:null,
    rows:arr.map(x=>({row:x.row,counter:x.counter,doc:dn,time:x.time,amt:(x.credCash||x.debCash)})),
    desc:"Один и тот же номер документа встречается несколько раз — прямой дубль проведения."});});

  if(ut.length){
    const accRef=txns.filter(t=>t.credCash>0&&ref.has(t.counter)).sort((a,b)=>a.date-b.date||a.row-b.row);
    const u=utRef.map(x=>({...x,used:false})).sort((a,b)=>a.date-b.date);let over=0;
    accRef.forEach(a=>{const hit=u.find(x=>!x.used&&Math.abs(x.amt-Math.round(a.credCash*100)/100)<0.005&&Math.abs((x.date-a.date)/864e5)<=10);
      if(hit)hit.used=true;else over+=a.credCash;});
    const under=u.filter(x=>!x.used).reduce((s,x)=>s+x.amt,0);
    R.utRef={net:Math.round((over-under)*100)/100,accTotal:Math.round(accRef.reduce((s,a)=>s+a.credCash,0)*100)/100,utTotal:Math.round(utRef.reduce((s,a)=>s+a.amt,0)*100)/100};
    const depAcc=txns.filter(t=>t.credCash>0&&dep.has(t.counter)).reduce((s,t)=>s+t.credCash,0);
    R.utDep={accTotal:Math.round(depAcc*100)/100,utTotal:Math.round(utDep.reduce((s,a)=>s+a.amt,0)*100)/100};
    R.utDep.net=Math.round((R.utDep.accTotal-R.utDep.utTotal)*100)/100;
  }

  const provenSigned=R.findings.filter(f=>f.sev==="proven"&&f.amount!=null).reduce((s,f)=>s+f.amount,0);
  R.provenSigned=Math.round(provenSigned*100)/100;
  R.residual=Math.round((R.deviation-provenSigned)*100)/100;
  const rank={proven:0,likely:1,low:2,zone:3,fact:4};
  R.findings.sort((a,b)=>rank[a.sev]-rank[b.sev]||Math.abs(b.amount||0)-Math.abs(a.amount||0));
  return R;
}

/* ---------- render ---------- */
function renderReport(R){
  const dev=R.deviation,sign=dev<-0.005?"neg":dev>0.005?"pos":"zero";
  const lampC=sign==="neg"?"#E8857A":sign==="pos"?"#E6C062":"#A6C04A";
  let verdict;
  if(R.devMode==="zero"&&sign==="neg")verdict="Касса закрывается в минусе — отрицательной наличности быть не может, это ошибка ввода (расходов проведено больше, чем прихода).";
  else if(R.devMode==="zero"&&sign==="pos")verdict="Оборот даёт положительный остаток. Если по факту в кассе меньше — задайте фактический остаток в «Настройки и разметка», чтобы посчитать отклонение со знаком.";
  else if(R.devMode==="expected"&&sign==="neg")verdict="Книга показывает МЕНЬШЕ эталона — недостача в учёте (завышен расход или занижен приход).";
  else if(R.devMode==="expected"&&sign==="pos")verdict="Книга показывает БОЛЬШЕ эталона — излишек в учёте (занижен расход или задвоен приход).";
  else verdict="Оборот сходится с эталоном: явного отклонения нет. Проверьте находки ниже как профилактику.";

  const cards=[];
  R.findings.forEach(f=>{
    const sevLbl={proven:"Доказано",likely:"Вероятно",low:"Под вопросом",zone:"Зона проверки",fact:"Факт"}[f.sev];
    const sevCls={proven:"proven",likely:"likely",low:"zone",zone:"zone",fact:"fact"}[f.sev];
    let rowsHtml="";
    if(f.rows&&f.rows.length)rowsHtml="<details><summary>строки в файле ("+f.rows.length+")</summary><table class='minitable'><tr><th>R#</th><th>Корр-счёт</th><th>Документ</th><th>Время</th><th class='r'>Сумма</th></tr>"+
      f.rows.map(r=>"<tr><td>"+r.row+"</td><td>"+(r.counter||"")+"</td><td>"+(r.doc||"")+"</td><td>"+(r.time||"")+"</td><td class='r'>"+fmt(r.amt)+"</td></tr>").join("")+"</table></details>";
    const amtHtml=f.amount!=null?`<div class="amt ${f.amount<0?"neg":"pos"}">${f.amount<0?"−":"+"}${fmt(Math.abs(f.amount))}</div>`:"";
    cards.push(`<div class="card ${sevCls}"><div class="ch"><span class="ct">${f.title}</span><span class="sev ${sevCls}">${sevLbl}</span></div>${amtHtml}<div class="desc">${f.desc||""}${f.date?` <span class="muted">· ${dru(f.date)}</span>`:""}</div>${rowsHtml}</div>`);
  });

  const factCard=`<div class="card fact span2"><div class="ch"><span class="ct">Контроль и арифметика</span><span class="sev fact">Факт</span></div>
    <table class="minitable">
      <tr><th>Показатель</th><th class="r">Значение</th></tr>
      <tr><td>Приход по кассе (${R.cash})</td><td class="r">${fmt(R.sumD)}</td></tr>
      <tr><td>Расход по кассе</td><td class="r">${fmt(R.sumC)}</td></tr>
      <tr><td><b>Отклонение${R.devMode==="expected"?" (книга − эталон)":" (приход − расход)"}</b></td><td class="r tred"><b>${dev<0?"−":"+"}${fmt(Math.abs(dev))}</b></td></tr>
      <tr><td>Операций обработано</td><td class="r">${R.nTx}</td></tr>
      <tr><td>Несходимостей остатка (книга vs пересчёт)</td><td class="r">${R.mismatch===0?"нет (0)":R.mismatch}</td></tr>
      <tr><td>Минимальный остаток за период</td><td class="r ${R.minBal!=null&&R.minBal<0?"tred":""}">${R.minBal!=null?fmt(R.minBal):"—"}</td></tr>
    </table>
    <div class="desc">${R.mismatch===0?"Остаток в файле согласован с пересчётом — искажены проводки, а не сам остаток.":"Есть строки, где остаток не равен пересчёту — проверьте их первыми (возможна правка задним числом)."}</div></div>`;

  let utCard="";
  if(R.utRef)utCard=`<div class="card fact span2"><div class="ch"><span class="ct">Сверка с УТ</span><span class="sev fact">Факт</span></div>
    <table class="minitable"><tr><th>Категория</th><th class="r">1С</th><th class="r">УТ</th><th class="r">Нетто (1С−УТ)</th></tr>
    <tr><td>Возвраты</td><td class="r">${fmt(R.utRef.accTotal)}</td><td class="r">${fmt(R.utRef.utTotal)}</td><td class="r ${R.utRef.net>0?"tred":""}">${R.utRef.net<0?"−":"+"}${fmt(Math.abs(R.utRef.net))}</td></tr>
    <tr><td>Инкассация</td><td class="r">${fmt(R.utDep.accTotal)}</td><td class="r">${fmt(R.utDep.utTotal)}</td><td class="r">${R.utDep.net<0?"−":"+"}${fmt(Math.abs(R.utDep.net))}</td></tr></table>
    <div class="desc">Положительное нетто по возвратам = 1С завысил расход. По инкассации большой зазор обычно методический (пачки vs ежедневно) — не торопитесь считать ошибкой.</div></div>`;

  let residCard="";
  if(Math.abs(R.residual)>0.02)residCard=`<div class="card zone span2"><div class="ch"><span class="ct">Остаток ${fmt(R.residual)} — не атрибутируется автоматически</span><span class="sev zone">Зона проверки</span></div>
    <div class="desc">Доказанные находки объясняют ${fmt(R.provenSigned)} из ${dev<0?"−":"+"}${fmt(Math.abs(dev))}. Остаток по этим данным к конкретным документам однозначно не привязывается${R.utRef?"":" (нет блока УТ для сверки оттоков)"}. Где обычно прячется: продажи (нет независимого источника), инкассация (пачки, методический зазор с УТ). Поднимите: выписку банка по инкассации, Z-отчёты/фискальные данные по продажам, журнал РКО/ПКО со статусами.</div></div>`;
  else if(R.findings.some(f=>f.sev==="proven"))residCard=`<div class="card fact span2"><div class="ch"><span class="ct">Отклонение объяснено полностью</span><span class="sev fact">Факт</span></div><div class="desc">Сумма доказанных находок (${fmt(R.provenSigned)}) совпадает с отклонением. Достаточно исправить документы выше.</div></div>`;

  let trajCard="";
  if(R.ratchet.length)trajCard=`<div class="card span2"><div class="ch"><span class="ct">Когда остаток уходил за грань (${R.negCount} точек)</span><span class="sev zone">Хронология</span></div>
    <table class="minitable"><tr><th>R#</th><th>Дата</th><th class="r">Остаток</th><th>Корр-счёт</th><th>Документ</th></tr>
    ${R.ratchet.map(r=>`<tr><td>${r.row}</td><td>${dru(r.date)}</td><td class="r tred">${fmt(r.bal)}</td><td>${r.counter||""}</td><td>${r.doc||""}</td></tr>`).join("")}</table>
    <div class="desc">Моменты, где «дно» опускалось ниже прежнего — каждая ступень = накопленный к этой дате недобор.</div></div>`;

  $("#results").innerHTML=`
    <div class="readout reveal"><div class="scan"></div>
      <div class="lbl">Отклонение остатка · касса ${R.cash}</div>
      <div class="figure fig-${sign}"><span class="lamp" style="color:${lampC}"></span><span>${dev<0?"−":dev>0?"+":""}${fmt(Math.abs(dev))}</span><span class="ccy">BYN</span></div>
      <div class="verdict">${verdict}</div></div>
    <div class="sec-h">Находки · отсортированы по достоверности</div>
    <div class="bento">${cards.join("")}${factCard}${utCard}${residCard}${trajCard}</div>
    <div class="btnrow"><button class="btn" id="xlsx">Скачать Excel-отчёт</button><button class="btn ghost" id="prnt">Печать / PDF</button></div>`;
  $("#xlsx").onclick=()=>buildExcel(R);
  $("#prnt").onclick=()=>window.print();
  $("#results").scrollIntoView({behavior:"smooth",block:"start"});
}

/* ---------- excel export ---------- */
function buildExcel(R){
  const wb=XLSX.utils.book_new();const dev=R.deviation;
  const s1=[["Касса "+R.cash+" — анализ отклонения"],[],
    ["Отклонение остатка",Math.round(dev*100)/100],
    ["Режим",R.devMode==="expected"?"книга − эталон":"приход − расход (норма 0)"],
    ["Приход по кассе",Math.round(R.sumD*100)/100],["Расход по кассе",Math.round(R.sumC*100)/100],
    ["Операций",R.nTx],["Несходимостей остатка",R.mismatch],["Минимальный остаток",R.minBal],
    [],["Доказанные находки объясняют",R.provenSigned],["Остаток (не атрибутирован)",R.residual]];
  XLSX.utils.book_append_sheet(wb,aoa(s1,[34,16]),"Диагноз");
  const fh=[["Тип","Достоверность","Сумма (со знаком)","Дата","Документы (R#)","Пояснение"]];
  R.findings.forEach(f=>{const sev={proven:"Доказано",likely:"Вероятно",low:"Под вопросом",zone:"Зона",fact:"Факт"}[f.sev];
    fh.push([f.title,sev,f.amount!=null?Math.round(f.amount*100)/100:"",f.date?dru(f.date):"",(f.rows||[]).map(r=>"R"+r.row+(r.counter?"/"+r.counter:"")+(r.doc?"/"+r.doc:"")).join("; "),f.desc||""]);});
  XLSX.utils.book_append_sheet(wb,aoa(fh,[34,13,18,12,40,60]),"Найденные ошибки");
  if(R.ratchet.length){const t=[["R#","Дата","Остаток","Корр-счёт","Документ"]];
    R.ratchet.forEach(r=>t.push([r.row,dru(r.date),Math.round(r.bal*100)/100,r.counter||"",r.doc||""]));
    XLSX.utils.book_append_sheet(wb,aoa(t,[8,13,13,12,28]),"Уход за грань");}
  if(R.utRef){const t=[["Категория","1С","УТ","Нетто (1С−УТ)"],["Возвраты",R.utRef.accTotal,R.utRef.utTotal,R.utRef.net],["Инкассация",R.utDep.accTotal,R.utDep.utTotal,R.utDep.net]];
    XLSX.utils.book_append_sheet(wb,aoa(t,[16,14,14,16]),"Сверка УТ");}
  XLSX.writeFile(wb,"Касса_"+R.cash+"_отклонение.xlsx");
}
function aoa(rows,w){const ws=XLSX.utils.aoa_to_sheet(rows);if(w)ws["!cols"]=w.map(x=>({wch:x}));return ws;}

/* ---------- run + wiring ---------- */
function runAnalysis(){$("#maperr").innerHTML="";try{renderReport(analyze());}catch(err){$("#maperr").innerHTML="<div class='err'>"+err.message+"</div>";$("#results").innerHTML="";}}
const drop=$("#drop"),file=$("#file");
drop.onclick=()=>file.click();
drop.onkeydown=e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();file.click();}};
["dragenter","dragover"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add("drag");}));
["dragleave","drop"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove("drag");}));
drop.addEventListener("drop",e=>{if(e.dataTransfer.files[0])handleFile(e.dataTransfer.files[0]);});
file.onchange=e=>{if(e.target.files[0])handleFile(e.target.files[0]);};
$("#sheetsel").onchange=loadSheet;
$("#hdrrow").oninput=()=>{renderPreview();buildColSelects();};
$("#ut_on").onchange=e=>$("#utfields").classList.toggle("hidden",!e.target.checked);
["m_dacc","m_cacc","m_damt","m_camt"].forEach(id=>$("#"+id).addEventListener("change",detectAccts));
$("#recalc").onclick=runAnalysis;
$("#reset").onclick=()=>location.reload();
</script>
</body>
</html>
