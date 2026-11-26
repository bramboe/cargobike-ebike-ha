"""Ingress dashboard; all untrusted values must be escaped or textContent."""
from insight_ui import INSIGHTS_CSS, INSIGHTS_HTML, INSIGHTS_SCRIPT

INDEX_HTML = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'><title>Bosch Kiox eBike</title>
<style>
:root{--bg:#f2f3f5;--card:#fff;--soft:#eef1f4;--ink:#212121;--mut:#727272;--line:#e0e0e0;--acc:#03a9f4;--chip:#e9eaee}
@media(prefers-color-scheme:dark){:root{--bg:#111;--card:#1c1c1c;--soft:#262626;--ink:#e1e1e1;--mut:#9b9b9b;--line:#3a3a3a;--acc:#03a9f4;--chip:#2a2a2a}}
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,sans-serif;margin:0;background:var(--bg);color:var(--ink);line-height:1.45}
.wrap{max-width:none;margin:0 auto;padding:22px 22px 48px}
.tabs{display:flex;gap:8px;margin:2px 0 22px;max-width:520px}
.tab{flex:1;background:var(--chip);color:var(--mut);border:0;border-radius:12px;padding:12px;font-size:14px;font-weight:600;cursor:pointer}
.tab.on{background:var(--acc);color:#fff}
.dash{display:grid;gap:16px;grid-template-columns:1fr}
.dash>*{min-width:0}
.htitle{overflow-wrap:anywhere}
@media(min-width:720px){.dash{grid-template-columns:1.55fr 1fr;align-items:start}
 .col-wide{grid-column:1}.col-rail{grid-column:2;grid-row:1 / span 6}}
.rail{display:flex;flex-direction:column;gap:16px}
.card{background:var(--card);border-radius:12px;padding:20px;border:1px solid var(--line);box-shadow:0 1px 2px rgba(0,0,0,.04)}
.set .card{margin-bottom:18px}
.hero{text-align:center;padding:30px 24px 26px}
.htitle{font-size:21px;font-weight:800;letter-spacing:-.01em}
.badge{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.06em;padding:6px 15px;border-radius:20px;background:var(--chip);color:var(--mut);margin-top:14px;text-transform:uppercase}
.badge.on{background:rgba(67,160,71,.18);color:#43a047}
.sub{color:var(--mut);font-size:12.5px;margin-top:9px}
.reqlink{display:inline-block;margin:14px 0 18px;font-size:12px;color:var(--mut);text-decoration:none;border:1px solid var(--line);padding:6px 13px;border-radius:18px}
.reqlink:hover{color:var(--acc);border-color:var(--acc)}
.bikewrap{background:#eef1f3;border-radius:12px;margin:16px 0 12px;padding:16px}
.bike{display:block;margin:0 auto;width:100%;max-width:360px;max-height:230px;object-fit:contain}
.hstats{display:flex;justify-content:center;align-items:center;gap:18px 30px;flex-wrap:wrap;margin:12px 0 2px}
.hstat{display:flex;align-items:center;gap:10px}
.hlbl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.05em;margin-top:3px}
.hstats .vr{width:1px;height:42px;background:var(--line)}
@media(max-width:520px){.hstats .vr{display:none}.hero{padding:26px 16px 20px}.htitle{font-size:19px}.pct{font-size:28px}.pct small{font-size:15px}.range{font-size:24px}.range small{font-size:13px}}
.biketile{display:flex;align-items:center;gap:14px;padding:12px 14px;border:1px solid var(--line);border-radius:12px;margin-top:10px}
.biketile.match{border-color:#43a047;background:rgba(67,160,71,.07)}
.btimg{width:66px;height:auto;flex:0 0 auto}
.btinfo{flex:1;min-width:0}
.btadd{flex:0 0 auto;padding:9px 16px;font-size:14px}
.segs{display:flex;gap:4px;align-items:flex-end;height:30px}
.segs i{width:8px;border-radius:3px;display:block}
.segs i:nth-child(1){height:13px}.segs i:nth-child(2){height:17px}.segs i:nth-child(3){height:21px}
.segs i:nth-child(4){height:26px}.segs i:nth-child(5){height:30px}
.pct{font-size:34px;font-weight:800;line-height:1}.pct small{font-size:17px;font-weight:600;color:var(--mut)}
.range{font-size:30px;font-weight:800}.range small{font-size:15px;color:var(--mut);font-weight:600}
.lbl{font-size:11px;letter-spacing:.08em;color:var(--mut);text-transform:uppercase;font-weight:700;margin-bottom:12px}
.big{font-size:28px;font-weight:800;line-height:1.1}
.g4{display:flex;justify-content:space-between;gap:12px;margin-top:4px}
.g4 div{flex:1}
.g4 .m{font-size:12px;font-weight:800;letter-spacing:.03em}.g4 .v{font-size:19px;font-weight:700;margin-top:7px}.g4 .v small{font-size:11px;color:var(--mut)}
.cbar{display:flex;height:10px;border-radius:6px;overflow:hidden;margin-top:20px;background:var(--line)}
.cbar i{display:block;height:100%}
.between{display:flex;justify-content:space-between;align-items:center}
.pill{font-size:13px;font-weight:700;padding:6px 14px;border-radius:20px}
button{background:var(--acc);color:#fff;border:0;border-radius:12px;padding:11px 16px;font-size:14px;cursor:pointer;margin:6px 8px 0 0}
button.sec{background:var(--chip);color:var(--ink)}button:disabled{opacity:.5;cursor:default}
.armbtns{margin-top:16px}.armbtns button{padding:10px 15px}
.warn{margin-top:12px;font-size:11.5px;color:var(--mut);line-height:1.45}
.tech{display:grid;grid-template-columns:auto 1fr;gap:9px 18px;font-size:13.5px;margin:0}
.tech dt{color:var(--mut)}.tech dd{margin:0;text-align:right;font-weight:600;word-break:break-all}
.th{font-size:11px;letter-spacing:.06em;color:var(--mut);text-transform:uppercase;font-weight:700;margin:16px 0 9px}
.th:first-child{margin-top:2px}
.legal{margin:26px 4px 8px;font-size:11px;line-height:1.5;color:var(--mut);text-align:center;opacity:.85}
.devbar{margin:0 0 18px;padding:12px 15px;border-radius:12px;border:1px solid #e0a800;background:rgba(255,193,7,.14);color:#8a6d00;font-size:13px;line-height:1.45}
@media(prefers-color-scheme:dark){.devbar{color:#e8c25a}}
.row{display:flex;align-items:center;gap:10px;padding:14px;border:1px solid var(--line);border-radius:12px;margin:8px 0;cursor:pointer}
.row.sel{border-color:var(--acc);background:rgba(3,169,244,.12)}
.muted{color:var(--mut);font-size:13px}.ok{color:#43a047;font-weight:700}.bad{color:#e53935;font-weight:700}
.hidden{display:none}h2{font-size:17px;margin:0 0 10px}.set p{margin:6px 0 14px}
.src{font-size:11px;margin-left:6px;opacity:.7;vertical-align:middle;cursor:help}
#cloudMap .leaflet-control-attribution{font-size:9px}
#cloudMap.fs{position:fixed!important;inset:0!important;width:100%!important;height:100%!important;z-index:99999;border-radius:0;margin:0}
.leaflet-bar a.fsbtn{display:flex;align-items:center;justify-content:center;color:#333}
.srow{border:1px solid var(--line);border-radius:12px;padding:12px;margin:8px 0}
.srow.off{opacity:.55}
.shead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.shead .snm{font-weight:700;flex:1;min-width:120px}
.sbadge{font-size:12px;font-weight:700;padding:3px 9px;border-radius:20px;background:var(--chip)}
.sopts{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:10px;font-size:13px}
.sopts label{display:flex;align-items:center;gap:6px}
.sopts select,.sopts input[type=number]{padding:6px 8px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:13px}
.epick{width:100%;max-width:520px;padding:9px;border-radius:10px;border:1px solid var(--line);background:var(--card);color:var(--ink);margin-top:8px}
.switch{position:relative;width:42px;height:24px;flex:0 0 auto}
.switch input{opacity:0;width:0;height:0}
.switch .sl{position:absolute;inset:0;background:var(--chip);border-radius:24px;transition:.2s;cursor:pointer}
.switch .sl:before{content:"";position:absolute;height:18px;width:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.switch input:checked+.sl{background:var(--acc)}
.switch input:checked+.sl:before{transform:translateX(18px)}
</style>
<link rel=stylesheet href="leaflet.css">
<script src="leaflet.js"></script>
</head><body><div class=wrap>
<div class=tabs>
  <button class='tab on' id=tabDash data-i18n=tab_dash onclick="tab('dash')">Dashboard</button>
  <button class=tab id=tabMore data-i18n=tab_more onclick="tab('more')">Meer info</button>
  <button class=tab id=tabSet data-i18n=tab_set onclick="tab('set')">Instellingen</button>
</div>
<div class=devbar id=devBar data-i18n=devmode style="display:none"></div>
<div class="card hidden" id=onboard style="padding:28px 24px">
  <div class=htitle data-i18n=ob_title style="text-align:center">Voeg je fiets toe</div>
  <div class=sub data-i18n=ob_body style="text-align:center;margin-top:6px">Zet het display van de fiets aan (en zet 'm in koppelmodus) — dan verschijnt 'ie hieronder.</div>
  <div id=obFound style="margin-top:18px"></div>
  <div style="text-align:center;margin-top:12px"><button class=sec data-i18n=ob_scan onclick="scan('bike','#obFound')">Zoek fiets</button></div>
</div>

<section id=dash class=dash>
  <div class='card hero col-wide'>
    <div class=htitle id=bikeTitle>Bosch eBike</div>
    <div class=sub id=bikeSpec></div>
    <span class=badge id=conn>—</span>
    <span class=badge id=cloudMatch style="display:none"></span>
    <div class=hstats>
      <div class=hstat><div class=segs id=segs></div><div class=pct id=pct>—<small>%</small></div><span class=src title=Bluetooth>📶</span></div>
      <div class=vr></div>
      <div><div class=range id=range>—<small> km</small></div><div class=hlbl data-i18n=ranges_short>bereik</div></div>
    </div>
    <div class=bikewrap>
      <img class=bike src="bike.png" alt="Urban Arrow Family" />
    </div>
    <a class=reqlink id=reqPhoto data-i18n=request_photo target=_blank rel=noopener
       href="https://github.com/bramboe/cargobike-ebike-ha/issues/new?title=Bike%20photo%20request&labels=bike-image&body=Model%20(Family%2FTender%2FCargo%2FFlatbed)%3A%20%0AType%2Fversion%20(e.g.%20Advanced%20Next)%3A%20%0AColour%3A%20%0AProduct%20photo%20URL%20(transparent%20PNG%20if%20possible)%3A%20">Andere fiets? Vraag je model aan</a>
  </div>

  <div class='rail col-rail'>
    <div class=card><div class=lbl><span data-i18n=mode>Rijmodus</span><span class=src title=Bluetooth>📶</span></div><div class=between><div class=big id=mode>—</div><span class=pill id=modePill></span></div></div>
    <div class=card id=maintenanceCard><div class=lbl><span data-i18n=maint>Onderhoud</span></div><div class=service-notice id=serviceNotice></div><div class=big id=service>—</div><div class=sub data-i18n=maint_sub>tot de volgende servicebeurt</div><div class=sub id=serviceForecast></div><button type=button class=sec onclick="openInsights('maintenance')" id=planningOpen>Bekijk planning</button></div>
    <div class=card><div class=lbl><span data-i18n=security>Beveiliging</span><span class=src title=Bluetooth>📶</span></div><div id=secLine class=big>—</div>
      <div class=armbtns id=armBox></div><div class=warn id=secWarn></div>
      <div class=sub id=lockLine style="margin-top:14px;font-size:14px"></div></div>
    <div class=card><div class=lbl data-i18n=gps>GPS-module &amp; locatie</div>
      <div class=between><div class=big id=gpsBatt>—</div><span class=pill id=gpsConn></span></div>
      <div class=sub id=gpsUpd></div>
      <div class=sub id=mainBatt style="margin-top:6px"></div>
      <div id=cloudSub style="display:none;margin-top:14px;border-top:1px solid var(--line);padding-top:14px">
        <div class=between><div class=big id=cloudState style="font-size:22px">—</div><span class=pill id=cloudSpeed></span></div>
        <div class=between style="margin-top:10px;font-size:14px"><span class=muted><span data-i18n=cloud_home>Afstand tot huis</span><span class=src title=Cloud>☁️</span></span><b id=cloudHome>—</b></div>
        <div id=cloudMap style="display:none;height:200px;border-radius:10px;margin-top:10px;overflow:hidden"></div>
        <div class=sub id=cloudUpd style="margin-top:8px"></div></div>
      <div style="margin-top:14px"><button class=sec id=trkBtn data-i18n=refresh_module onclick="refreshTracker()">Module-accu verversen</button></div></div>
  </div>

  <div class='card col-wide'><div class=lbl><span data-i18n=ranges>Geschat bereik per stand</span><span class=src title=Bluetooth>📶</span></div>
    <div class=g4 id=ranges></div><div class=cbar id=rangeBar></div></div>

  <div class='card col-wide'><div class=lbl><span data-i18n=mileage>Kilometerstand</span><span class=src title=Bluetooth>📶</span></div><div class=big id=odo>—</div></div>

<!-- INSIGHT_PANELS -->
  <div class='card col-wide' id=boschCard style="display:none"><div class=lbl><span data-i18n=bosch_h>Accu &amp; service</span><span class=src title="Bosch cloud">☁️</span></div>
    <div class=g4 id=boschStats></div><div class=sub id=boschUpd style="margin-top:8px"></div></div>

  <div class='card col-wide' id=actCard style="display:none"><div class=lbl><span data-i18n=activities>Activiteiten</span><span class=src title=Cloud>☁️</span></div>
    <div id=actList></div></div>

  <div class='col-wide muted' style="font-size:12px;text-align:center">📶 Bluetooth · ☁️ Cloud</div>
</section>

<section id=more class='set hidden'>
  <div class=card><div class=lbl data-i18n=tech>Technische info</div>
    <div id=techInfo></div></div>
  <div class=card><div class=lbl data-i18n=components>Componenten</div>
    <div id=compInfo></div></div>
  <div class=card><div class=lbl data-i18n=cloud_accounts>Cloud-accounts</div>
    <div id=cloudAcc></div>
    <div class=sub data-i18n=acc_hint style="margin-top:8px"></div></div>
  <div class=card><div class=lbl data-i18n=about>Over deze add-on</div>
    <p class=muted data-i18n=about_p></p>
    <p><a id=repoLink href="https://github.com/bramboe/cargobike-ebike-ha" target=_blank rel=noopener data-i18n=about_repo>Broncode op GitHub</a></p>
    <div class=legal data-i18n=legal></div></div>
</section>

<section id=set class='set hidden'>
  <div class=card><h2 id=displayHeading></h2><label class=maintenance-toggle><input type=checkbox id=showMaintenance checked onchange='saveMaintenancePreference(this)'> <span id=showMaintenanceLabel></span></label><p class=sub id=maintenanceSettingHint></p><p class=sub id=maintenanceSaveStatus role=status></p></div>
  <div class=card>
    <h2 data-i18n=su_bike_h>1. Fiets</h2>
    <!-- Added-bike tile (shown once a bike is added) -->
    <div id=addedBike class=hidden>
      <div class="biketile match">
        <img src=bike.png class=btimg>
        <div class=btinfo>
          <b id=addedName style="display:block">—</b>
          <div class=muted id=addedMac style="font-size:12px"></div>
          <div id=addedConn style="font-size:12px;margin-top:2px"></div>
        </div>
        <button class=sec id=removeBtn onclick="removeBike()" data-i18n=remove_bike>Verwijderen</button>
      </div>
      <div id=pairArea class=hidden style="margin-top:10px">
        <p class=muted style="font-size:13px" data-i18n=su_pair_p>Zet de fiets in koppelmodus (display → nieuw apparaat), klik dan:</p>
        <button id=pairBtn data-i18n=pair_btn onclick="pair()">Koppel (pair)</button><span id=pairMsg></span></div>
      <span id=removeMsg class=muted></span>
      <p class=muted style="font-size:12px;margin-top:12px"><a href=# id=replaceLink onclick="showScan();return false" data-i18n=replace_bike>Andere fiets koppelen</a></p>
    </div>
    <!-- Add flow (scan → tiles with an add button) -->
    <div id=addFlow>
      <p class=muted data-i18n=su_bike_p>Zet het display van de fiets aan en zoek 'm.</p>
      <p class=muted data-i18n=acc_hint style="font-size:12px"></p>
      <button data-i18n=scan_bikes onclick="scan('bike','#bikes')">Zoek fietsen</button><div id=bikes></div>
    </div>
  </div>
  <div class=card>
    <h2 data-i18n=su_tracker_h>2. GPS-tracker (anti-diefstal, optioneel)</h2>
    <p class=muted data-i18n=su_tracker_p>De tracker is altijd aan. Scan en kies 'm, of sla over.</p>
    <button data-i18n=scan_trackers onclick="scan('tracker')">Scan trackers</button>
    <button class=sec data-i18n=skip onclick="skipTracker()">Overslaan / uit</button><div id=trackers></div>
    <div id=trackerActions class=hidden><button data-i18n=select_tracker onclick="selectTracker()">Selecteer deze tracker</button></div>
  </div>
  <div class=card>
    <h2 data-i18n=su_alarm_h>3. Alarm (optioneel — vereist de tracker)</h2>
    <p class=muted data-i18n=su_alarm_p>Afwezig = hard (push + lampen), Thuis = stil (alleen melding). Uit = alleen de bewegingssensor.</p>
    <button id=alarmBtn onclick="toggleAlarm()">…</button> <span id=alarmState class=muted></span>
  </div>
  <div class=card id=sensCard>
    <h2 data-i18n=sens_h>Sensoren</h2>
    <p class=muted data-i18n=sens_p>Elke bron die beweging/diefstal kan melden — de ingebouwde fietssensoren én je eigen HA-sensoren — staat hier als een rij die je apart aan/uit zet, met dezelfde opties.</p>
    <div id=sensList></div>
    <div style="margin-top:10px"><button class=sec id=sensAddBtn onclick="addExtSensor()" data-i18n=sens_add>+ Sensor toevoegen</button></div>
    <div id=sensDelays style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px"></div>
    <div style="margin-top:12px"><button id=sensSaveBtn onclick="saveSensors()" data-i18n=ext_save>Opslaan</button> <span id=sensMsg class=muted></span></div>
  </div>
</section>
</div>
<script>
const $=s=>document.querySelector(s);
// HTML-escape anything that isn't ours (BLE names, HA entity names, cloud fields)
// before it goes into innerHTML: this page runs inside Home Assistant's origin.
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api=async(p,o)=>(await fetch(p,o)).json();
const post=(p,b)=>api(p,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b||{})});
const LANG=(navigator.language||'en').toLowerCase().startsWith('nl')?'nl':'en';
const T={nl:{tab_dash:'Dashboard',tab_more:'Meer info',tab_set:'Instellingen',components:'Componenten',about:'Over deze add-on',about_p:'Leest je Bosch Smart System eBike (Kiox) via Bluetooth uit en publiceert batterij, bereik, modus, km-stand, beurt, beweging/alarm en tracker naar Home Assistant.',about_repo:'Broncode op GitHub',c_drive:'Aandrijving',c_batt:'Accu',c_disp:'Display',c_hub:'Hub',mode:'Rijmodus',maint:'Onderhoud',maint_sub:'tot de volgende servicebeurt',security:'Beveiliging',ranges:'Geschat bereik per stand',mileage:'Kilometerstand',tech:'Technische info',tech_kiox:'Kiox (Bosch-hub)',tech_gps:'GPS-module',t_model:'Model',t_frame:'Framenummer',devmode:'🛠️ Beweegtest staat AAN — bewaking en uitlezen pauzeren. Zet Beweegtest (ontwikkelaar) uit in de configuratie als je klaar bent.',gps:'GPS-module & locatie',gps_conn:'verbonden',in_range:'in bereik',out_range:'buiten bereik',ob_title:'Voeg je fiets toe',ob_body:"Zet het display van de fiets aan (en in koppelmodus) — dan verschijnt 'ie hieronder.",ob_scan:'Zoek fiets',add_bike:'Toevoegen',adding:'Toevoegen…',replace_bike:'Andere fiets koppelen',ob_btn:'Naar Instellingen',remove_bike:'Verwijder fiets',remove_confirm_btn:'Bevestig verwijderen',remove_confirm:'⚠️ Weet je het zeker? Klik nogmaals om te wissen.',removed_ok:'Verwijderd ✓',lk_on:'🔒 Vergrendeld',lk_off:'🔓 Ontgrendeld',refresh_module:'Module-accu verversen',refreshing:'verversen…',t_pname:'Productnaam',t_color:'Kleur',t_part:'Onderdeelnummer',t_sku:'Artikelcode',t_pcode:'Productcode',t_hubfw:'Firmware',t_modfw:'Firmware',t_addr:'Bluetooth-adres',t_mac:'MAC-adres',t_mfr:'Fabrikant',t_hw:'Hardware',t_batt:'Module-accu',t_gps:'GPS-coördinaten',legal:'Onofficiële, door de community gemaakte integratie. Niet gelieerd aan, goedgekeurd of ondersteund door Bosch eBike Systems of Urban Arrow. Gebruik volledig op eigen risico, zonder enige garantie. Alle merknamen zijn eigendom van hun respectievelijke eigenaren.',su_bike_h:'1. Fiets',su_bike_p:"Zet het display van de fiets aan en zoek 'm.",scan_bikes:'Scan fietsen',select_bike:'Selecteer deze fiets',su_pair_p:'Zet de fiets in pairing mode (display → nieuw apparaat koppelen), klik dan:',pair_btn:'Koppel (pair)',su_tracker_h:'2. GPS-tracker (anti-diefstal, optioneel)',su_tracker_p:"De tracker is altijd aan. Scan en kies 'm, of sla over.",scan_trackers:'Scan trackers',skip:'Overslaan / uit',select_tracker:'Selecteer deze tracker',su_alarm_h:'3. Alarm (optioneel — vereist de tracker)',su_alarm_p:'Afwezig = hard (push + lampen), Thuis = stil (alleen melding). Uit = alleen de bewegingssensor.',conn_on:'Verbonden',conn_off:'Niet verbonden',no_reading:'nog geen meting',up_now:'zojuist bijgewerkt',up_min:'bijgewerkt {n} min geleden',up_hour:'bijgewerkt {n} uur geleden',up_day:'bijgewerkt {n} d geleden',motion_y:'beweging',motion_n:'rustig',alarm_off:'Alarm uit',s_disarmed:'Uit',s_home:'Stil',s_away:'Vol alarm',s_trig:'⚠️ GEACTIVEERD',a_off:'Uit',a_home:'Stil',a_away:'Vol alarm',alarm_off_hint:'Alarm staat uit (zie Instellingen)',alarm_enable:'Alarm inschakelen',alarm_disable:'Alarm uitschakelen',now_off:'momenteel uit',now_on:'momenteel aan',scanning:'scannen… (±8s)',nothing:'niets gevonden — staat het apparaat aan/in bereik?',pairing:'koppelen…',paired_ok:'Gekoppeld ✓',paired_fail:'Mislukt — staat de fiets in pairing mode?',request_photo:'Andere fiets? Vraag je kleur/model aan',sec_passive:'🛡️ Passieve bewaking: de add-on luistert alleen naar de GPS-module (geen verbinding, geen extra accuverbruik). Staat het alarm scherp, dan luistert hij vrijwel continu en gaat het alarm af zodra de module {n} s niet meer gehoord wordt. Zegt de GPS dat de fiets weg is, dan pauzeert het luisteren tot hij weer thuis is.',ext_h:'Externe bewegingssensor (op de fiets)',ext_p:'Kies een eigen Home Assistant-sensor (contact-, trillings- of bewegingssensor) die je op de fiets monteert. Gaat die aan, dan telt dat als beweging en gaat — als het alarm scherp staat — het alarm af. Werkt los van Bluetooth.',ext_save:'Opslaan',ext_none:'— Geen —',saved_ok:'Opgeslagen ✓',sens_h:'Sensoren',sens_p:'Elke bron die beweging of diefstal kan melden — de ingebouwde fietssensoren én je eigen HA-sensoren — staat hier als een rij die je apart aan/uit zet, met dezelfde opties.',sens_add:'+ Sensor toevoegen',sens_pick:'Kies een sensor…',s_presence:'Nabijheid tracker (buiten bereik)',s_ext:'Externe sensor',o_role:'Rol:',role_alarm:'Alarm',role_motion:'Alleen beweging',o_alwayson:'Altijd aan (ook als alarm uit)',o_unavail:'Onbereikbaar = sabotage',o_invert:'Omkeren',o_dbl:'Dubbele controle',m_silent:'Stil',m_loud:'Vol alarm',entry_delay:'Ingangsvertraging',exit_delay:'Uitgangsvertraging',sens_delay_hint:'Uitgang = tijd na scherpzetten voordat sensoren tellen (wegrijden). Ingang = genadetijd voordat het alarm echt afgaat.',dbl_win:'Venster dubbele controle',dbl_hint:'Sensoren met “Dubbele controle” laten het alarm pas afgaan als er minstens twee binnen dit venster samen bevestigen.',st_unavail:'onbereikbaar',cloud:'Cloud (PON)',cloud_charge:'Module-lading (cloud)',cloud_loc:'Locatie',cl_moving:'Rijdt',cl_parked:'Geparkeerd',cloud_home:'Afstand tot huis',at_home:'Thuis',away:'Onderweg',mb_in:'Hoofdaccu erin (module laadt)',mb_out:'Hoofdaccu eruit (module op eigen accu)',bosch_h:'Accu & service',b_soh:'Gezondheid',b_cycles:'Laadcycli',b_energy:'Geleverd',b_motor:'Motor-uren',b_service:'Volgende beurt',b_sw:'Software',cloud_accounts:'Cloud-accounts',acc_ble:'Bluetooth (live)',acc_pon:'PON (locatie/GPS)',acc_bosch:'Bosch (diagnostiek)',acc_linked:'gekoppeld ✓',acc_off:'niet ingesteld',acc_hint:'Live data komt via Bluetooth (scan hieronder). Diagnostiek en locatie komen via je Bosch/PON-account (add-on-instellingen) — die fiets wordt automatisch gekoppeld, zonder scan.',your_bike:'jouw geregistreerde fiets',registered:'geregistreerd',acc_checking:'controleren…',activities:'Activiteiten',act_ride_start:'Rit gestart',act_ride_stop:'Rit gestopt',act_left_home:'Vertrokken van huis',act_arrived_home:'Thuisgekomen',act_moved:'Verplaatst',act_none:'nog geen activiteit geregistreerd',ranges_short:'bereik',same_dist:'zelfde afstand als je fiets — waarschijnlijk van jou'},
en:{tab_dash:'Dashboard',tab_more:'More info',tab_set:'Settings',components:'Components',about:'About this add-on',about_p:'Reads your Bosch Smart System eBike (Kiox) over Bluetooth and publishes battery, range, mode, odometer, service, motion/alarm and tracker to Home Assistant.',about_repo:'Source code on GitHub',c_drive:'Drive unit',c_batt:'Battery',c_disp:'Display',c_hub:'Hub',mode:'Ride mode',maint:'Maintenance',maint_sub:'until the next service',security:'Security',ranges:'Estimated range per mode',mileage:'Odometer',tech:'Technical info',tech_kiox:'Kiox (Bosch hub)',tech_gps:'GPS module',t_model:'Model',t_frame:'Frame number',devmode:'🛠️ Motion test is ON — guarding and reading are paused. Turn off Motion test (developer) in the configuration when done.',gps:'GPS module & location',gps_conn:'connected',in_range:'in range',out_range:'out of range',ob_title:'Add your bike',ob_body:"Turn on the bike's display (and put it in pairing mode) — it'll appear below.",ob_scan:'Find bike',add_bike:'Add',adding:'Adding…',replace_bike:'Link a different bike',ob_btn:'Go to Settings',remove_bike:'Remove bike',remove_confirm_btn:'Confirm remove',remove_confirm:'⚠️ Are you sure? Click again to wipe.',removed_ok:'Removed ✓',lk_on:'🔒 Locked',lk_off:'🔓 Unlocked',refresh_module:'Refresh module battery',refreshing:'refreshing…',t_pname:'Product name',t_color:'Colour',t_part:'Part number',t_sku:'Article code',t_pcode:'Product code',t_hubfw:'Firmware',t_modfw:'Firmware',t_addr:'Bluetooth address',t_mac:'MAC address',t_mfr:'Manufacturer',t_hw:'Hardware',t_batt:'Module battery',t_gps:'GPS coordinates',legal:'Unofficial, community-made integration. Not affiliated with, endorsed by, or supported by Bosch eBike Systems or Urban Arrow. Use entirely at your own risk, without any warranty. All trademarks are the property of their respective owners.',su_bike_h:'1. Bike',su_bike_p:"Turn on the bike's display and find it.",scan_bikes:'Scan bikes',select_bike:'Select this bike',su_pair_p:'Put the bike in pairing mode (display → connect a new device), then:',pair_btn:'Pair',su_tracker_h:'2. GPS tracker (anti-theft, optional)',su_tracker_p:'The tracker is always on. Scan and pick it, or skip.',scan_trackers:'Scan trackers',skip:'Skip / off',select_tracker:'Select this tracker',su_alarm_h:'3. Alarm (optional — needs the tracker)',su_alarm_p:'Away = loud (push + lights), Home = silent (notification only). Off = motion sensor only.',conn_on:'Connected',conn_off:'Not connected',no_reading:'no reading yet',up_now:'updated just now',up_min:'updated {n} min ago',up_hour:'updated {n} h ago',up_day:'updated {n} d ago',motion_y:'motion',motion_n:'still',alarm_off:'Alarm off',s_disarmed:'Off',s_home:'Silent',s_away:'Full alarm',s_trig:'⚠️ TRIGGERED',a_off:'Off',a_home:'Silent',a_away:'Full alarm',alarm_off_hint:'Alarm is off (see Settings)',alarm_enable:'Enable alarm',alarm_disable:'Disable alarm',now_off:'currently off',now_on:'currently on',scanning:'scanning… (±8s)',nothing:'nothing found — is the device on / in range?',pairing:'pairing…',paired_ok:'Paired ✓',paired_fail:'Failed — is the bike in pairing mode?',request_photo:'Different bike? Request your colour & model',sec_passive:'🛡️ Passive guard: the add-on only listens for the GPS module (no connection, no extra battery drain). While armed it listens almost continuously and the alarm goes off once the module hasn\\'t been heard for {n} s. When GPS says the bike is away, listening pauses until it is home again.',ext_h:'External motion sensor (on the bike)',ext_p:'Pick your own Home Assistant sensor (contact, vibration or motion) that you mount on the bike. When it turns on it counts as motion and — if the alarm is armed — triggers it. Works independently of Bluetooth.',ext_save:'Save',ext_none:'— None —',saved_ok:'Saved ✓',sens_h:'Sensors',sens_p:'Every source that can report movement or theft — the built-in bike sensors and your own HA sensors — is a row here you enable/disable individually, with the same options.',sens_add:'+ Add sensor',sens_pick:'Pick a sensor…',s_presence:'Tracker presence (out of range)',s_ext:'External sensor',o_role:'Role:',role_alarm:'Alarm',role_motion:'Motion only',o_alwayson:'Always on (even when disarmed)',o_unavail:'Unavailable = tamper',o_invert:'Invert',o_dbl:'Double-check',m_silent:'Silent',m_loud:'Full alarm',entry_delay:'Entry delay',exit_delay:'Exit delay',sens_delay_hint:'Exit = grace after arming before sensors count (riding away). Entry = grace before the alarm actually fires.',dbl_win:'Double-check window',dbl_hint:'Sensors marked “Double-check” only trip the alarm once at least two confirm together within this window.',st_unavail:'unavailable',cloud:'Cloud (PON)',cloud_charge:'Module charge (cloud)',cloud_loc:'Location',cl_moving:'Moving',cl_parked:'Parked',cloud_home:'Distance from home',at_home:'Home',away:'Away',mb_in:'Main battery in (module charging)',mb_out:'Main battery out (module on its own)',bosch_h:'Battery & service',b_soh:'Health',b_cycles:'Charge cycles',b_energy:'Delivered',b_motor:'Motor hours',b_service:'Next service',b_sw:'Software',cloud_accounts:'Cloud accounts',acc_ble:'Bluetooth (live)',acc_pon:'PON (location/GPS)',acc_bosch:'Bosch (diagnostics)',acc_linked:'linked ✓',acc_off:'not set',acc_hint:'Live data comes over Bluetooth (scan below). Diagnostics and location come from your Bosch/PON account (add-on Settings) — that bike is linked automatically, without a scan.',your_bike:'your registered bike',registered:'registered',acc_checking:'checking…',activities:'Activity',act_ride_start:'Ride started',act_ride_stop:'Ride stopped',act_left_home:'Left home',act_arrived_home:'Arrived home',act_moved:'Moved',act_none:'no activity recorded yet',ranges_short:'range',same_dist:'same distance as your bike — likely yours'}};
const t=(k,n)=>((T[LANG]||T.en)[k]||k).replace('{n}',n);
function applyI18n(){document.querySelectorAll('[data-i18n]').forEach(e=>{e.textContent=t(e.dataset.i18n)});}
const MC={Turbo:'#e2241a',Auto:'#7b3ff2','Tour+':'#1aa3e0',Tour:'#1aa3e0',Eco:'#5fb336',Off:'#8a8a8a'};
const bcol=p=>p>40?'#37a24a':p>15?'#f59e0b':'#e53935';
let pick={bike:null,tracker:null};
let _tab='dash';
let SENS=null,ENTS=[],LIVE={};
function tab(t){_tab=t;window._replacing=false;rt();if(t=='set')loadSensors();}
async function loadSensors(){
  let d;try{d=await api('api/sensors');}catch(e){return;}
  if(!d.available){$('#sensCard').style.display='none';return;}
  $('#sensCard').style.display='';
  SENS=d.sensors;ENTS=d.entities||[];LIVE=d.live||{};
  if(!SENS.groups)SENS.groups={};
  if(!SENS.groups.dbl)SENS.groups.dbl={min_active:2,window:30};
  renderSensors();
  if(!window._sensTimer)window._sensTimer=setInterval(refreshSensLive,5000);}
function scfg(kind,ref){return kind=='ext'?SENS.external[+ref]:SENS.builtin[ref];}
function sset(kind,ref,field,el){const v=el.type=='checkbox'?el.checked:(el.type=='number'?Math.max(0,parseInt(el.value||'0')):el.value);
  const c=scfg(kind,ref);c[field]=v;if(field=='enabled')el.closest('.srow').classList.toggle('off',!v);}
function smode(kind,ref,which,el){const c=scfg(kind,ref);const m=new Set(c.modes||[]);
  const ks=which=='silent'?['armed_home','armed_night']:['armed_away'];
  ks.forEach(k=>el.checked?m.add(k):m.delete(k));c.modes=[...m];}
function sentity(ref,el){const c=SENS.external[+ref];c.entity_id=el.value;
  const o=el.options[el.selectedIndex];c.name=o&&o.dataset.nm?o.dataset.nm:el.value;}
function sgroup(ref,el){SENS.external[+ref].group=el.checked?'dbl':'';renderDelays();}
function sdelay(field,el){SENS[field]=Math.max(0,parseInt(el.value||'0'));}
function swin(el){SENS.groups.dbl.window=Math.max(1,parseInt(el.value||'30'));}
function badgeB(key){const L=(LIVE&&LIVE[key])||{};
  return L.present?t('in_range'):t('out_range');}
function badgeE(c){const raw=LIVE.external&&LIVE.external[c.entity_id];
  if(!c.entity_id)return '';if(raw=='unavailable')return t('st_unavail');
  if(raw=='on')return t('now_on');if(raw==null)return t('no_reading');return t('now_off');}
function modeChk(kind,ref,c){const sil=(c.modes||[]).includes('armed_home'),loud=(c.modes||[]).includes('armed_away');
  return `<label><input type=checkbox ${sil?'checked':''} onchange="smode('${kind}','${ref}','silent',this)">${t('m_silent')}</label>`
    +`<label><input type=checkbox ${loud?'checked':''} onchange="smode('${kind}','${ref}','loud',this)">${t('m_loud')}</label>`;}
function optRow(kind,ref,c,ext){let h=`<div class=sopts>`;
  h+=`<label>${t('o_role')} <select onchange="sset('${kind}','${ref}','role',this)"><option value=alarm ${c.role!='motion'?'selected':''}>${t('role_alarm')}</option><option value=motion ${c.role=='motion'?'selected':''}>${t('role_motion')}</option></select></label>`;
  h+=modeChk(kind,ref,c);
  h+=`<label><input type=checkbox ${c.always_on?'checked':''} onchange="sset('${kind}','${ref}','always_on',this)">${t('o_alwayson')}</label>`;
  if(ext){h+=`<label><input type=checkbox ${c.trigger_unavailable?'checked':''} onchange="sset('${kind}','${ref}','trigger_unavailable',this)">${t('o_unavail')}</label>`;
    h+=`<label><input type=checkbox ${c.invert?'checked':''} onchange="sset('${kind}','${ref}','invert',this)">${t('o_invert')}</label>`;
    h+=`<label><input type=checkbox ${c.group=='dbl'?'checked':''} onchange="sgroup('${ref}',this)">${t('o_dbl')}</label>`;}
  return h+`</div>`;}
function srow(kind,ref,name,c,bid,btxt,ext,rm){
  let h=`<div class="srow${c.enabled?'':' off'}"><div class=shead>`;
  h+=`<label class=switch><input type=checkbox ${c.enabled?'checked':''} onchange="sset('${kind}','${ref}','enabled',this)"><span class=sl></span></label>`;
  h+=`<span class=snm>${esc(name)}</span><span class=sbadge id=${bid}>${esc(btxt)}</span>`;
  if(rm)h+=`<button class=sec style="padding:4px 10px" onclick="rmExt('${ref}')">✕</button>`;
  h+=`</div>`;
  if(ext){let os=`<option value="">${t('sens_pick')}</option>`;
    ENTS.forEach(e=>{os+=`<option value="${esc(e.entity_id)}" data-nm="${esc(e.name||'')}" ${e.entity_id==c.entity_id?'selected':''}>${e.match?'★ ':''}${esc(e.name)}${e.device_class?' ('+esc(e.device_class)+')':''}</option>`;});
    h+=`<select class=epick onchange="sentity('${ref}',this)">${os}</select>`;}
  return h+optRow(kind,ref,c,ext)+`</div>`;}
function renderSensors(){let h='';
  h+=srow('builtin','presence',t('s_presence'),SENS.builtin.presence,'sb_b_presence',badgeB('presence'),false,false);
  (SENS.external||[]).forEach((c,i)=>{h+=srow('ext',''+i,c.name||t('s_ext'),c,'sb_e_'+i,badgeE(c),true,true);});
  $('#sensList').innerHTML=h;renderDelays();}
function renderDelays(){const anyDbl=(SENS.external||[]).filter(c=>c.group=='dbl').length;
  let h=`<div class=sopts><label>${t('entry_delay')} <input type=number min=0 style=width:70px value="${SENS.entry_delay||0}" onchange="sdelay('entry_delay',this)"> s</label>`;
  h+=`<label>${t('exit_delay')} <input type=number min=0 style=width:70px value="${SENS.exit_delay||0}" onchange="sdelay('exit_delay',this)"> s</label></div>`;
  h+=`<p class=muted style="margin-top:8px">${t('sens_delay_hint')}</p>`;
  if(anyDbl>=1){h+=`<div class=sopts><label>${t('dbl_win')} <input type=number min=1 style=width:70px value="${(SENS.groups.dbl&&SENS.groups.dbl.window)||30}" onchange="swin(this)"> s</label></div><p class=muted>${t('dbl_hint')}</p>`;}
  $('#sensDelays').innerHTML=h;}
function addExtSensor(){SENS.external=SENS.external||[];
  SENS.external.push({id:'',entity_id:'',name:'',enabled:true,role:'alarm',always_on:false,trigger_unavailable:false,invert:false,modes:['armed_away','armed_home','armed_night'],group:''});
  renderSensors();}
function rmExt(ref){SENS.external.splice(+ref,1);renderSensors();}
async function saveSensors(){const used=(SENS.external||[]).some(c=>c.group=='dbl');
  const groups=used?{dbl:{min_active:2,window:(SENS.groups.dbl&&SENS.groups.dbl.window)||30}}:{};
  await post('api/sensors',{sensors:Object.assign({},SENS,{groups})});
  $('#sensMsg').textContent=' '+t('saved_ok');setTimeout(()=>{$('#sensMsg').textContent='';},2500);}
async function refreshSensLive(){if(_tab!='set'||!SENS)return;
  let d;try{d=await api('api/sensors');}catch(e){return;}LIVE=d.live||{};
  let el=$('#sb_b_presence');if(el)el.textContent=badgeB('presence');
  (SENS.external||[]).forEach((c,i)=>{const e=$('#sb_e_'+i);if(e)e.textContent=badgeE(c);});}
function rt(){const added=window._added!==false;
  const obVis=!added&&_tab=='dash';
  $('#onboard').classList.toggle('hidden', !obVis);
  $('#dash').classList.toggle('hidden', _tab!='dash'||!added);
  $('#more').classList.toggle('hidden', _tab!='more'||!added);
  $('#set').classList.toggle('hidden', _tab!='set');
  $('#addedBike').classList.toggle('hidden', !added);
  $('#addFlow').classList.toggle('hidden', added&&!window._replacing);
  $('#tabDash').classList.toggle('on',_tab=='dash');$('#tabMore').classList.toggle('on',_tab=='more');$('#tabSet').classList.toggle('on',_tab=='set');
  if(obVis&&!window._obScan){window._obScan=1;scan('bike','#obFound');}
  if(added){window._obScan=0;}}
function ago(iso){if(!iso)return '';const ts=Date.parse(iso);if(isNaN(ts))return '';
  const s=Math.max(0,(Date.now()-ts)/1000);
  if(s<90)return t('up_now');if(s<3600)return t('up_min',Math.round(s/60));
  if(s<86400)return t('up_hour',Math.round(s/3600));return t('up_day',Math.round(s/86400));}
const rel=iso=>ago(iso).replace(/^(updated|bijgewerkt) +/i,'');
const fresh=iso=>{const ts=Date.parse(iso);return !isNaN(ts)&&(Date.now()-ts)<150000;};
const fmtDist=m=>m<1000?Math.round(m)+' m':(m/1000).toFixed(1)+' km';
/* INSIGHT_LOGIC */

async function refresh(){const s=await api('api/status');const L=s.last||{};const di=L.device_info||{};const dev=s.device||{};const R=L.range||{};
  renderInsights(L.insights,L.next_service);applyMaintenancePreference(s.show_maintenance!==false);
  window._added=!s.bike_off&&!!(L.last_updated||L.frame_number||s.bike||s.locked);
  window._bikeAddr=s.bike||L.address||'';rt();
  if(window._added){
    $('#addedName').textContent=L.bike_model||L.product_name||L.bike_brand||'Bosch Smart System eBike';
    $('#addedMac').textContent=L.address||s.bike||'';
    const conn=fresh(L.last_updated);
    $('#addedConn').innerHTML=conn?`<span style="color:#43a047">✓ ${t('conn_on')}</span>`:`<span class=muted>${t('conn_off')}</span>`;
    $('#pairArea').classList.toggle('hidden', conn);}
  $('#devBar').style.display=(s.motion_test)?'':'none';
  $('#bikeTitle').textContent=L.bike_model||L.product_name||L.bike_brand||di.manufacturer||dev.manufacturer||'Bosch eBike';
  $('#bikeSpec').textContent=L.last_updated?ago(L.last_updated):t('no_reading');
  const f=fresh(L.last_updated);
  $('#conn').className='badge'+(f?' on':'');$('#conn').textContent=f?t('conn_on'):t('conn_off');
  const cm=$('#cloudMatch');if(L.cloud_matched){cm.style.display='';cm.className='badge on';cm.textContent='✓ '+t('registered');cm.title=L.cloud_bike_id||'';}else cm.style.display='none';
  const p=L.battery; const fill=p==null?0:Math.max(0,Math.min(5,Math.round(p/20)));
  let seg='';for(let i=0;i<5;i++)seg+=`<i style="background:${i<fill?bcol(p):'#dfe2e7'}"></i>`;$('#segs').innerHTML=seg;
  $('#pct').innerHTML=esc(p??'—')+'<small>%</small>';
  $('#range').innerHTML=(R.turbo!=null?`${esc(R.turbo)}–${esc(R.eco)}`:'—')+'<small> km</small>';
  $('#mode').textContent=L.mode||'—';const mp=$('#modePill');
  if(L.mode){mp.style.display='';mp.style.background=(MC[L.mode]||'#888')+'22';mp.style.color=MC[L.mode]||'#888';mp.textContent=L.mode;}else mp.style.display='none';
  const order=[['turbo','TURBO'],['auto','AUTO'],['tour','TOUR+'],['eco','ECO']];
  $('#ranges').innerHTML=order.map(([k,n])=>`<div><div class=m style="color:${MC[n=='TOUR+'?'Tour+':n[0]+n.slice(1).toLowerCase()]||'#555'}">${n}</div><div class=v>${esc(R[k]??'—')}<small> km</small></div></div>`).join('');
  const rsum=order.reduce((a,[k])=>a+(R[k]||0),0)||1;
  $('#rangeBar').innerHTML=order.map(([k,n])=>`<i style="width:${(R[k]||0)/rsum*100}%;background:${MC[n=='TOUR+'?'Tour+':n[0]+n.slice(1).toLowerCase()]||'#999'}"></i>`).join('');
  $('#service').textContent=L.next_service!=null?Math.round(L.next_service)+' km':'—';
  $('#odo').textContent=L.odometer!=null?L.odometer.toLocaleString('nl-NL')+' km':'—';
  // technical info — Kiox (Bosch hub) vs GPS module, separate devices/MACs
  const dl=rows=>{const r=rows.filter(([k,v])=>v!=null&&v!=='');return r.length
    ?'<dl class=tech>'+r.map(([k,v])=>`<dt>${t(k)}</dt><dd>${v&&v.html?v.html:esc(v)}</dd>`).join('')+'</dl>'
    :`<div class=muted style="margin:2px 0 6px">${t('no_reading')}</div>`;};
  const kiox=[['t_pname',L.product_name],['t_color',L.product_color],['t_model',di.model||L.model_number],['t_frame',L.frame_number],['t_sku',L.sku],['t_pcode',L.product_code],['t_part',L.part_number||di.serial],['t_hubfw',L.hub_firmware||di.firmware],['t_addr',L.address||s.bike]];
  const gla=Number(L.cloud&&L.cloud.latitude),glo=Number(L.cloud&&L.cloud.longitude);
  const gco=(L.cloud&&L.cloud.latitude!=null&&isFinite(gla)&&isFinite(glo))?{html:`<a href="https://www.openstreetmap.org/?mlat=${gla}&mlon=${glo}#map=16/${gla}/${glo}" target=_blank rel=noopener>${gla.toFixed(5)}, ${glo.toFixed(5)}</a> ☁️`}:null;
  const gps=[['t_mac',s.tracker||L.module_mac],['t_modfw',L.module_firmware],['t_hw',L.module_hardware],['t_mfr',L.module_manufacturer],['t_batt',L.tracker_battery!=null?L.tracker_battery+'%':null],['t_gps',gco]];
  $('#techInfo').innerHTML=`<div class=th>${t('tech_kiox')}</div>`+dl(kiox)+`<div class=th>${t('tech_gps')}</div>`+dl(gps);
  // components — name + firmware + production date per subsystem
  const C=L.components||{};
  const cv=(name,key)=>{const c=C[key]||{};const x=[name,c.firmware&&('fw '+c.firmware),c.date].filter(Boolean);return x.length?x.join(' · '):null;};
  const comp=[['c_drive',cv(L.drive_unit,'drive')],['c_batt',cv(L.battery_model,'battery')],['c_disp',cv(L.display,'display')],['c_hub',cv(di.model||L.model_number,'controller')]];
  $('#compInfo').innerHTML=dl(comp);
  // Bosch cloud (health/service) card — only when Bosch cloud data has arrived
  const BO=L.bosch;
  if(BO){$('#boschCard').style.display='';
    const bs=[[t('b_soh'),BO.battery_soh!=null?BO.battery_soh+'%':'—'],
      [t('b_cycles'),BO.battery_cycles!=null?BO.battery_cycles:'—'],
      [t('b_energy'),BO.battery_lifetime_wh!=null?(BO.battery_lifetime_wh/1000).toFixed(1)+' kWh':'—'],
      [t('b_motor'),BO.motor_hours!=null?BO.motor_hours+' h':'—'],
      ...(maintenanceVisible?[[t('b_service'),BO.next_service_km!=null?BO.next_service_km+' km':'—']]:[]),
      [t('b_sw'),BO.software_version||'—']];
    $('#boschStats').innerHTML=bs.map(([m,v])=>`<div><div class=m>${esc(m)}</div><div class=v>${esc(v)}</div></div>`).join('');
    $('#boschUpd').textContent=BO.ts?ago(BO.ts):'';}
  else $('#boschCard').style.display='none';
  // Activities (usage/movement) log — newest first. Card shows once PON is active
  // (even before the first event) so it's discoverable.
  const AL=L.activity_log||[];
  if(L.cloud||AL.length){$('#actCard').style.display='';
    if(AL.length){
      const lab={ride_start:t('act_ride_start'),ride_stop:t('act_ride_stop'),left_home:t('act_left_home'),arrived_home:t('act_arrived_home'),moved:t('act_moved')};
      const ico={ride_start:'🚴',ride_stop:'🅿️',left_home:'➡️',arrived_home:'🏠',moved:'📍'};
      $('#actList').innerHTML=AL.slice().reverse().slice(0,25).map(e=>{
        const ela=Number(e.lat),elo=Number(e.lon);
        const loc=(e.lat!=null&&isFinite(ela)&&isFinite(elo))?` · <a href="https://www.openstreetmap.org/?mlat=${ela}&mlon=${elo}#map=17/${ela}/${elo}" target=_blank rel=noopener>kaart</a>`:'';
        const dist=(e.dist!=null)?` (${esc(e.dist)} m)`:'';
        return `<div style="padding:7px 0;border-top:1px solid var(--line);font-size:14px"><span class=muted>${esc(rel(e.ts))}</span> — ${ico[e.type]||'•'} ${esc(lab[e.type]||e.type)}${dist}${loc}</div>`;}).join('');
    }else $('#actList').innerHTML=`<span class=muted>${t('act_none')}</span>`;}
  else $('#actCard').style.display='none';
  // Cloud-accounts status (More info) — shows the three layers are coupled apart
  const accRow=(k,on,extra)=>`<dt>${k}</dt><dd>${on?t('acc_linked')+(extra?' · '+esc(extra):''):t('acc_off')}</dd>`;
  $('#cloudAcc').innerHTML='<dl class=tech>'+
    accRow(t('acc_ble'),!!(s.bike||L.address),(L.address||s.bike||''))+
    accRow(t('acc_pon'),!!L.cloud,'')+
    accRow(t('acc_bosch'),!!BO,(BO&&BO.bike_id?String(BO.bike_id).slice(0,8)+'…':'')+(L.cloud_matched?' ✓':''))+
    '</dl>';
  // GPS module card (rail)
  // one module-battery %: cloud preferred, BLE as backup
  const cloudC=(L.cloud&&L.cloud.module_charge!=null)?L.cloud.module_charge:null;
  const tbv=(cloudC!=null)?cloudC:L.tracker_battery;
  const battSrc=(cloudC!=null)?'<span class=src title=Cloud>☁️</span>':(L.tracker_battery!=null?'<span class=src title=Bluetooth>📶</span>':'');
  $('#gpsBatt').innerHTML=esc(tbv!=null?tbv:'—')+'<small>%</small>'+battSrc;
  const gUpd=(cloudC!=null)?(L.cloud&&L.cloud.ts):L.tracker_updated;
  $('#gpsUpd').textContent=gUpd?ago(gUpd):t('no_reading');
  const gc=$('#gpsConn');const CLp=L.cloud;
  const setPill=(bg,col,txt)=>{gc.style.display='';gc.style.background=bg;gc.style.color=col;gc.textContent=txt;};
  const GRN='rgba(67,160,71,.18)',GRNC='#43a047',AMB='rgba(251,140,0,.16)',AMBC='#fb8c00';
  // BLE presence is authoritative for home (seeing the tracker = home, no battery
  // cost). If BLE can't see it, it's NOT home — show riding/away from the cloud.
  const homeBLE=L.tracker_present===true;
  if(homeBLE)setPill(GRN,GRNC,t('at_home'));
  else if(CLp&&CLp.in_use)setPill(AMB,AMBC,t('cl_moving'));
  else if(CLp&&CLp.distance_m!=null&&CLp.distance_m>100)setPill(AMB,AMBC,fmtDist(CLp.distance_m));
  else if(CLp||L.tracker_present===false)setPill(AMB,AMBC,t('away'));
  else gc.style.display='none';
  const mb=$('#mainBatt');
  if(L.main_battery===true){mb.textContent='🔌 '+t('mb_in');}
  else if(L.main_battery===false){mb.textContent='🔋 '+t('mb_out');}
  else mb.textContent='';
  // cloud (PON) card — only when cloud data has arrived
  const CLD=L.cloud;
  if(CLD){$('#cloudSub').style.display='';
    $('#cloudState').textContent=CLD.loc_state==='moving'?t('cl_moving'):t('cl_parked');
    const cs=$('#cloudSpeed');
    if(CLD.speed!=null){cs.style.display='';cs.style.background='rgba(3,169,244,.16)';cs.style.color='#03a9f4';cs.textContent=CLD.speed+' km/h';}else cs.style.display='none';
    $('#cloudHome').textContent=homeBLE?('✓ '+t('at_home')):CLD.in_use?t('cl_moving'):(CLD.distance_m!=null&&CLD.distance_m>100?fmtDist(CLD.distance_m):t('away'));
    const mp=$('#cloudMap');
    try{
      if(!window.L){mp.style.display='none';$('#cloudUpd').textContent='map: leaflet not loaded';}
      else if(CLD.latitude!=null){const la=CLD.latitude,lo=CLD.longitude;mp.style.display='';
        const zWant=(CLD.home===false)?15:18;  // away = zoom out 3 to show surroundings
        if(!window._lmap){window._lmap=window.L.map(mp,{zoomControl:true,attributionControl:true});
          window.L.tileLayer('tile/{z}/{x}/{y}',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(window._lmap);
          const bikeIcon=window.L.divIcon({className:'',iconSize:[38,38],iconAnchor:[19,19],html:`<div style="background:#03a9f4;width:38px;height:38px;border-radius:50%;border:3px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center"><svg viewBox="0 0 24 24" width="20" height="20" fill="#fff"><path d="M5,20.5A3.5,3.5 0 0,1 1.5,17A3.5,3.5 0 0,1 5,13.5A3.5,3.5 0 0,1 8.5,17A3.5,3.5 0 0,1 5,20.5M5,12A5,5 0 0,0 0,17A5,5 0 0,0 5,22A5,5 0 0,0 10,17A5,5 0 0,0 5,12M14.8,10H19V8.2H15.8L13.86,4.93C13.57,4.43 13,4.1 12.4,4.1C11.93,4.1 11.5,4.29 11.2,4.6L7.5,8.29C7.19,8.6 7,9 7,9.5C7,10.13 7.33,10.66 7.85,10.97L11.2,13V18H13V11.5L10.75,9.85L13.07,7.5M19,12A5,5 0 0,0 14,17A5,5 0 0,0 19,22A5,5 0 0,0 24,17A5,5 0 0,0 19,12M19,20.5A3.5,3.5 0 0,1 15.5,17A3.5,3.5 0 0,1 19,13.5A3.5,3.5 0 0,1 22.5,17A3.5,3.5 0 0,1 19,20.5M16,4.8C17,4.8 17.8,4 17.8,3C17.8,2 17,1.2 16,1.2C15,1.2 14.2,2 14.2,3C14.2,4 15,4.8 16,4.8Z"/></svg></div>`});
          window._lmark=window.L.marker([la,lo],{icon:bikeIcon}).addTo(window._lmap);
          const Fs=window.L.Control.extend({onAdd:function(){const b=window.L.DomUtil.create('a','fsbtn');b.href='#';b.title='Fullscreen';b.innerHTML=`<svg viewBox="0 0 24 24" width=18 height=18><path fill=currentColor d="M5,5H10V7H7V10H5V5M14,5H19V10H17V7H14V5M17,14H19V19H14V17H17V14M10,17V19H5V14H7V17H10Z"/></svg>`;window.L.DomEvent.on(b,'click',window.L.DomEvent.stop).on(b,'click',function(){mp.classList.toggle('fs');setTimeout(function(){try{window._lmap.invalidateSize();}catch(e){}},120);});return b;}});
          window._lmap.addControl(new Fs({position:'topright'}));
          window._lmap.setView([la,lo],zWant);window._lzoom=zWant;
          setTimeout(()=>{try{window._lmap.invalidateSize();}catch(e){}},300);}
        else{window._lmark.setLatLng([la,lo]);
          if(window._lzoom!==zWant){window._lzoom=zWant;window._lmap.setView([la,lo],zWant);}}
        setTimeout(()=>{try{window._lmap.invalidateSize();}catch(e){}},50);
        $('#cloudUpd').textContent=CLD.ts?ago(CLD.ts):'';}
      else{mp.style.display='none';$('#cloudUpd').textContent=CLD.ts?ago(CLD.ts):'';}
    }catch(e){mp.style.display='none';$('#cloudUpd').textContent='map err: '+(e&&e.message||e);}}
  else $('#cloudSub').style.display='none';
  // security
  const A=L.alarm; const nm={disarmed:t('s_disarmed'),armed_home:t('s_home'),armed_away:t('s_away'),triggered:t('s_trig')}[A]||'—';
  const mv=L.motion?t('motion_y'):t('motion_n');const tb=L.tracker_battery;
  $('#secLine').innerHTML=(s.alarm_off?t('alarm_off')+' · '+mv:`${nm} · ${mv}`);
  $('#secWarn').textContent=t('sec_passive').replace('{n}',s.alarm_grace_s);
  $('#armBox').innerHTML=s.alarm_off?`<span class=muted>${t('alarm_off_hint')}</span>`:
    [['DISARM','a_off','disarmed'],['ARM_HOME','a_home','armed_home'],['ARM_AWAY','a_away','armed_away']].map(([c,lk,st])=>
     `<button class="${A==st?'':'sec'}" onclick="arm('${c}')">${t(lk)}</button>`).join('');
  // eBike Lock (read-only status from the bike)
  const ls=L.lock_state; const meth=(L.lock_label||'').match(/\\((.*)\\)/);
  $('#lockLine').textContent=ls?('eBike Lock: '+(ls=='locked'?t('lk_on'):t('lk_off'))+(meth?' ('+meth[1]+')':'')):'';
  // settings tab bits
  window._alarmOff=s.alarm_off;
  $('#alarmBtn').textContent=t(s.alarm_off?'alarm_enable':'alarm_disable');
  $('#alarmState').textContent=t(s.alarm_off?'now_off':'now_on');}
async function arm(cmd){await post('api/alarm',{cmd});refresh()}
async function toggleAlarm(){await post('api/set_alarm',{on:window._alarmOff===true});refresh()}
const fmt=d=>`${d.address} · ${d.rssi} dBm`+(d.module_mac?` · ${d.module_mac}`:'');
async function scan(kind,box){box=box||(kind=='bike'?'#bikes':'#trackers');
  $(box).innerHTML=`<span class=muted>${t('scanning')}</span>`;
  let list=[];try{list=await api('api/scan',{method:'POST'});}catch(e){}
  const items=(list||[]).filter(d=>d.kind==kind);
  if(!items.length){$(box).innerHTML=`<span class=muted>${t('nothing')}</span>`;return}
  $(box).innerHTML='';const els={};
  items.forEach(d=>{
   if(kind=='bike'){
     const c=document.createElement('div');c.className='biketile';
     c.innerHTML=`<img src=bike.png class=btimg><div class=btinfo><b class=bname>Bosch Smart System eBike</b><div class=muted style="font-size:12px">${esc(d.address)} · ${esc(d.rssi)} dBm</div><div class=mtag style="font-size:12px;color:#43a047;margin-top:2px"></div></div><button class=btadd>${t('add_bike')}</button>`;
     c.querySelector('.btadd').onclick=()=>addBike(d,c);
     els[d.address]=c;$(box).appendChild(c);
   }else{
     const el=document.createElement('div');el.className='row';
     el.innerHTML=`<div><b>${esc(d.name||kind)}</b><div class=muted style="font-size:12px">${esc(fmt(d))}</div></div>`;
     el.onclick=()=>{pick[kind]=d;[...$(box).children].forEach(c=>c.classList.remove('sel'));el.classList.add('sel');$('#trackerActions').classList.remove('hidden')};
     els[d.address]=el;$(box).appendChild(el);
   }});
  // Tracker↔bike distance heuristic: the tracker whose RSSI is closest to the
  // identified bike's is most likely on the same bike (the GPS module has no cloud
  // id and its BLE MAC rotates, so this is a hint — pre-selected, user confirms).
  if(kind=='tracker'){const bd=(list||[]).filter(d=>d.kind=='bike');
    const ba=(window._bikeAddr||'').toUpperCase();
    const bike=bd.find(d=>(d.address||'').toUpperCase()==ba)||bd[0];
    if(bike){let best=null,diff=1e9;
      items.forEach(d=>{const df=Math.abs((d.rssi||-999)-(bike.rssi||-999));if(df<diff){diff=df;best=d;}});
      if(best&&diff<=12){const el=els[best.address];
        if(el){el.classList.add('sel');pick.tracker=best;$('#trackerActions').classList.remove('hidden');
          const inf=el.querySelector('div');if(inf){const tg=document.createElement('div');tg.className='muted';tg.style='font-size:12px;color:#43a047;margin-top:2px';tg.textContent='≈ '+t('same_dist');inf.appendChild(tg);}}}}}
  // Bosch cloud auto-match for bikes: mark + auto-name the registered bike.
  if(kind=='bike'){for(const d of items){const c=els[d.address];const tag=c&&c.querySelector('.mtag');
    if(tag)tag.textContent='· '+t('acc_checking');
    let r={};try{r=await post('api/identify',{address:d.address});}catch(e){}
    if(!r||!r.registry){if(tag)tag.textContent='';break;}
    if(r.matched){d.cloud_name=r.name;if(c)c.classList.add('match');
      if(tag)tag.textContent='✓ '+t('your_bike');
      const nm=c&&c.querySelector('.bname');if(nm&&r.name)nm.textContent=r.name;break;}
    else if(tag)tag.textContent='';}}}
async function addBike(d,tile){window._replacing=false;const btn=tile&&tile.querySelector('.btadd');
  if(btn){btn.disabled=true;btn.textContent=t('adding');}
  await post('api/select_bike',{address:d.address,name:d.cloud_name||''});
  const r=await post('api/pair');await refresh();
  if(r&&r.ok)tab('dash');}          // paired → show the dashboard; else the added tile shows the pair step
function showScan(){window._replacing=true;$('#addFlow').classList.remove('hidden');scan('bike','#bikes');}
async function removeBike(){const b=$('#removeBtn'),m=$('#removeMsg');
  if(!b.dataset.armed){b.dataset.armed='1';b.textContent=t('remove_confirm_btn');m.textContent=' '+t('remove_confirm');
    clearTimeout(window._rmT);window._rmT=setTimeout(()=>{b.dataset.armed='';b.textContent=t('remove_bike');m.textContent='';},6000);return;}
  clearTimeout(window._rmT);b.dataset.armed='';b.textContent=t('remove_bike');window._replacing=false;
  await post('api/remove_bike');m.textContent=' '+t('removed_ok');refresh()}
async function pair(){$('#pairBtn').disabled=true;$('#pairMsg').textContent=' '+t('pairing');
  const r=await post('api/pair');$('#pairBtn').disabled=false;
  $('#pairMsg').innerHTML=(r&&r.ok)?'':` <span class=bad>${t('paired_fail')}</span>`;refresh()}
async function selectTracker(){await post('api/select_tracker',{module_mac:pick.tracker.module_mac});refresh()}
async function skipTracker(){await post('api/select_tracker',{off:true});refresh()}
async function refreshTracker(){const b=$('#trkBtn');b.disabled=true;b.textContent=t('refreshing');
  await post('api/refresh_tracker');
  setTimeout(()=>{b.disabled=false;b.textContent=t('refresh_module');refresh();},14000)}
applyI18n();refresh();setInterval(refresh,5000);
</script></body></html>"""


INDEX_HTML = (INDEX_HTML.replace("<!-- INSIGHT_PANELS -->", INSIGHTS_HTML)
              .replace("</style>", INSIGHTS_CSS + "</style>", 1)
              .replace("/* INSIGHT_LOGIC */", INSIGHTS_SCRIPT))
