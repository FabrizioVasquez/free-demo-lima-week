const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const DN = ['dom','lun','mar','mié','jue','vie','sáb'];
const MN = ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic'];
const dayLabel = d => { const t = new Date(d + 'T12:00:00'); return `${DN[t.getDay()]} ${t.getDate()} ${MN[t.getMonth()]}`; };
const timeLabel = e => {
  const sd = e.start.slice(0, 10), ed = e.end.slice(0, 10);
  return ed === sd ? `${e.start.slice(11)}–${e.end.slice(11)}` : `${e.start.slice(11)} → ${dayLabel(ed)}`;
};
const where = e => e.mode === 'virtual' ? 'Virtual' : (e.city || 'Lugar por confirmar');
const store = { get(k){ try { return localStorage.getItem(k); } catch { return null; } }, set(k, v){ try { localStorage.setItem(k, v); } catch {} } };

const PRESETS = {
  'Estudiante de CS': 'Soy estudiante de Computer Science en 7mo ciclo. Quiero aprender IA aplicada y agentes, hacer proyectos reales y conocer gente que contrate practicantes. Vivo en Surco, prefiero eventos presenciales y por las tardes.',
  'Founder fintech': 'Soy founder de una startup fintech pre-seed. Busco inversionistas, conocer bancos y fintechs y entender cómo levantar capital. Top 3.',
  'Dev backend senior': 'Soy desarrollador backend con 6 años de experiencia. Quiero aprender arquitectura de agentes de IA, blockchain y computación cuántica y hacer networking técnico con CTOs. Solo por las tardes.',
  'Mujer en tech': 'Soy ingeniera de datos y quiero crecer hacia liderazgo en IA. Busco comunidades de mujeres en tecnología, mentoras y eventos con buen networking.',
  'Hackathon el sábado': 'Quiero un hackathon para construir con agentes de IA el sábado, presencial.'
};
const CRIT = { semantica: 'SEM', objetivo: 'OBJ', disponibilidad: 'DISP', escala: 'ESC', logistica: 'LOG' };
let EVENTS = [], DAYS = [], sel = new Set();

function tags(e){
  const t = [];
  if (e.status === 'agotado') t.push('<span class="tag agotado">AGOTADO</span>');
  else if (e.status === 'lista de espera') t.push('<span class="tag espera">LISTA DE ESPERA</span>');
  else t.push(`<span class="tag abierto">ABIERTO${e.spots ? ' · ' + e.spots + ' CUPOS' : ''}</span>`);
  if (e.approval) t.push('<span class="tag info">REQUIERE APROBACIÓN</span>');
  if (e.mode === 'virtual') t.push('<span class="tag info">VIRTUAL</span>');
  return `<div class="tags">${t.join('')}</div>`;
}

async function init(){
  const [st, ev] = await Promise.all([fetch('/api/status').then(r => r.json()), fetch('/api/events').then(r => r.json())]);
  EVENTS = ev;
  $('count').textContent = `(${ev.length})`;
  $('sys').innerHTML = `<i></i><b>LOCAL</b> · ${esc(st.db)}<br>modelo: ${esc(st.model.split('/').pop())}<br>${st.events} eventos · ahora: ${esc(st.now)} (Lima)`;
  DAYS = [...new Set(ev.map(e => e.start.slice(0, 10)))].sort();
  sel = new Set(DAYS);
  $('days').innerHTML = DAYS.map(d => { const t = new Date(d + 'T12:00:00'); return `<button class="day" data-d="${d}" aria-pressed="true">${DN[t.getDay()]}<b>${t.getDate()}</b></button>`; }).join('');
  $('days').onclick = e => { const b = e.target.closest('.day'); if (!b) return; const d = b.dataset.d, on = !sel.has(d); on ? sel.add(d) : sel.delete(d); b.setAttribute('aria-pressed', on); };
  $('city').innerHTML = '<option value="">Todos</option>' + st.cities.map(c => `<option>${esc(c)}</option>`).join('');
  $('presets').innerHTML = Object.keys(PRESETS).map(k => `<button type="button" class="chip">${esc(k)}</button>`).join('');
  $('presets').onclick = e => { const c = e.target.closest('.chip'); if (c){ $('prompt').value = PRESETS[c.textContent]; store.set('btw-prompt', $('prompt').value); } };
  $('prompt').value = store.get('btw-prompt') || PRESETS['Estudiante de CS'];
  $('prompt').oninput = () => store.set('btw-prompt', $('prompt').value);
  $('prompt').onkeydown = e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') run(); };
  $('go').onclick = run;
  document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.setAttribute('aria-selected', x === t));
    $('view-rec').hidden = t.dataset.tab !== 'rec'; $('view-all').hidden = t.dataset.tab !== 'all';
  });
  $('fday').innerHTML = '<option value="">Todos los días</option>' + DAYS.map(d => `<option value="${d}">${dayLabel(d)}</option>`).join('');
  ['q', 'fday', 'fstatus'].forEach(id => $(id).oninput = renderAll);
  renderAll();
  run();
}

function norm(s){ return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
function renderAll(){
  const q = norm($('q').value), fd = $('fday').value, fs = $('fstatus').value;
  const list = EVENTS.filter(e => (!fd || e.start.slice(0, 10) === fd) && (!fs || e.status === fs) &&
    (!q || norm(e.name + ' ' + e.hosts.join(' ') + ' ' + e.description).includes(q)));
  let out = '', cur = '';
  for (const e of list){
    const d = e.start.slice(0, 10);
    if (d !== cur){ cur = d; out += `<h3 class="dayh">${dayLabel(d).toUpperCase()}</h3>`; }
    out += `<div class="erow"><span class="tm">${timeLabel(e)}</span><div><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.name)}</a>
      <small>${esc(where(e))}${e.hosts.length ? ' · ' + esc(e.hosts.join(', ')) : ''}${e.guests ? ' · ' + e.guests + ' inscritos' : ''}</small></div>${tags(e)}</div>`;
  }
  $('all').innerHTML = out || '<p class="muted">Ningún evento coincide.</p>';
}

function highlight(text, kws){
  let h = esc(text);
  (kws || []).forEach(k => { h = h.replace(new RegExp('(' + k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\w*)', 'gi'), '<mark>$1</mark>'); });
  return h;
}

function render(r){
  const labels = Object.fromEntries(r.weights.map(w => [w.key, w.label]));
  let h = r.low_confidence ? '<div class="banner err">Tu texto no se parece a ningún evento. Estos son los menos lejanos; cuéntame qué quieres aprender o a quién quieres conocer.</div>' : '';
  h += `<div class="box interp"><h2>01 · INTERPRETACIÓN DE TU PROMPT</h2><ul>${r.interpretation.map(l => `<li>${esc(l)}</li>`).join('')}</ul>
    <div class="sq">consulta semántica enviada al índice (sin lugar, día ni formato): «${esc(r.semantic_query)}»<br>${r.candidates} eventos candidatos · ${r.ms} ms</div></div>`;
  h += `<div class="box"><h2>02 · PONDERACIÓN (SE ADAPTA A TU PROMPT)</h2>${r.weights.map(w => `<div class="wrow"><span>${esc(w.label)}</span><div class="wbar"><i style="width:${w.weight * 2}%"></i></div><b>${w.weight}%</b></div>`).join('')}</div>`;
  if (!r.results.length){ $('results').innerHTML = h + '<div class="banner err">Ningún evento cumple esos filtros. Activa más días o quita el distrito.</div>'; return; }
  h += `<div class="box"><h2>03 · MATRIZ</h2><div class="mtx"><table><thead><tr><th>Evento</th>${r.weights.map(w => `<th>${esc(w.label)} · ${w.weight}%</th>`).join('')}<th style="text-align:right">Total</th></tr></thead><tbody>
    ${r.results.map(x => `<tr><td class="n"><a href="${esc(x.event.url)}" target="_blank" rel="noopener">${esc(x.event.name)}</a></td>${r.weights.map(w => `<td class="s" style="background:rgba(248,225,142,${(x.scores[w.key] / 10 * .32).toFixed(2)})">${x.scores[w.key]}</td>`).join('')}<td class="t">${x.total.toFixed(0)}</td></tr>`).join('')}</tbody></table></div></div>`;
  r.results.forEach((x, i) => {
    const e = x.event;
    h += `<article class="box ev"><div class="rank">${String(i + 1).padStart(2, '0')}</div><div>
      <div class="evh"><h3>${esc(e.name)}</h3><div class="score">${x.total.toFixed(0)}<small>/100</small></div></div>
      <div class="meta"><span>${dayLabel(e.start.slice(0, 10))} · ${timeLabel(e)}</span><span>${esc(where(e))}</span>${e.guests ? `<span>${e.guests} inscritos</span>` : ''}${e.hosts.length ? `<span>${esc(e.hosts.join(', '))}</span>` : ''}</div>
      ${tags(e)}
      <div class="trace"><h4>RAZONAMIENTO · PASO A PASO</h4>${x.trace.map(t => `<div class="tr"><span class="k">[${t.tag}]</span><span class="v">${t.score}</span><span>${esc(t.text)}</span></div>`).join('')}</div>
      ${x.snippet ? `<p class="snip">${highlight(x.snippet, x.keywords)}</p>` : ''}
      <a class="go" href="${esc(e.url)}" target="_blank" rel="noopener">ABRIR EN LUMA ↗</a></div></article>`;
  });
  if (r.conflicts.length) h += `<div class="box"><h2>04 · CHOQUES DE HORARIO</h2><ul class="list">${r.conflicts.map(c => `<li><span class="tag espera">CRUCE</span> ${esc(c.day)}: ${esc(c.a)} <span class="dim">y</span> ${esc(c.b)}</li>`).join('')}</ul></div>`;
  if (r.excluded.length) h += `<div class="box"><h2>05 · SE PARECEN A TU PROMPT, PERO QUEDARON FUERA</h2><ul class="list">${r.excluded.map(x => `<li><a href="${esc(x.event.url)}" target="_blank" rel="noopener">${esc(x.event.name)}</a> ${tags(x.event)}<div class="muted" style="margin-top:4px">${esc(x.reason)}</div></li>`).join('')}</ul></div>`;
  $('results').innerHTML = h;
}

async function run(){
  const prompt = $('prompt').value.trim();
  if (prompt.length < 3){ $('hint').textContent = 'Escribe primero quién eres y qué buscas.'; return; }
  $('go').disabled = true;
  $('results').innerHTML = '<div class="box"><span class="blink">▍</span> buscando en el índice vectorial…</div>';
  try {
    const body = { prompt, days: sel.size === DAYS.length ? [] : [...sel], city: $('city').value || null, mode: $('mode').value || null,
      include_soldout: $('soldout').checked, hide_ended: $('hideended').checked, top_n: $('topn').value ? +$('topn').value : null };
    const res = await fetch('/api/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    render(await res.json());
  } catch (e) {
    $('results').innerHTML = `<div class="banner err">No pude completar la búsqueda (${esc(e.message)}). Revisa que el servidor siga corriendo.</div>`;
  } finally { $('go').disabled = false; }
}
init();
