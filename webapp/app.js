const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();
try { tg?.setHeaderColor('#050507'); tg?.setBackgroundColor('#050507'); tg?.setBottomBarColor?.('#050507'); } catch (e) {}

const $ = (s) => document.querySelector(s);
const view = $('#view');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const haptic = (t = 'light') => { try { tg?.HapticFeedback?.impactOccurred(t); } catch (e) {} };

const state = {
  tab: 'search', me: null,
  country: localStorage.getItem('country') || '', niche: localStorage.getItem('niche') || '',
  count: +(localStorage.getItem('count') || 10),
  results: null, leftInBase: null, searching: false,
  scripts: null, active: null, scriptNeed: 'site',
  leads: null, filter: 'all',
};
const save = (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} };

async function api(path, data) {
  const res = await fetch(path, {
    method: data ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json', 'X-Init-Data': tg?.initData || '' },
    body: data ? JSON.stringify(data) : undefined,
  });
  const json = await res.json().catch(() => ({ error: 'Сервер недоступен' }));
  if (!res.ok) throw Object.assign(new Error(json.error || 'Ошибка'), { status: res.status, data: json });
  return json;
}

let toastTimer;
function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('on'), 2600);
}

function openSheet(html) {
  $('#sheetBody').innerHTML = html;
  $('#sheet').classList.add('on');
  $('#scrim').classList.add('on');
}
function closeSheet() {
  $('#sheet').classList.remove('on');
  $('#scrim').classList.remove('on');
}

/* ---------- общие куски ---------- */

function quotaCard() {
  const q = state.me.quota;
  let num, title, sub;
  if (q.left === null) {
    num = '∞'; title = q.kind === 'admin' ? 'Режим разработчика' : 'Безлимит навсегда'; sub = 'Ищите сколько угодно';
  } else if (q.kind === 'daily') {
    num = `${q.left}<small> / ${q.limit}</small>`; title = 'Генераций на сегодня'; sub = 'Лимит обновляется каждый день';
  } else {
    num = `${q.left}<small> / ${q.limit}</small>`; title = 'Пробный доступ'; sub = q.left ? 'Одна генерация — один поиск' : 'Пробные генерации закончились';
  }
  const btn = q.left === null ? '' : '<button class="pill" data-act="key">Ключ</button>';
  return `<div class="card quota"><div class="quota-num">${num}</div><div class="quota-txt"><b>${title}</b><span>${sub}</span></div>${btn}</div>`;
}

function plansHtml() {
  const p = state.me.prices;
  return `<div class="plans">
    <div class="card plan hot"><div class="plan-ico">♾</div><div><b>Навсегда</b><span>Безлимитные генерации каждый день</span></div><div class="price">${esc(p.forever)} ₽</div></div>
    <div class="card plan"><div class="plan-ico">📅</div><div><b>Лимит в день</b><span>Своё число генераций в сутки — цена зависит от количества</span></div><div class="price">от ${esc(p.daily)} ₽</div></div>
  </div>
  <p class="small muted" style="margin:10px 4px 12px">За подпиской пишите <b style="color:#8fb0ff">@${esc(state.me.support)}</b> — пришлём ключ доступа.</p>
  <div class="row"><button class="btn" data-act="buy">Купить у @${esc(state.me.support)}</button></div>
  <button class="btn ghost mt" data-act="key">У меня есть ключ</button>`;
}

function statusLabel(s) {
  return { new: 'Не написал', written: 'Написал', refused: 'Отказ', interested: 'Интересно' }[s] || s;
}

function leadCard(l) {
  const meta = [l.city && `📍 ${esc(l.city)}${l.address ? ', ' + esc(l.address) : ''}`, `${esc(l.niche_title)}`,
    l.website && `🌐 есть сайт`].filter(Boolean).join('</span><span>');
  const actions = l.status === 'new'
    ? `<button class="btn small" data-act="write" data-id="${l.id}">✉️ Написать</button>
       <button class="btn small ghost" data-act="copy" data-id="${l.id}">Копировать текст</button>`
    : `<button class="btn small ghost" data-act="write" data-id="${l.id}">✉️ Ещё раз</button>
       <button class="btn small ghost" data-act="mark" data-id="${l.id}" data-status="interested">👍 Интерес</button>
       <button class="btn small ghost" data-act="mark" data-id="${l.id}" data-status="refused">👎 Отказ</button>`;
  return `<div class="card lead fade" id="lead-${l.id}">
    <div class="lead-head"><div class="lead-name">${esc(l.name)}</div>
      <span class="tag ${l.need}">${l.need === 'site' ? 'Нужен сайт' : 'Нужен бот'}</span></div>
    <div class="lead-meta"><span class="lead-tg">${esc(l.tg)}</span><span>${meta}</span></div>
    ${l.status !== 'new' ? `<div class="mt" style="margin-top:8px"><span class="status st-${l.status}">${statusLabel(l.status)}</span></div>` : ''}
    <div class="lead-msg" data-act="expand">${esc(l.message)}</div>
    <div class="lead-actions">${actions}</div>
  </div>`;
}

const allLeads = () => [...(state.results || []), ...(state.leads || [])];
const findLead = (id) => allLeads().find((l) => String(l.id) === String(id));

function updateLead(id, patch) {
  for (const list of [state.results, state.leads]) {
    const l = list?.find((x) => String(x.id) === String(id));
    if (l) Object.assign(l, patch);
  }
  const el = document.getElementById(`lead-${id}`);
  const l = findLead(id);
  if (el && l) el.outerHTML = leadCard(l);
}

/* ---------- вкладки ---------- */

function renderSearch() {
  const me = state.me;
  const q = me.quota;
  const blocked = q.left !== null && q.left <= 0;
  const countries = me.countries.map((c) => `<button class="chip ${c.code === state.country ? 'on' : ''}" data-act="country" data-v="${c.code}">${esc(c.title)}</button>`).join('');
  const niches = me.niches.map((n) => `<button class="niche ${n.code === state.niche ? 'on' : ''}" data-act="niche" data-v="${n.code}"><i>${n.emoji}</i>${esc(n.title)}</button>`).join('');
  const counts = me.counts.map((c) => `<button class="${c === state.count ? 'on' : ''}" data-act="count" data-v="${c}">${c}</button>`).join('');

  let results = '';
  if (state.searching) {
    results = `<div class="loader"><span class="spin"></span>Ищем компании в картах…<br>Первый поиск по стране и нише может занять до минуты</div>`;
  } else if (state.results) {
    results = state.results.length
      ? `<div class="label">Найдено: ${state.results.length}${state.leftInBase !== null ? ` · ещё в базе: ${state.leftInBase}` : ''}</div>` + state.results.map(leadCard).join('')
      : `<div class="card empty"><div class="big">🔍</div>По этой нише и стране новых лидов с Telegram больше нет. Попробуйте другую нишу или страну — генерация не списана.</div>`;
  }

  view.innerHTML = `<div class="fade">
    ${quotaCard()}
    ${blocked ? `<div class="label">Доступ закончился</div><div class="card"><p style="margin:0 0 12px">Пробные генерации закончились. Оформите подписку, чтобы продолжить поиск лидов.</p>${plansHtml()}</div>` : ''}
    <div class="card tip"><span class="tip-ico">💡</span><div><b>Совет.</b> ${esc(me.tip)}</div></div>
    <div class="label">Страна</div><div class="chips">${countries}</div>
    <div class="label">Ниша</div><div class="niches">${niches}</div>
    <div class="label">Сколько лидов найти</div><div class="seg">${counts}</div>
    <button class="btn mt" data-act="search" ${state.searching || blocked ? 'disabled' : ''}>${state.searching ? '<span class="spin"></span>Ищем…' : 'Найти лидов'}</button>
    <p class="small muted" style="margin:10px 4px 0">Ищем только компании, которым можно написать в Telegram. Бот сам определяет, что предложить: сайт — если сайта нет, бота — если сайт уже есть.</p>
    <div id="results" class="mt">${results}</div>
  </div>`;
}

async function renderScripts() {
  if (!state.scripts) {
    view.innerHTML = '<div class="loader"><span class="spin"></span></div>';
    const r = await api('/api/scripts');
    state.scripts = r.scripts; state.active = r.active;
  }
  const need = state.scriptNeed;
  const list = state.scripts.filter((s) => s.need === need);
  const sample = need === 'site' ? { name: '«Barber Hub»', city: ' в г. Алматы', niche: 'барбершопа', niche_short: 'барбершоп', offer: 'услуги, цены, фото работ и онлайн-запись' }
    : { name: '«Smile Dent»', city: ' в г. Ташкент', niche: 'стоматологии', niche_short: 'клинику', offer: 'услуги, цены, фото работ и онлайн-запись' };
  const fill = (t) => t.replace(/\{(\w+)\}/g, (m, k) => sample[k] ?? m);
  view.innerHTML = `<div class="fade">
    <div class="seg" style="margin-bottom:12px">
      <button class="${need === 'site' ? 'on' : ''}" data-act="sneed" data-v="site">Для «нужен сайт»</button>
      <button class="${need === 'bot' ? 'on' : ''}" data-act="sneed" data-v="bot">Для «нужен бот»</button>
    </div>
    <p class="small muted" style="margin:0 4px 12px">Выберите текст, который уйдёт лиду. Бот сам подставит название компании, город и нишу, а скрипт выберет по тому, что нужно лиду.</p>
    ${list.map((s) => `<div class="card script ${state.active[need] === s.id ? 'on' : ''}" data-act="pick" data-id="${s.id}">
      <div class="script-head"><span class="radio"></span><b>${esc(s.title)}</b>${s.custom ? `<button class="del" data-act="sdel" data-id="${s.id}">Удалить</button>` : ''}</div>
      <p>${esc(fill(s.text))}</p></div>`).join('')}
    <button class="btn ghost" data-act="snew">＋ Свой скрипт</button>
  </div>`;
}

async function renderStats() {
  view.innerHTML = '<div class="loader"><span class="spin"></span></div>';
  const [r] = await Promise.all([api('/api/leads'), refreshMe()]);
  state.leads = r.leads;
  const s = state.me.stats;
  const q = state.me.quota;
  const left = q.left === null ? '∞' : q.left;
  const conv = s.written ? Math.round((s.interested / s.written) * 100) : 0;
  const shown = state.filter === 'all' ? state.leads : state.leads.filter((l) => l.status === state.filter);
  const f = (k, t) => `<button class="chip ${state.filter === k ? 'on' : ''}" data-act="filter" data-v="${k}">${t}</button>`;
  view.innerHTML = `<div class="fade">
    <div class="stats">
      <div class="stat"><b>${s.found}</b><span>лидов найдено</span></div>
      <div class="stat"><b>${s.written}</b><span>написал</span></div>
      <div class="stat"><b style="color:var(--red)">${s.refused}</b><span>отказали</span></div>
      <div class="stat"><b style="color:var(--green)">${s.interested}</b><span>заинтересовались</span></div>
      <div class="stat wide"><div><b>${left}</b><span>${q.left === null ? 'генерации без лимита' : 'осталось генераций'}</span></div><button class="pill" data-act="tab" data-tab="support">Тарифы</button></div>
      <div class="stat wide" style="display:block"><span>Конверсия в интерес</span><b style="font-size:20px;margin-top:4px">${conv}%</b><div class="bar"><i style="width:${conv}%"></i></div></div>
    </div>
    <div class="label">Мои лиды</div>
    <div class="filters">${f('all', 'Все')}${f('new', 'Не написал')}${f('written', 'Написал')}${f('interested', 'Интерес')}${f('refused', 'Отказ')}</div>
    ${shown.length ? shown.map(leadCard).join('') : '<div class="card empty"><div class="big">📭</div>Здесь пока пусто. Найдите лидов во вкладке «Поиск».</div>'}
  </div>`;
}

function renderSupport() {
  view.innerHTML = `<div class="fade">
    <div class="card support-hero">
      <div class="big">💬</div>
      <h2>Возникли вопросы?</h2>
      <p class="muted" style="margin:0 0 16px">Пишите <a href="https://t.me/${esc(state.me.support)}" data-act="support">@${esc(state.me.support)}</a> — поможем с поиском, скриптами и подпиской.</p>
      <button class="btn" data-act="support">Написать @${esc(state.me.support)}</button>
    </div>
    <div class="label">Тарифы</div>
    ${plansHtml()}
  </div>`;
}

async function render() {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.tab === state.tab));
  try {
    if (state.tab === 'search') renderSearch();
    else if (state.tab === 'scripts') await renderScripts();
    else if (state.tab === 'stats') await renderStats();
    else renderSupport();
  } catch (e) { handleError(e); }
}

async function refreshMe() {
  state.me = await api('/api/me');
}

/* ---------- действия ---------- */

function writeLink(l) {
  const text = encodeURIComponent(l.message);
  if (l.tg.startsWith('@')) return `https://t.me/${l.tg.slice(1)}?text=${text}`;
  return `https://t.me/${l.tg}`;   // ссылка по номеру: текст не подставится, он уже скопирован
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {}
  const ta = document.createElement('textarea');
  ta.value = text; document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) {}
  ta.remove();
  return ok;
}

async function setStatus(id, status) {
  const r = await api('/api/leads/status', { id: +id, status });
  state.me.stats = r.stats;
  updateLead(id, { status });
}

const actions = {
  tab: (el) => { state.tab = el.dataset.tab; haptic(); render(); window.scrollTo(0, 0); },
  country: (el) => { state.country = el.dataset.v; save('country', state.country); haptic(); renderSearch(); },
  niche: (el) => { state.niche = el.dataset.v; save('niche', state.niche); haptic(); renderSearch(); },
  count: (el) => { state.count = +el.dataset.v; save('count', state.count); haptic(); renderSearch(); },
  async search() {
    if (!state.country) return toast('Выберите страну');
    if (!state.niche) return toast('Выберите нишу');
    state.searching = true; state.results = null; renderSearch();
    $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const r = await api('/api/search', { country: state.country, niche: state.niche, count: state.count });
      state.results = r.leads; state.leftInBase = r.left_in_base; state.me = r.me; state.leads = null;
      haptic('medium');
    } catch (e) {
      if (e.status === 402) await refreshMe();
      handleError(e);
    } finally {
      state.searching = false; renderSearch();
      $('#results')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  },
  async write(el) {
    const l = findLead(el.dataset.id);
    await copy(l.message);
    const link = writeLink(l);
    if (tg?.openTelegramLink) tg.openTelegramLink(link); else window.open(link, '_blank');
    if (l.status === 'new') await setStatus(l.id, 'written');
    toast(l.tg.startsWith('@') ? 'Текст подставлен в чат — проверьте и отправьте' : 'Текст скопирован — вставьте в чат');
  },
  async copy(el) {
    const l = findLead(el.dataset.id);
    toast((await copy(l.message)) ? 'Текст скопирован' : 'Не удалось скопировать');
  },
  async mark(el) { haptic(); await setStatus(el.dataset.id, el.dataset.status); toast('Сохранено'); },
  expand: (el) => el.classList.toggle('open'),
  filter: (el) => { state.filter = el.dataset.v; renderStats(); },
  sneed: (el) => { state.scriptNeed = el.dataset.v; renderScripts(); },
  async pick(el, ev) {
    if (ev.target.closest('[data-act="sdel"]')) return;
    const r = await api('/api/scripts/select', { id: el.dataset.id });
    state.active = r.active; state.results = null; state.leads = null; haptic(); renderScripts(); toast('Скрипт выбран');
  },
  async sdel(el) {
    if (!confirm('Удалить скрипт?')) return;
    const r = await api('/api/scripts/delete', { id: el.dataset.id });
    state.scripts = r.scripts; state.active = r.active; renderScripts();
  },
  snew() {
    openSheet(`<h3>Свой скрипт</h3>
      <div class="seg" style="margin-bottom:12px" id="newNeed">
        <button class="${state.scriptNeed === 'site' ? 'on' : ''}" data-act="nneed" data-v="site">Нужен сайт</button>
        <button class="${state.scriptNeed === 'bot' ? 'on' : ''}" data-act="nneed" data-v="bot">Нужен бот</button></div>
      <label class="field"><span>Название</span><input class="input" id="sTitle" maxlength="40" placeholder="Например: Мой основной"></label>
      <label class="field"><span>Текст. Подстановки: {name} — компания, {city} — « в г. Город», {niche} — «барбершопа», «стоматологии»…</span>
      <textarea class="input" id="sText" maxlength="1500" placeholder="Здравствуйте! Увидел {name}{city}…"></textarea></label>
      <button class="btn" data-act="ssave">Сохранить</button>`);
  },
  nneed(el) {
    document.querySelectorAll('#newNeed button').forEach((b) => b.classList.toggle('on', b === el));
  },
  async ssave() {
    const need = document.querySelector('#newNeed .on').dataset.v;
    const r = await api('/api/scripts', { need, title: $('#sTitle').value, text: $('#sText').value });
    state.scripts = r.scripts; state.active = r.active; state.scriptNeed = need;
    closeSheet(); renderScripts(); toast('Скрипт сохранён и выбран');
  },
  key() {
    openSheet(`<h3>Активировать ключ</h3>
      <p class="small muted" style="margin:0 0 12px">Ключ выдаёт @${esc(state.me.support)} после оплаты подписки.</p>
      <label class="field"><input class="input" id="keyInput" placeholder="HL-XXXX-XXXX-XXXX" autocomplete="off" style="text-transform:uppercase;letter-spacing:.05em"></label>
      <button class="btn" data-act="keyGo">Активировать</button>`);
    setTimeout(() => $('#keyInput')?.focus(), 250);
  },
  async keyGo() {
    const r = await api('/api/key', { code: $('#keyInput').value });
    state.me = r.me; closeSheet(); haptic('heavy'); toast(`Активировано: ${r.title}`); render();
  },
  buy: () => openSupport(),
  support: (el, ev) => { ev.preventDefault(); openSupport(); },
  close: () => closeSheet(),
};

function openSupport() {
  const link = `https://t.me/${state.me.support}`;
  if (tg?.openTelegramLink) tg.openTelegramLink(link); else window.open(link, '_blank');
}

document.addEventListener('click', async (ev) => {
  const el = ev.target.closest('[data-act]');
  if (!el || !actions[el.dataset.act]) return;
  if (el.dataset.act === 'search' || el.tagName === 'A') ev.preventDefault();
  try { await actions[el.dataset.act](el, ev); } catch (e) { handleError(e); }
});

function handleError(e) {
  if (e.status === 403 && e.data?.error === 'subscribe') return renderGate(e.data.channels);
  if (e.status === 403) { view.innerHTML = '<div class="card empty"><div class="big">🚫</div>Доступ к боту ограничен.</div>'; return; }
  if (e.status === 401) { view.innerHTML = '<div class="card empty"><div class="big">🔒</div>Откройте приложение через бота в Telegram.</div>'; return; }
  if (e.status === 402) { toast('Генерации закончились — оформите подписку'); return; }
  toast(e.message || 'Ошибка');
}

function renderGate(channels) {
  $('#tabbar').hidden = true;
  view.innerHTML = `<div class="card fade"><h2 style="font-size:18px;margin-bottom:8px">Подпишитесь на каналы</h2>
    <p class="muted small" style="margin:0 0 14px">Чтобы пользоваться парсером, подпишитесь и нажмите «Проверить».</p>
    ${channels.map((c) => `<a class="btn ghost" style="margin-bottom:8px;text-decoration:none" href="${esc(c.url)}" target="_blank">${esc(c.title)}</a>`).join('')}
    <button class="btn mt" onclick="location.reload()">Проверить</button></div>`;
}

(async function init() {
  const u = tg?.initDataUnsafe?.user;
  if (u) {
    const av = $('#avatar');
    if (u.photo_url) av.style.backgroundImage = `url("${u.photo_url}")`; else av.textContent = (u.first_name || '?')[0];
  }
  try {
    await refreshMe();
    $('#tabbar').hidden = false;
    render();
  } catch (e) { handleError(e); }
})();
