/* Registry-generated, read-only dashboard. No device calls or service actions. */
(() => {
  const DOMAIN = 'ventaxia_econiq_readonly';
  const ROLLING = ['recovery_mean_1h','recovery_mean_24h','recovery_median_24h',
    'recovery_minimum_24h','recovery_maximum_24h','recovery_sd_24h',
    'recovery_p10_24h','recovery_p90_24h','recovery_samples_24h',
    'recovery_coverage_1h','recovery_coverage_24h','recovery_oldest_sample',
    'recovery_newest_sample','lift_mean_24h','lift_minimum_24h','lift_maximum_24h'];
  const KEYS = new Set(['supply_rpm','extract_rpm','outdoor_temperature','supply_temperature',
    'indoor_temperature','internal_humidity','external_humidity','system_power','co2',
    'supply_airflow','extract_airflow','supply_measured_airflow','extract_measured_airflow',
    'filter_1_remaining','filter_2_remaining','airflow_preset','faults','warnings','notices',
    'override','regulation','wifi_signal','bypass_status','frost_status','supply_motor_power',
    'extract_motor_power','supply_motor_runtime','extract_motor_runtime','unit_runtime',
    'filter_last_change','filter_interval','service_last','service_interval','filter_1_type',
    'filter_2_type','model_details','wifi_firmware','wifi_hardware','air_quality','unit_name',
    'connection','last_telemetry','last_reading','started_at','bridge_started','reconnects',
    'received_messages','received_mqtt_bytes','sent_mqtt_bytes','ping_replies',
    'recovery_ratio','temperature_lift','available_temperature_difference',
    'remaining_temperature_difference','recovery_status', ...ROLLING]);
  const ALIASES = {
    recovery_ratio:'sensor.mvhr_apparent_temperature_recovery',
    temperature_lift:'sensor.mvhr_supply_temperature_lift',
    available_temperature_difference:'sensor.mvhr_available_temperature_difference',
    remaining_temperature_difference:'sensor.mvhr_remaining_temperature_difference',
    recovery_status:'sensor.mvhr_recovery_calculation_status',
    energy_today:'sensor.mvhr_energy_today', energy_month:'sensor.mvhr_energy_this_month',
    ...Object.fromEntries(ROLLING.map(key => [key, `sensor.mvhr_${key}`])),
    recovery_oldest_sample:'sensor.mvhr_recovery_oldest_sample_24h',
  };
  const LABELS = {co2:'CO₂', supply_rpm:'Supply fan speed', extract_rpm:'Extract fan speed', wifi_signal:'Wi-Fi signal', internal_humidity:'Intake humidity', external_humidity:'Extract humidity',
    recovery_ratio:'Apparent temperature recovery', temperature_lift:'Supply temperature lift',
    supply_airflow:'Supply demand (raw)',
    extract_airflow:'Extract demand (raw)',
    supply_measured_airflow:'Supply measured (raw)',
    extract_measured_airflow:'Extract measured (raw)',
    supply_motor_power:'Supply motor power',
    extract_motor_power:'Extract motor power',
    energy_today:'Electrical energy today', energy_month:'Electrical energy this month'};
  const label = key => LABELS[key] || key.replaceAll('_', ' ').replace(/^./, c => c.toUpperCase());
  const note = content => ({type:'markdown', content});
  const missing = () => note('No enabled readings in this section. Optional entities may need enabling, or the unit has not reported them.');

  function discover(devices, entities) {
    return devices.filter(d => !d.disabled_by).flatMap(device => {
      const ids = device.identifiers || [];
      const native = ids.find(i => Array.isArray(i) && i[0] === DOMAIN);
      const old = ids.find(i => Array.isArray(i) && i[0] === 'mqtt' && typeof i[1] === 'string' && i[1].startsWith('ventaxia_readonly_'));
      if (!native && !old) return [];
      const unit = native ? native[1] : old[1].slice('ventaxia_readonly_'.length);
      if (typeof unit !== 'string' || !unit) return [];
      const prefix = native ? `${unit}_` : `ventaxia_readonly_${unit}_`;
      const map = {};
      for (const entity of entities) {
        if (entity.device_id !== device.id || entity.disabled_by || entity.hidden_by ||
            !/^(sensor|binary_sensor)\./.test(entity.entity_id || '') ||
            typeof entity.unique_id !== 'string' || !entity.unique_id.startsWith(prefix)) continue;
        const key = entity.unique_id.slice(prefix.length);
        if (KEYS.has(key)) map[key] = entity.entity_id;
      }
      return [{device, unit, legacy:!native, map}];
    });
  }

  function unitViews(unit, allCount, hass, index, showUnit) {
    const e = {...unit.map};
    if (unit.legacy && allCount === 1) {
      for (const [key, entity] of Object.entries(ALIASES)) {
        if (!e[key] && hass.states?.[entity]) e[key] = entity;
      }
    }
    const group = (title, keys, attrs = []) => {
      const rows = keys.filter(k => e[k]).map(k => ({entity:e[k], name:label(k)}));
      for (const [key, attribute, name] of attrs) {
        if (e[key]) rows.push({type:'attribute', entity:e[key], attribute, name});
      }
      return rows.length ? {type:'entities', title, show_header_toggle:false, entities:rows} : missing();
    };
    const graph = (title, keys, hours = 24) => {
      const entries = keys.filter(k => e[k]).map(k => ({entity:e[k], name:label(k)}));
      return entries.length ? {type:'history-graph', title, hours_to_show:hours, entities:entries} : missing();
    };
    const title = unit.device.name_by_user || unit.device.name || 'Ventilation unit';
    const view = (name, cards, icon) => ({title:showUnit ? `${title} · ${name}` : name,
      path:showUnit ? `${unit.device.id}-${name.toLowerCase()}` : name.toLowerCase(), cards});
    const statsNote = unit.legacy
      ? 'Legacy helpers are shown only when exactly one compatible unit exists. Their windows and sampling depend on the helper configuration; history is not migrated. Any sample-span coverage below is approximate, not elapsed-time availability.'
      : 'Native statistics use one-minute samples. Means are means of minute samples; median, standard deviation and percentiles use those samples. P10/P90 remain unavailable below 20 valid samples. Rolling coverage describes sample coverage, not certified performance.';
    const coverageAttrs = [];
    if (unit.legacy && allCount === 1) {
      coverageAttrs.push(['recovery_mean_1h','age_coverage_ratio','Approximate 1 h sample-span coverage'],
        ['recovery_mean_24h','age_coverage_ratio','Approximate 24 h sample-span coverage']);
    }
    return [
      view('Overview', [
        note('## Ventilation telemetry\nReported states and measurements only. Missing or unavailable data does not prove that hardware is off or fault-free.'),
        group('Current operation', ['connection','airflow_preset','override','regulation','bypass_status','frost_status','air_quality']),
        group('Temperatures', ['outdoor_temperature','supply_temperature','indoor_temperature','internal_humidity','external_humidity','co2']),
        graph('Temperature history', ['outdoor_temperature','supply_temperature','indoor_temperature']),
        group('Fans and power', ['supply_rpm','extract_rpm','system_power','supply_motor_power','extract_motor_power','energy_today','energy_month']),
        group('Airflow · unverified units', ['supply_airflow','extract_airflow','supply_measured_airflow','extract_measured_airflow']),
      ], 'mdi:fan'),
      {...view('Statistics', [
        {type:'custom:ventaxia-econiq-analytics', entities:Object.fromEntries(ANALYTIC_KEYS.filter(k=>e[k]).map(k=>[k,e[k]]))},
        note('## Apparent temperature recovery\n100 × (supply − outdoor) / (extract − outdoor). The calculation requires |extract − outdoor| ≥ 3 K and valid inputs. It is not certified heat-exchanger efficiency. Interpret alongside reported bypass/frost status; unavailable status does not establish bypass closure. No recovered W or kWh is calculated while airflow units remain unverified.'),
        group('Current calculation', ['recovery_status','recovery_ratio','temperature_lift','available_temperature_difference','remaining_temperature_difference']),
        graph('Recovery ratio history', ['recovery_ratio','recovery_mean_1h','recovery_mean_24h']),
        note(statsNote),
        group('Recovery distribution', ['recovery_mean_1h','recovery_mean_24h','recovery_median_24h','recovery_minimum_24h','recovery_maximum_24h','recovery_sd_24h']),
        ...(e.recovery_samples_24h && (e.recovery_p10_24h || e.recovery_p90_24h) ? [{type:'conditional',
          conditions:[{condition:'numeric_state', entity:e.recovery_samples_24h, above:19}],
          card:group('Percentiles — at least 20 samples', ['recovery_p10_24h','recovery_p90_24h'])}] : []),
        group('Sample quality and coverage', ['recovery_samples_24h','recovery_coverage_1h','recovery_coverage_24h','recovery_oldest_sample','recovery_newest_sample'], coverageAttrs),
        group('Supply temperature lift', ['lift_mean_24h','lift_minimum_24h','lift_maximum_24h']),
      ].map(card => card && ['entities','conditional'].includes(card.type)
        ? {...card, view_layout:{position:'sidebar'}} : card), 'mdi:chart-line'), type:'sidebar'},
      view('Diagnostics', [
        group('Communication', ['connection','last_telemetry','last_reading','started_at','bridge_started','reconnects','wifi_signal','received_messages','received_mqtt_bytes','sent_mqtt_bytes','ping_replies']),
        group('Reported alert flags', ['faults','warnings','notices'], ['faults','warnings','notices'].flatMap(k => [
          [k,'codes',`${label(k)} codes`], [k,'raw_hex',`${label(k)} raw mask`],
          [k,'unknown_bits_hex',`${label(k)} unknown bits`]])),
        group('Reported override', ['override'], [['override','reported_source_id','Source ID (not a preset)'],
          ['override','reported_started_at','Reported start timestamp'], ['override','requested_duration','Requested duration'],
          ['override','requested_seconds','Requested duration (seconds)']]),
        group('Bypass and frost details', ['bypass_status','frost_status'], [
          ['bypass_status','percent_open','Reported opening (%)'], ['bypass_status','operating_mode','Reported bypass operating mode'],
          ['frost_status','power_raw','Frost power reading — unit unverified'], ['frost_status','usage_raw','Frost usage reading — unit unverified']]),
        note('Alert masks show only what the unit reported. Unknown code bits are preserved. A cause, source ID or requested duration does not establish the effective fan preset.'),
      ], 'mdi:stethoscope'),
      view('Maintenance', [
        group('Filter information', ['filter_1_type','filter_2_type','filter_last_change','filter_interval','filter_1_remaining','filter_2_remaining']),
        group('Service and runtime', ['service_last','service_interval','unit_runtime','supply_motor_runtime','extract_motor_runtime']),
        group('Hardware and software', ['unit_name','model_details','wifi_firmware','wifi_hardware'], [
          ['model_details','firmware_version','Mainboard firmware'], ['model_details','firmware_reported','Raw firmware value'],
          ['model_details','serial_number','Reported serial number'], ['model_details','model_code','Model code'],
          ['model_details','board_revision_id','Board revision ID'], ['model_details','manufacture_date_reported','Reported manufacture date']]),
        note('Dates and intervals are reported values; no service completion, filter reset or firmware action is provided. Motor/unit runtime is displayed in hours by the integration. Unverified maintenance units remain raw.'),
      ], 'mdi:clipboard-text-outline'),
    ];
  }

  const MINUTE = 60000;
  const DAY = 1440 * MINUTE;
  const MODES = ['Low', 'Normal', 'Boost', 'Purge', 'Maximum', 'Off', 'Unknown'];
  const COLORS = ['#38bdf8','#2dd4bf','#f59e0b','#c084fc','#f472b6','#94a3b8','#64748b'];
  const PLOTS = [
    ['scatter','Temperature lift vs. indoor–outdoor difference'],
    ['distribution','Apparent recovery by mode'],
    ['boost','Boost event profiles'],
    ['heatmap','Temperature lift by hour'],
    ['drift','Normal-mode performance drift'],
    ['energy','Fan electricity by mode'],
  ];
  const ANALYTIC_KEYS = ['connection','last_telemetry','last_reading','airflow_preset','outdoor_temperature',
    'supply_temperature','indoor_temperature','supply_rpm','extract_rpm','external_humidity','system_power',
    'bypass_status','frost_status'];
  const numeric = value => typeof value === 'string' && value.trim() && Number.isFinite(Number(value)) ? Number(value) : null;
  const groupBy = (items, key) => {
    const map = new Map();
    for (const item of items) {
      const k = key(item);
      if (!map.has(k)) map.set(k, []);
      map.get(k).push(item);
    }
    return map;
  };
  function quantiles(values, fractions) {
    const sorted = [...values].sort((a,b) => a-b);
    return fractions.map(p => {
      const i = (sorted.length-1)*p, j = Math.floor(i);
      return sorted[j] + (sorted[Math.min(j+1, sorted.length-1)]-sorted[j])*(i-j);
    });
  }

  function minuteHistory(history, entities, start, end, zone) {
    const series = Object.fromEntries(Object.entries(entities).map(([key,id]) => {
      const values = (history[id] || []).flatMap(row => {
        const t = row.lu ?? row.lc ?? row.last_updated ?? row.last_changed;
        const time = typeof t === 'number' ? t * 1000 : Date.parse(t);
        return Number.isFinite(time) ? [[time, row.s ?? row.state]] : [];
      }).sort((a,b) => a[0]-b[0]);
      return [key, {values, index:0}];
    }));
    const format = new Intl.DateTimeFormat('en-GB', {timeZone:zone, year:'numeric', month:'2-digit',
      day:'2-digit', hour:'2-digit', hourCycle:'h23'});
    const rows = [];
    for (let time = start + MINUTE/2; time < end; time += MINUTE) {
      const get = key => {
        const s = series[key];
        if (!s) return null;
        while (s.index < s.values.length && s.values[s.index][0] <= time) s.index++;
        return s.values[s.index-1]?.[1] ?? null;
      };
      const heartbeat = Date.parse(get(entities.last_telemetry ? 'last_telemetry' : 'last_reading'));
      const fresh = get('connection') === 'on' && Number.isFinite(heartbeat) &&
        time - heartbeat >= 0 && time - heartbeat <= 3*MINUTE;
      const preset = get('airflow_preset');
      const mode = MODES.includes(preset) ? preset : 'Unknown';
      const power = fresh ? numeric(get('system_power')) : null;
      const humidity = fresh ? numeric(get('external_humidity')) : null;
      const fans = numeric(get('supply_rpm')) > 0 && numeric(get('extract_rpm')) > 0;
      const [outdoor,supply,indoor] = ['outdoor_temperature','supply_temperature','indoor_temperature'].map(k => numeric(get(k)));
      const valid = fresh && fans && [outdoor,supply,indoor].every(v => v !== null);
      const lift = valid ? supply-outdoor : null;
      const delta = valid ? indoor-outdoor : null;
      const bypass = get('bypass_status'), frost = get('frost_status');
      const parts = Object.fromEntries(format.formatToParts(time).map(p => [p.type,p.value]));
      rows.push({time, day:`${parts.year}-${parts.month}-${parts.day}`, hour:Number(parts.hour),
        mode, fresh, power:power !== null && power >= 0 ? power : null,
        humidity:humidity !== null && humidity >= 0 && humidity <= 100 ? humidity : null,
        lift, delta, ratio:valid && delta >= 3 ? 100*lift/delta : null,
        standard:(!entities.bypass_status || bypass === 'Closed') && (!entities.frost_status || frost === 'Inactive')});
    }
    return rows;
  }

  const range = values => {
    let min = Infinity, max = -Infinity;
    for (const v of values) { min = Math.min(min,v); max = Math.max(max,v); }
    if (!Number.isFinite(min)) return [0,1];
    const pad = Math.max(0.05, (max-min)*0.07, min === max ? Math.abs(min)*0.08 : 0);
    return [min-pad,max+pad];
  };
  const dayLabel = day => day.slice(8)+'/'+day.slice(5,7);
  const color = mode => COLORS[MODES.indexOf(mode)];
  const text = (x,y,value,anchor='middle') => `<text x="${x}" y="${y}" text-anchor="${anchor}">${value}</text>`;
  const line = (x1,y1,x2,y2,stroke='var(--divider-color, #8995a1)') =>
    `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}"/>`;
  const noData = message => `<p class="message">${message}</p>`;
  const legend = modes => `<div class="legend">${modes.map(m => `<span><i style="background:${color(m)}"></i>${m}</span>`).join('')}</div>`;
  const svg = (height,label,body) => `<svg viewBox="0 0 640 ${height}" role="img" aria-label="${label}">${body}</svg>`;
  function frame(xr, yr, xLabel, yLabel, draw, options={}) {
    const {height=300, labels, steps=4} = options;
    const left=58, right=614, top=23, bottom=height-49;
    const x = v => left+(v-xr[0])/(xr[1]-xr[0])*(right-left);
    const y = v => bottom-(v-yr[0])/(yr[1]-yr[0])*(bottom-top);
    let marks = '';
    for (let i=0;i<=4;i++) {
      const v=yr[0]+(yr[1]-yr[0])*i/4;
      marks += line(left,y(v),right,y(v))+text(left-8,y(v)+4,Number(v.toFixed(2)),'end');
    }
    if (labels) labels.forEach((label,i) => { marks += text(x(i),bottom+20,label); });
    else for (let i=0;i<=steps;i++) {
      const v=xr[0]+(xr[1]-xr[0])*i/steps;
      marks += text(x(v),bottom+20,Number(v.toFixed(1)));
    }
    marks += text(left,15,yLabel,'start') + text((left+right)/2,height-8,xLabel);
    return svg(height, yLabel+' versus '+xLabel, marks+draw(x,y,left,right,top,bottom));
  }

  function scatter(rows) {
    const good = rows.filter(r => r.ratio !== null && r.mode !== 'Unknown');
    if (!good.length) return noData('No valid heating-mode samples. This plot needs fresh temperatures, both fan speeds and a temperature difference of at least 3 K.');
    const groups = groupBy(good,r=>r.mode);
    const points = [...groups.values()].flatMap(g => g.filter((_,i)=>i%Math.ceil(g.length/500)===0));
    return legend([...groups.keys()])+frame(range(good.map(r=>r.delta)),range(good.map(r=>r.lift)),
      'Indoor − outdoor (K)','Supply lift (K)',(x,y)=>points.map(r=>
        `<circle cx="${x(r.delta)}" cy="${y(r.lift)}" r="2.8" fill="${color(r.mode)}" opacity=".6"><title>${r.mode} · gap ${r.delta.toFixed(1)} K · lift ${r.lift.toFixed(1)} K</title></circle>`).join(''))+
      `<p class="caption">${good.length.toLocaleString()} valid minutes. Display thinned by mode. Compare points at similar temperature differences.</p>`;
  }

  function distribution(rows) {
    const grouped = groupBy(rows.filter(r=>r.ratio!==null && r.mode!=='Unknown'),r=>r.mode);
    const groups = MODES.filter(m=>(grouped.get(m)?.length || 0)>=20);
    if (!groups.length) return noData('At least 20 valid heating minutes in one mode are needed for percentiles.');
    const data = groups.map(m=>({m,n:grouped.get(m).length,q:quantiles(grouped.get(m).map(r=>r.ratio),[.1,.25,.5,.75,.9])}));
    return frame([-.6,groups.length-.4],range(data.flatMap(g=>g.q)),'Reported mode','Apparent recovery (%)',(x,y)=>
      data.map(({m,n,q:[lo,q1,med,q3,hi]},i)=>{
        const cx=x(i);
        return line(cx,y(lo),cx,y(hi),color(m))+line(cx-10,y(lo),cx+10,y(lo),color(m))+
          line(cx-10,y(hi),cx+10,y(hi),color(m))+
          `<rect x="${cx-20}" y="${y(q3)}" width="40" height="${Math.max(1,y(q1)-y(q3))}" fill="${color(m)}" opacity=".55"><title>${m}: ${n} minutes, median ${med.toFixed(1)}%, P10–P90 ${lo.toFixed(1)}–${hi.toFixed(1)}%</title></rect>`+
          line(cx-20,y(med),cx+20,y(med),color(m));
      }).join(''),{labels:groups})+
      '<p class="caption">Box P25–P75, line median, whiskers P10–P90. Mode comparisons include different weather and operating conditions.</p>';
  }

  function boost(rows) {
    const starts = [];
    rows.forEach((r,i) => {
      const previous = rows[i-1];
      if (r.fresh && r.mode==='Boost' && previous?.fresh && !['Boost','Unknown'].includes(previous.mode)) starts.push(i);
    });
    const events = starts.filter((i,j)=>i>=15 && i+15<rows.length &&
      (j===0 || i-starts[j-1]>30) && (j===starts.length-1 || starts[j+1]-i>30));
    if (!events.length) return noData('No isolated Boost starts with a full ±15-minute window in this period.');
    return [['humidity','Extract humidity (%)'],['power','Electrical power (W)'],['lift','Supply lift (K)']].map(([key,label])=>{
      const complete = events.filter(i=>rows.slice(i-15,i+16).every(r=>r[key]!==null));
      if (!complete.length) return noData(label+' · no complete event windows');
      const profile = Array.from({length:31},(_,j)=>{
        const vals=complete.map(i=>rows[i+j-15][key]);
        return complete.length>=3 ? quantiles(vals,[.1,.5,.9]) : quantiles(vals,[.5,.5,.5]);
      });
      return frame([-15,15],range(profile.flat()),'Minutes from Boost start',label,(x,y,_,__,top,bottom)=>{
        const path = (index,reverse=false) => (reverse ? [...profile].reverse() : profile)
          .map((q,j)=>`${x(reverse ? 15-j : j-15)},${y(q[index])}`).join(' ');
        return line(x(0),top,x(0),bottom)+
          `<polygon points="${path(0)} ${path(2,true)}" fill="#2dd4bf" opacity=".20"/><polyline points="${path(1)}" fill="none" stroke="#2dd4bf" stroke-width="2"/>`;
      },{height:185,steps:6})+
        `<p class="caption">${complete.length} complete events · median${complete.length>=3?' and P10–P90 band':''}</p>`;
    }).join('');
  }

  function heatmap(rows) {
    const byDay = groupBy(rows,r=>r.day);
    const cells = [...byDay].flatMap(([day,minutes],i)=>[...groupBy(minutes,r=>r.hour)].flatMap(([hour,samples])=>{
      const valid=samples.filter(r=>r.lift!==null);
      return valid.length>=30 ? [{day,i,hour,n:valid.length,mean:valid.reduce((sum,r)=>sum+r.lift,0)/valid.length}] : [];
    }));
    if (!cells.length) return noData('No hourly bins with at least 30 valid temperature-lift minutes.');
    const [min,max]=range(cells.map(c=>c.mean)), width=23, height=24, left=57;
    const labels=[...byDay.keys()].map((day,i)=>text(left-7,51+i*height,dayLabel(day),'end')).join('');
    const hours=Array.from({length:8},(_,i)=>text(left+i*3*width+width/2,25,String(i*3).padStart(2,'0'))).join('');
    const marks=cells.map(c=>`<rect x="${left+c.hour*width}" y="${34+c.i*height}" width="21" height="21" fill="#2dd4bf" opacity="${.18+.82*(c.mean-min)/(max-min)}"><title>${dayLabel(c.day)} at ${c.hour}:00 · ${c.mean.toFixed(2)} K · ${c.n} valid minutes</title></rect>`).join('');
    return svg(66+byDay.size*height,'Mean supply temperature lift by local day and hour',hours+labels+marks+
      text(333,52+byDay.size*height,'Local hour · mean supply lift (K)'))+
      `<p class="caption">Scale ${Math.min(...cells.map(c=>c.mean)).toFixed(1)} to ${Math.max(...cells.map(c=>c.mean)).toFixed(1)} K. Blank hours have fewer than 30 valid minutes.</p>`;
  }

  function drift(rows, baseline) {
    const select = r => r.mode==='Normal' && r.ratio!==null && r.standard;
    const bins=groupBy(baseline.filter(select),r=>Math.floor(r.delta));
    const expected = new Map([...bins].flatMap(([k,v])=>
      v.length>=60 && new Set(v.map(r=>r.day)).size>=2 ? [[k,quantiles(v.map(r=>r.lift),[.5])[0]]] : []));
    const byDay=groupBy(rows,r=>r.day);
    const values=[...byDay].map(([day,minutes])=>{
      const residuals=minutes.filter(r=>select(r) && expected.has(Math.floor(r.delta)))
        .map(r=>r.lift-expected.get(Math.floor(r.delta)));
      return {day,n:residuals.length,q:residuals.length>=30 ? quantiles(residuals,[.1,.5,.9]) : null};
    });
    if (!values.some(d=>d.q)) return noData('No qualifying Normal-mode days overlap the baseline temperature bins yet.');
    return frame([-.6,values.length-.4],range([0,...values.flatMap(d=>d.q || [])]),'Date','Lift versus baseline (K)',(x,y,left,right)=>
      line(left,y(0),right,y(0))+values.map((d,i)=>d.q ? line(x(i),y(d.q[0]),x(i),y(d.q[2]),'#2dd4bf')+
        `<circle cx="${x(i)}" cy="${y(d.q[1])}" r="5" fill="#2dd4bf"><title>${dayLabel(d.day)} · median ${d.q[1].toFixed(2)} K · ${d.n} matched minutes</title></circle>` : '').join(''),
      {labels:values.map(d=>dayLabel(d.day))})+
      '<p class="caption">Daily median and P10–P90 vs. the preceding seven days, matched in 1 K indoor–outdoor bins. Baseline needs ≥60 minutes across ≥2 dates per bin. Each dot needs ≥30 matched minutes. Bypass and frost excluded where their histories are available as entities.</p>';
  }

  function energy(rows) {
    const days=[...groupBy(rows,r=>r.day)].map(([day,minutes])=>{
      const good=minutes.filter(r=>r.power!==null);
      const sums=new Map([...groupBy(good,r=>r.mode)].map(([mode,group])=>[mode,group.reduce((sum,r)=>sum+r.power/60000,0)]));
      return {day,sums,n:good.length,total:minutes.length,kwh:[...sums.values()].reduce((a,b)=>a+b,0)};
    });
    if (!days.some(d=>d.n)) return noData('No fresh, valid electrical-power samples in this period.');
    const modes=MODES.filter(m=>days.some(d=>d.sums.has(m)));
    return legend(modes)+frame([-.6,days.length-.4],[0,Math.max(.01,...days.map(d=>d.kwh))*1.12],'Date','Electrical energy (kWh)',(x,y)=>
      days.map((d,i)=>{
        let sum=0;
        return modes.map(mode=>{
          const value=d.sums.get(mode)||0;
          const bottom=y(sum);
          sum+=value;
          return value>0 ? `<rect x="${x(i)-18}" y="${y(sum)}" width="36" height="${bottom-y(sum)}" fill="${color(mode)}"><title>${dayLabel(d.day)} · ${mode} · ${value.toFixed(3)} kWh · ${d.n}/${d.total} observed minutes</title></rect>` : '';
        }).join('');
      }).join(''),{labels:days.map(d=>dayLabel(d.day))})+
      '<p class="caption">One-minute estimate from reported electrical watts. Unknown mode is shown separately. Missing power or stale telemetry contributes no estimate. First and last dates may be partial.</p>';
  }

  class VentaxiaEconiqAnalytics extends HTMLElement {
    setConfig(config) {
      this.entities=Object.fromEntries(ANALYTIC_KEYS.filter(k=>config.entities?.[k]).map(k=>[k,config.entities[k]]));
      if (this.shadowRoot) return;
      this.attachShadow({mode:'open'}).innerHTML=`
        <style>
          ha-card{display:block;padding:18px} h2{font-size:1.2rem;margin:0 0 10px}
          .controls,.legend{display:flex;gap:8px 14px;flex-wrap:wrap;align-items:center}
          select,button{font:inherit;color:var(--primary-text-color);background:var(--card-background-color);
            border:1px solid var(--divider-color,#8995a1);border-radius:8px;padding:8px;max-width:100%}
          label{display:flex;gap:8px;align-items:center;flex-wrap:wrap} svg{display:block;width:100%;height:auto;margin-top:8px}
          svg text{fill:var(--primary-text-color);font:15px sans-serif} .legend{font-size:.85rem;margin-top:10px}
          i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
          p{margin:9px 0 0}.caption,.status{color:var(--secondary-text-color);font-size:.85rem}
        </style>
        <ha-card><h2>Ventilation analytics</h2>
          <div class="controls"><label>Plot <select>${PLOTS.map(([key,name])=>`<option value="${key}">${name}</option>`).join('')}</select></label>
          <button type="button">Refresh</button></div>
          <p class="status" role="status"></p><div class="plot"></div>
        </ha-card>`;
      this.shadowRoot.querySelector('select').addEventListener('change',()=>this.draw());
      this.shadowRoot.querySelector('button').addEventListener('click',()=>this.loadHistory());
    }
    set hass(value) {
      this._hass=value;
      if (this.isConnected && this.entities && !this.requested) this.loadHistory();
    }
    connectedCallback() {
      if (this._hass && this.entities && !this.requested) this.loadHistory();
    }
    getCardSize() { return 6; }
    async loadHistory() {
      if (this.loading || !this._hass) return;
      this.requested=true;
      const status=this.shadowRoot.querySelector('.status');
      const button=this.shadowRoot.querySelector('button');
      if (!this.entities.connection || !(this.entities.last_telemetry || this.entities.last_reading)) {
        status.textContent='Connection and telemetry timestamp entities are needed to exclude gaps.';
        return;
      }
      this.loading=true;
      button.disabled=true;
      status.textContent='Reading Home Assistant history…';
      try {
        const end=Math.floor(Date.now()/MINUTE)*MINUTE, start=end-14*DAY;
        const history=await this._hass.callWS({type:'history/history_during_period',
          entity_ids:[...new Set(Object.values(this.entities))], start_time:new Date(start).toISOString(),
          end_time:new Date(end).toISOString(), minimal_response:true, no_attributes:true, significant_changes_only:false});
        const zone=this._hass.config?.time_zone || Intl.DateTimeFormat().resolvedOptions().timeZone;
        const all=minuteHistory(history,this.entities,start,end,zone);
        this.rows=all.slice(-7*1440);
        this.baseline=all.slice(0,-7*1440);
        const fresh=this.rows.filter(r=>r.fresh).length;
        status.textContent=`Last 7 days · ${Math.round(100*fresh/this.rows.length)}% fresh telemetry · ${zone}`;
        this.draw();
      } catch (_) {
        status.textContent='Could not read history. Check Recorder access and try Refresh.';
      } finally {
        this.loading=false;
        button.disabled=false;
      }
    }
    draw() {
      if (!this.rows) return;
      const plot=this.shadowRoot.querySelector('select').value;
      const charts={scatter,distribution,boost,heatmap,drift,energy};
      this.shadowRoot.querySelector('.plot').innerHTML=charts[plot](this.rows,this.baseline);
    }
  }
  if (!customElements.get('ventaxia-econiq-analytics')) customElements.define('ventaxia-econiq-analytics', VentaxiaEconiqAnalytics);

  class VentaxiaEconiqStrategy extends HTMLElement {
    static getCreateSuggestions() { return {title:'Ventilation', icon:'mdi:fan'}; }
    static async generate(config, hass) {
      let devices, entities;
      try {
        [entities, devices] = await Promise.all([
          hass.callWS({type:'config/entity_registry/list'}),
          hass.callWS({type:'config/device_registry/list'}),
        ]);
        if (!Array.isArray(devices) || !Array.isArray(entities)) throw new Error('Invalid registry response');
      } catch (_) {
        return {title:'Ventilation', views:[{title:'Setup', cards:[note('Unable to read the Home Assistant registries. Check your session permissions and reload this dashboard. No device requests were made.')]}]};
      }
      const all = discover(devices, entities);
      const units = config.device_id ? all.filter(u => u.device.id === config.device_id) : all;
      if (!units.length) return {title:'Ventilation', views:[{title:'Setup', cards:[note(config.device_id
        ? 'The selected Home Assistant device UUID is not a compatible enabled ventilation device. Check strategy.device_id.'
        : 'No compatible enabled ventilation device was found. Set up the native integration or existing read-only MQTT bridge, then reload. The strategy does not connect to or pair a unit.')]}]};
      units.sort((a,b) => a.device.id.localeCompare(b.device.id));
      return {title:'Ventilation', views:units.flatMap((unit,index) => unitViews(unit, all.length, hass, index, units.length > 1))};
    }
  }
  const tag = 'll-strategy-dashboard-ventaxia-econiq';
  if (!customElements.get(tag)) customElements.define(tag, VentaxiaEconiqStrategy);
})();
