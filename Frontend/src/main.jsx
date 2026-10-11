import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Activity from 'lucide-react/dist/esm/icons/activity.js';
import ArrowDownRight from 'lucide-react/dist/esm/icons/arrow-down-right.js';
import ArrowRight from 'lucide-react/dist/esm/icons/arrow-right.js';
import Battery from 'lucide-react/dist/esm/icons/battery.js';
import Bike from 'lucide-react/dist/esm/icons/bike.js';
import Check from 'lucide-react/dist/esm/icons/check.js';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down.js';
import CircleHelp from 'lucide-react/dist/esm/icons/circle-help.js';
import Clock3 from 'lucide-react/dist/esm/icons/clock-3.js';
import Compass from 'lucide-react/dist/esm/icons/compass.js';
import Gauge from 'lucide-react/dist/esm/icons/gauge.js';
import Leaf from 'lucide-react/dist/esm/icons/leaf.js';
import MapPin from 'lucide-react/dist/esm/icons/map-pin.js';
import Menu from 'lucide-react/dist/esm/icons/menu.js';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw.js';
import Route from 'lucide-react/dist/esm/icons/route.js';
import Settings2 from 'lucide-react/dist/esm/icons/settings-2.js';
import ShieldCheck from 'lucide-react/dist/esm/icons/shield-check.js';
import Sparkles from 'lucide-react/dist/esm/icons/sparkles.js';
import TriangleAlert from 'lucide-react/dist/esm/icons/triangle-alert.js';
import Zap from 'lucide-react/dist/esm/icons/zap.js';
import { api, getApiSettings, saveApiSettings } from './api';
import './styles.css';

const PROFILE = 'xiaomi_pro2_public';
const INITIAL_ROUTE = {
  vehicle_profile: PROFILE, soc_percent: 80, cycles_used: 0, cycles_to_80pct: 800, temp_c: 25,
  trip_km: 8, safety_margin: 0.175, route: 'flat', rider_kg: 95, vehicle_kg: 14.2,
  start_lat: 25.2620, start_lon: 82.9890, end_lat: 25.3307, end_lon: 82.9873,
};
const DEMO_ROUTES = [
  { id: 'bhu', label: 'IIT (BHU) · mostly flat', start: 'IIT (BHU), Varanasi', end: 'Varanasi city', route: { start_lat: 25.2620, start_lon: 82.9890, end_lat: 25.3307, end_lon: 82.9873, route: 'flat', trip_km: 8 } },
  { id: 'hills', label: 'Shimla → Dharamshala · hilly', start: 'Shimla, Himachal Pradesh', end: 'Dharamshala, Himachal Pradesh', route: { start_lat: 31.1048, start_lon: 77.1734, end_lat: 32.2190, end_lon: 76.3234, route: 'hill', trip_km: 240 } },
  { id: 'mussoorie-rishikesh', label: 'Mussoorie → Rishikesh · downhill', start: 'Mussoorie, Uttarakhand', end: 'Rishikesh, Uttarakhand', route: { start_lat: 30.4569, start_lon: 78.0783, end_lat: 30.1165, end_lon: 78.2311, route: 'hill', trip_km: 75 } },
  { id: 'srinagar-gulmarg', label: 'Srinagar → Gulmarg · mountain', start: 'Srinagar, Jammu & Kashmir', end: 'Gulmarg, Jammu & Kashmir', route: { start_lat: 34.0857, start_lon: 74.8056, end_lat: 34.0536, end_lon: 74.3819, route: 'hill', trip_km: 55 } },
  { id: 'ooty-coonoor', label: 'Ooty → Coonoor · Nilgiri hills', start: 'Ooty, Tamil Nadu', end: 'Coonoor, Tamil Nadu', route: { start_lat: 11.4127, start_lon: 76.7031, end_lat: 11.3439, end_lon: 76.7945, route: 'hill', trip_km: 20 } },
];
const fmt = (n, digits = 1) => Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : '—';

function Field({ label, value, onChange, type = 'number', step, min, max, suffix, hint, required }) {
  return <label className="field"><span>{label}{required && <b className="required"> *</b>}</span><div className="input-wrap"><input type={type} value={value} step={step ?? (type === 'number' ? 'any' : undefined)} min={min} max={max} onChange={e => onChange(e.target.value)} required={required} />{suffix && <small>{suffix}</small>}</div>{hint && <em>{hint}</em>}</label>;
}

function App() {
  const [page, setPage] = useState('overview');
  const [settings, setSettings] = useState(getApiSettings());
  const [health, setHealth] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [route, setRoute] = useState(INITIAL_ROUTE);
  const [statusResult, setStatusResult] = useState(null);
  const [reEstimateResult, setReEstimateResult] = useState(null);
  const [coordMode, setCoordMode] = useState('map');
  const [demoRoute, setDemoRoute] = useState('bhu');

  const setRouteValue = (key, value) => {
    setRoute(prev => ({ ...prev, [key]: value }));
    if (['start_lat', 'start_lon', 'end_lat', 'end_lon'].includes(key)) setDemoRoute('custom');
  };
  const selectDemoRoute = preset => {
    setRoute(prev => ({ ...prev, ...preset.route }));
    setDemoRoute(preset.id);
    setCoordMode('manual');
    setResult(null);
    setError('');
  };
  const call = async task => {
    setBusy(true); setError('');
    try { return await task(); }
    catch (e) {
      const noKeyOnProtectedApi = health === 'ok' && !getApiSettings().apiKey && e.message.includes('Failed to fetch');
      setError(noKeyOnProtectedApi
        ? 'Backend is online, but production mode requires an API key for range and profile endpoints. Open API connection, paste the key from Backend/.env, and save.'
        : e.message);
      return null;
    }
    finally { setBusy(false); }
  };
  const checkBackend = async () => {
    const data = await call(() => api('/health'));
    if (data) setHealth(data.status);
  };
  useEffect(() => {
    checkBackend();
    if (getApiSettings().apiKey) {
      call(async () => { const data = await api('/vehicle-profiles'); setProfiles(data.profiles || []); return data; });
    }
  }, []);

  const runRoute = async e => {
    e?.preventDefault();
    setResult(null);
    const payload = { ...route, trip_km: Number(route.trip_km), soc_percent: Number(route.soc_percent), cycles_used: Number(route.cycles_used), cycles_to_80pct: Number(route.cycles_to_80pct), temp_c: Number(route.temp_c), safety_margin: Number(route.safety_margin), rider_kg: Number(route.rider_kg), vehicle_kg: Number(route.vehicle_kg), start_lat: Number(route.start_lat), start_lon: Number(route.start_lon), end_lat: Number(route.end_lat), end_lon: Number(route.end_lon) };
    const data = await call(() => api('/route-range', { method: 'POST', body: payload }));
    if (data) {
      setResult(data);
      setRoute(prev => ({ ...prev, trip_km: Number(data.route_distance_km ?? data.route_km ?? prev.trip_km) }));
      setPage('overview');
    }
  };
  const submitStatus = async e => {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    const body = { voltage_v: Number(f.get('voltage_v')), current_a: Number(f.get('current_a')), temp_c: Number(f.get('temp_c')), soc_percent: Number(f.get('soc_percent')), sampled_at: new Date().toISOString() };
    const data = await call(() => api('/battery/status', { method: 'POST', body })); if (data) setStatusResult(data);
  };
  const submitReEstimate = async e => {
    e.preventDefault(); const f = new FormData(e.currentTarget);
    const body = { ...route, trip_km: Number(f.get('trip_km')), km_done: Number(f.get('km_done')), wh_used: Number(f.get('wh_used')), start_lat: Number(route.start_lat), start_lon: Number(route.start_lon), end_lat: Number(route.end_lat), end_lon: Number(route.end_lon), soc_percent: Number(route.soc_percent), cycles_used: Number(route.cycles_used), cycles_to_80pct: Number(route.cycles_to_80pct), temp_c: Number(route.temp_c), safety_margin: Number(route.safety_margin) };
    delete body.start_lat; delete body.start_lon; delete body.end_lat; delete body.end_lon;
    const data = await call(() => api('/re-estimate', { method: 'POST', body })); if (data) setReEstimateResult(data);
  };
  const saveSettings = e => { e.preventDefault(); saveApiSettings(settings.baseUrl, settings.apiKey); setError(''); checkBackend(); };

  const nav = [
    { id: 'overview', label: 'Range overview', icon: Gauge, group: 'YOUR VEHICLE' },
    { id: 'battery', label: 'Battery status', icon: Battery },
    { id: 'reestimate', label: 'Trip re-estimate', icon: RefreshCw, group: 'TOOLS' },
    { id: 'settings', label: 'API connection', icon: Settings2 },
  ];
  const elevation = result?.profile?.elevation_m || [];
  const stepKm = Number(result?.profile?.step_km) || Number(result?.route_km) / Math.max(1, elevation.length - 1);
  const minElevation = elevation.length ? Math.min(...elevation) : 0;
  const maxElevation = elevation.length ? Math.max(...elevation) : 0;
  const elevationSpan = Math.max(1, maxElevation - minElevation);
  const elevationPoints = elevation.map((height, index) =>
    `${(index / Math.max(1, elevation.length - 1)) * 100},${90 - ((height - minElevation) / elevationSpan) * 80}`,
  ).join(' ');

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Activity size={19} strokeWidth={2.6} /></div><span>range<span className="brand-light">true</span></span><span className="brand-tag">BETA</span></div>
      <div className="vehicle-switch"><div className="vehicle-icon"><Bike size={18} /></div><div><strong>{result?.vehicle_profile?.name?.split(' (')[0] || 'Xiaomi scooter profile'}</strong><small>Public data demo</small></div><ChevronDown size={15} /></div>
      <div className="nav-label">{nav[0].group}</div>
      <nav>{nav.map((item, i) => <React.Fragment key={item.id}>{item.group && i > 0 && <div className="nav-label nav-label-spaced">{item.group}</div>}<button className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => { setPage(item.id); setError(''); }}><item.icon size={17} /><span>{item.label}</span>{item.id === 'overview' && result && <i />}</button></React.Fragment>)}</nav>
      <div className="sidebar-bottom"><div className={`connection-card ${health === 'ok' ? 'connected' : ''}`}><span className="pulse"/><div><strong>{health === 'ok' ? 'Backend connected' : health === 'degraded' ? 'Model degraded' : 'Checking backend'}</strong><small>{settings.baseUrl}</small></div></div><div className="sidebar-note"><ShieldCheck size={15} /><span>Estimates are guidance, not a guarantee.</span></div></div>
    </aside>

    <main className="main-area">
      <header className="topbar"><button className="mobile-menu" aria-label="Open menu"><Menu size={20}/></button><div className="breadcrumbs">RangeTrue <span>/</span> {nav.find(x => x.id === page)?.label}</div><div className="top-actions"><span className={`api-pill ${health === 'ok' ? 'online' : ''}`}><i/>{health === 'ok' ? 'API online' : health ? 'API unavailable' : 'Connecting'}</span><button className="icon-button" onClick={checkBackend} aria-label="Refresh API status"><RefreshCw size={16}/></button><div className="avatar">RT</div></div></header>
      <div className="content">
        {error && <div className="error-banner"><TriangleAlert size={18}/><div><strong>Request didn’t complete</strong><span>{error}</span>{error.includes('401') && <small>Production API ko key chahiye. API connection settings mein X-API-Key add karo. Public app mein shared secret expose nahi karna chahiye.</small>}</div><button onClick={() => setError('')}>×</button></div>}
        {health === 'ok' && !settings.apiKey && !error && <div className="api-key-notice"><ShieldCheck size={17}/><span><strong>Backend reachable.</strong> Protected range APIs ke liye production API key connect karo.</span><button onClick={() => setPage('settings')}>API connection <ArrowRight size={14}/></button></div>}

        {page === 'overview' && <>
          <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot"/> RANGE INTELLIGENCE</div><h1>Your range, <em>recalculated.</em></h1><p>Know what’s left in the battery—and what the road ahead will take.</p></div><button className="outline-button" onClick={() => setPage('settings')}><Settings2 size={16}/> API settings</button></section>
          <div className="demo-note"><Sparkles size={16}/><span>Using the <strong>public scooter data proxy</strong> for this estimate. Treat the result as a general estimate.</span></div>
          <div className="dashboard-grid">
            <section className="panel planner-panel"><div className="panel-heading"><div><div className="panel-kicker">PLAN A ROUTE</div><h2>Where are you headed?</h2></div><div className="route-icon"><Route size={18}/></div></div>
              <form onSubmit={runRoute}>
                <div className="field-row"><Field label="Battery charge" value={route.soc_percent} onChange={v=>setRouteValue('soc_percent',v)} min="0" max="100" suffix="%" required/><Field label="Battery temperature" value={route.temp_c} onChange={v=>setRouteValue('temp_c',v)} min="-30" max="60" suffix="°C" required/><Field label="Cycle count" value={route.cycles_used} onChange={v=>setRouteValue('cycles_used',v)} min="0" suffix="cycles"/></div>
                <div className="route-divider"><span>ROUTE</span><button type="button" onClick={() => { if (coordMode === 'map') setCoordMode('manual'); else { selectDemoRoute(DEMO_ROUTES[0]); setCoordMode('map'); } }}>{coordMode === 'map' ? 'Edit coordinates' : 'Use BHU demo route'}</button></div>
                <div className="demo-route-options" aria-label="Demo routes">{DEMO_ROUTES.map(preset => <button key={preset.id} type="button" className={demoRoute === preset.id ? 'selected' : ''} onClick={() => selectDemoRoute(preset)}>{preset.label}</button>)}</div>
                <div className="route-fields"><div className="route-point"><div className="pin start"><MapPin size={16}/></div><div className="route-location"><label>STARTING POINT</label><strong>{coordMode === 'map' ? 'BHU, Varanasi' : (DEMO_ROUTES.find(preset => preset.id === demoRoute)?.start || 'Custom start coordinates')}</strong></div>{coordMode === 'manual' && <div className="coord-fields"><input aria-label="Start latitude" value={route.start_lat} onChange={e=>setRouteValue('start_lat',e.target.value)}/><input aria-label="Start longitude" value={route.start_lon} onChange={e=>setRouteValue('start_lon',e.target.value)}/></div>}</div><div className="route-track"/><div className="route-point"><div className="pin end"><MapPin size={16}/></div><div className="route-location"><label>DESTINATION</label><strong>{coordMode === 'map' ? 'Varanasi, Uttar Pradesh' : (DEMO_ROUTES.find(preset => preset.id === demoRoute)?.end || 'Custom destination coordinates')}</strong></div>{coordMode === 'manual' && <div className="coord-fields"><input aria-label="End latitude" value={route.end_lat} onChange={e=>setRouteValue('end_lat',e.target.value)}/><input aria-label="End longitude" value={route.end_lon} onChange={e=>setRouteValue('end_lon',e.target.value)}/></div>}</div></div>
                <div className="field-row lower-fields"><Field label="Trip distance (fallback)" value={route.trip_km} onChange={v=>setRouteValue('trip_km',v)} min="0.5" step="0.1" suffix="km" hint="Used for quick estimate; route distance wins."/><label className="field"><span>Road profile</span><select value={route.route} onChange={e=>setRouteValue('route',e.target.value)}><option value="flat">Mostly flat</option><option value="rolling">Rolling</option><option value="hill">Hilly</option></select></label><Field label="Safety reserve" value={route.safety_margin} onChange={v=>setRouteValue('safety_margin',v)} min="0.05" max="0.3" step="0.025" suffix="fraction" hint="0.175 = 17.5% reserve"/></div>
                <div className="field-row load-fields"><Field label="Rider weight" value={route.rider_kg} onChange={v=>setRouteValue('rider_kg',v)} min="20" max="200" suffix="kg"/><Field label="Vehicle + cargo" value={route.vehicle_kg} onChange={v=>setRouteValue('vehicle_kg',v)} min="5" max="400" suffix="kg"/><div className="form-hint"><CircleHelp size={14}/> Range uses the public scooter data proxy.</div></div>
                <div className="planner-footer"><span><ShieldCheck size={15}/> Road route: OpenStreetMap · Elevation: Open-Meteo / Copernicus</span><div className="planner-buttons"><button className="primary-button" disabled={busy}>{busy ? <><span className="spinner"/> Calculating</> : <>Calculate route range <ArrowRight size={16}/></>}</button></div></div>
              </form>
            </section>

            <section className="range-panel"><div className="range-panel-top"><div className="panel-kicker">ESTIMATED RANGE</div><div className="range-status"><span className="status-dot"/>{result ? (result.verdict === 'reachable' ? 'Route reachable' : 'Not enough range') : 'Ready to calculate'}</div></div><div className="range-number">{result ? fmt(result.real_range_km) : '—'}<span>km</span></div><div className="range-caption">estimated real-world range</div><div className="range-bar"><div style={{width:`${result ? Math.min(100, (result.real_range_km / Math.max(result.dashboard_range_km,1))*100) : 0}%`}}/></div><div className="range-bar-labels"><span>0 km</span><span>{result ? `${fmt(result.dashboard_range_km,0)} km dashboard` : 'Dashboard range'}</span></div><div className="range-stats"><div><span>Safe range</span><strong>{result ? `${fmt(result.safe_range_km)} km` : '—'}</strong></div><div><span>Road distance</span><strong>{result ? `${fmt(result.route_distance_km ?? result.route_km,2)} km` : '—'}</strong></div><div><span>Arrival reserve</span><strong>{result ? `${fmt(result.energy_left_on_arrival_wh)} Wh` : '—'}</strong></div></div><div className={`reachability ${result?.can_reach ? 'good' : result ? 'bad' : ''}`}><div className="reach-icon">{result ? (result.can_reach ? <Check size={16}/> : <TriangleAlert size={16}/>) : <Compass size={16}/>}</div><div><strong>{result ? (result.can_reach ? 'You should make it' : 'Route may exceed available range') : 'Set your route to begin'}</strong><span>{result ? `About ${fmt(result.energy_needed_wh)} Wh used on this route` : 'We’ll factor in battery, load and elevation.'}</span></div></div></section>
          </div>

          {result && <><div className="section-title"><div><h2>Trip estimate</h2><p>Route-aware prediction based on your current inputs.</p></div><span className="updated-label"><Clock3 size={14}/> Just calculated</span></div><div className="metric-grid"><Metric icon={Battery} label="Usable energy" value={`${fmt(result.usable_energy_wh,0)} Wh`} sub={`${fmt(result.usable_fraction*100,0)}% battery health`} color="green"/><Metric icon={Zap} label="Trip energy" value={`${fmt(result.energy_needed_wh,1)} Wh`} sub={`${fmt(result.avg_wh_per_km_on_route,1)} Wh per km`} color="amber"/><Metric icon={ArrowDownRight} label="Energy at arrival" value={`${fmt(result.energy_left_on_arrival_wh,1)} Wh`} sub={`${fmt(result.reserve_wh,1)} Wh safety reserve`} color="blue"/><Metric icon={Gauge} label="Range sensitivity" value={result.range_sensitivity_km ? `${fmt(result.range_sensitivity_km.lower)}–${fmt(result.range_sensitivity_km.upper)} km` : `${fmt(result.real_range_km)} km`} sub={result.range_sensitivity_km ? 'Public trip variation, not a guarantee' : 'Estimate based on provided baseline'} color="purple"/></div>
          <div className="detail-grid"><section className="panel elevation-panel"><div className="panel-heading"><div><div className="panel-kicker">ROAD PROFILE</div><h2>Elevation along your route</h2><p className="chart-source">{result.elevation_source || 'Open-Meteo (Copernicus GLO-90)'} · {fmt(result.route_distance_km ?? result.route_km,2)} km route</p></div><span className="mini-chip"><Activity size={13}/> {Math.max(0, elevation.length - 1)} segments</span></div><div className="elevation-chart"><div className="chart-labels"><span>{fmt(maxElevation,0)} m</span><span>{fmt((minElevation + maxElevation) / 2,0)} m</span><span>{fmt(minElevation,0)} m</span></div><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Terrain elevation in meters above sea level along the selected road route"><line x1="0" y1="10" x2="100" y2="10" stroke="#52708e" strokeWidth="1" strokeDasharray="2 2" vectorEffect="non-scaling-stroke"/><line x1="0" y1="50" x2="100" y2="50" stroke="#52708e" strokeWidth="1" strokeDasharray="2 2" vectorEffect="non-scaling-stroke"/><line x1="0" y1="90" x2="100" y2="90" stroke="#52708e" strokeWidth="1" strokeDasharray="2 2" vectorEffect="non-scaling-stroke"/><polyline points={elevationPoints} fill="none" stroke="#42c995" strokeWidth="1.7" vectorEffect="non-scaling-stroke"/></svg></div><div className="chart-footer"><span><i className="legend-dot"/>Elevation above sea level</span><span>{fmt(minElevation,0)}–{fmt(maxElevation,0)} m · {fmt(stepKm,2)} km/sample</span></div></section><section className="panel breakdown-panel"><div className="panel-heading"><div><div className="panel-kicker">RANGE FACTORS</div><h2>What changes your range</h2></div><CircleHelp size={17} className="muted-icon"/></div><Breakdown label="Battery age & temperature" value={result.range_lost_km?.battery_age_and_temperature} max={Math.max(result.real_range_km,1)} icon={Battery}/><Breakdown label="Rider & vehicle load" value={result.range_lost_km?.load} max={Math.max(result.real_range_km,1)} icon={Bike}/><Breakdown label="Route terrain" value={result.range_lost_km?.terrain} max={Math.max(result.real_range_km,1)} icon={Activity}/><div className="baseline-note"><Leaf size={15}/><span>Baseline: <strong>{result.consumption_baseline?.replaceAll('_',' ') || 'vehicle estimate'}</strong>{result.vehicle_profile?.note && <small>{result.vehicle_profile.note}</small>}</span></div></section></div></>}
          {!result && <div className="empty-hint"><div className="empty-icon"><Route size={23}/></div><div><strong>Your route estimate will appear here</strong><span>Choose charge level, route and vehicle condition, then calculate.</span></div><ArrowRight size={17}/></div>}
        </>}

        {page === 'battery' && <><PageTitle eyebrow="LIVE INPUTS" title="Battery status" subtitle="Send a BMS or dashboard reading to the backend. The API reports power direction and does not infer charge from voltage."/><div className="tool-layout"><section className="panel tool-panel"><PanelTitle icon={Battery} title="Submit a battery reading" description="Use positive current while discharging and negative current during regeneration."/><form onSubmit={submitStatus}><div className="field-row"><FormField name="voltage_v" label="Voltage" initial="48" suffix="V" min="0.01" required/><FormField name="current_a" label="Current" initial="2.5" suffix="A" required/><FormField name="temp_c" label="Battery temperature" initial="25" suffix="°C" required/><FormField name="soc_percent" label="State of charge" initial="80" suffix="%" min="0" max="100" required/></div><button className="primary-button" disabled={busy}>{busy?'Sending…':<>Send reading <ArrowRight size={16}/></>}</button></form></section><section className="panel result-panel"><div className="panel-kicker">LATEST RESPONSE</div>{statusResult ? <><div className="result-highlight"><Zap size={18}/><strong>{fmt(statusResult.power_w,1)} W</strong><span>{statusResult.state}</span></div><ResultRows data={statusResult} omit={['sampled_at']}/></> : <ResultPlaceholder text="Submit a reading to see normalized power and battery state."/>}</section></div></>}

        {page === 'reestimate' && <><PageTitle eyebrow="ON THE ROAD" title="Re-estimate your trip" subtitle="Compare actual energy used so far with the route prediction and get a revised trip estimate."/><div className="tool-layout"><section className="panel tool-panel"><PanelTitle icon={RefreshCw} title="Update trip progress" description="This endpoint uses your selected vehicle profile and baseline with actual distance and energy used."/><form onSubmit={submitReEstimate}><div className="field-row"><FormField name="trip_km" label="Planned trip distance" initial={route.trip_km} suffix="km" min="0.5" required/><FormField name="km_done" label="Distance completed" initial="2" suffix="km" min="0" required/><FormField name="wh_used" label="Energy used so far" initial="45" suffix="Wh" min="0" required/></div><div className="form-hint"><CircleHelp size={15}/> Route planner inputs (SOC, profile, temperature) are reused from Range overview.</div><button className="primary-button" disabled={busy}>{busy?'Re-estimating…':<>Re-estimate range <ArrowRight size={16}/></>}</button></form></section><section className="panel result-panel"><div className="panel-kicker">REVISED ESTIMATE</div>{reEstimateResult ? <><div className="result-highlight"><Gauge size={18}/><strong>{fmt(reEstimateResult.real_range_km)} km</strong><span>real range</span></div><ResultRows data={reEstimateResult} omit={['profile','model','vehicle_profile','range_sensitivity_km']}/></> : <ResultPlaceholder text="Your revised estimate will show here after the calculation."/>}</section></div></>}

        {page === 'settings' && <><PageTitle eyebrow="CONFIGURATION" title="API connection" subtitle="Point this dashboard at your local or deployed FastAPI service."/><div className="tool-layout settings-layout"><section className="panel tool-panel"><PanelTitle icon={Settings2} title="Backend address" description="For your local backend, keep http://localhost:8000. The backend must allow this frontend origin in CORS."/><form onSubmit={saveSettings}><label className="field"><span>API base URL</span><input type="url" value={settings.baseUrl} onChange={e=>setSettings({...settings,baseUrl:e.target.value})} placeholder="http://localhost:8000" required/></label><label className="field"><span>API key <small className="optional">(only if your API requires one)</small></span><input type="password" autoComplete="off" value={settings.apiKey} onChange={e=>setSettings({...settings,apiKey:e.target.value})} placeholder="X-API-Key"/><em>Kept in this browser session only. Never commit or bake this key into a public frontend. A public app needs user authentication or a backend proxy.</em></label><div className="settings-actions"><button className="primary-button">Save and connect <ArrowRight size={16}/></button><button className="outline-button" type="button" onClick={checkBackend}><RefreshCw size={15}/> Check connection</button></div></form></section><section className="panel info-panel"><div className="panel-kicker">CONNECTION STATUS</div><div className={`status-large ${health==='ok'?'good':''}`}><span className="pulse"/>{health === 'ok' ? 'Connected' : health === 'degraded' ? 'Connected, model unavailable' : 'Not connected'}</div><div className="status-url">{settings.baseUrl}</div><div className="info-divider"/><div className="endpoint-list"><strong>Endpoints used by this UI</strong>{['GET /health','GET /vehicle-profiles','POST /route-range','POST /battery/status','POST /re-estimate'].map(x=><span key={x}><Check size={13}/>{x}</span>)}</div></section></div><div className="security-callout"><ShieldCheck size={18}/><div><strong>Production key safety</strong><span>A browser app cannot keep a shared API secret private. This screen sends a key entered by the user for private demos, but for a public frontend, put authenticated users or a server-side proxy in front of the protected API.</span></div></div></>}

        <footer className="footer"><span>RANGETRUE <b>•</b> EV RANGE ESTIMATES</span><span><ShieldCheck size={13}/> Estimates are informational; actual range varies.</span></footer>
      </div>
    </main>
  </div>;
}

function PageTitle({eyebrow,title,subtitle}) { return <section className="page-heading subpage-heading"><div><div className="eyebrow"><span className="eyebrow-dot"/> {eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div></section>; }
function Metric({icon:Icon,label,value,sub,color}) { return <div className="metric-card"><div className={`metric-icon ${color}`}><Icon size={17}/></div><div><span>{label}</span><strong>{value}</strong><small>{sub}</small></div></div>; }
function Breakdown({label,value,max,icon:Icon}) { const n = Number(value)||0; return <div className="breakdown-row"><div className="breakdown-icon"><Icon size={15}/></div><div className="breakdown-content"><div><span>{label}</span><strong>{fmt(n)} km</strong></div><div className="breakdown-bar"><i style={{width:`${Math.min(100,n/max*100)}%`}}/></div></div></div>; }
function FormField({name,label,initial,type='number',suffix,min,max,step,required}) { return <label className="field"><span>{label}{required && <b className="required"> *</b>}</span><div className="input-wrap"><input name={name} type={type} defaultValue={initial} min={min} max={max} step={step ?? (type === 'number' ? 'any' : undefined)} required={required}/>{suffix && <small>{suffix}</small>}</div></label>; }
function PanelTitle({icon:Icon,title,description}) { return <div className="tool-title"><div className="tool-icon"><Icon size={18}/></div><div><h2>{title}</h2><p>{description}</p></div></div>; }
function ResultRows({data,omit=[]}) { return <div className="result-rows">{Object.entries(data).filter(([k,v])=>!omit.includes(k)&&v!==null&&typeof v!=='object').map(([k,v])=><div key={k}><span>{k.replaceAll('_',' ')}</span><strong>{String(v)}</strong></div>)}</div>; }
function ResultPlaceholder({text}) { return <div className="result-placeholder"><div><Activity size={21}/></div><p>{text}</p></div>; }

createRoot(document.getElementById('root')).render(<App/>);
