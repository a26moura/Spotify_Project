'use strict';
// Etapas: connect → playlists → game → preview. Nada aqui grava no Spotify; só a prévia final (etapa 5).
let state = null, screen = 'connect', syncing = false, collectTimer = null;
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const LANGUAGES = ['Português', 'Inglês', 'Espanhol', 'Francês', 'Italiano', 'Alemão', 'Japonês', 'Coreano', 'Instrumental', 'Misto'];

function notify(text, error = false) {
  $('notice').textContent = text || '';
  $('notice').classList.toggle('error', error);
  $('notice').classList.toggle('hidden', !text);
  if (error && $('dialog').open) {
    let box = $('dialog-error');
    if (!box) { box = document.createElement('p'); box.id = 'dialog-error'; box.setAttribute('role', 'alert'); $('dialog-body').prepend(box); }
    box.textContent = text;
  }
}
async function api(path, data) {
  const options = data === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf}, body: JSON.stringify(data)};
  const response = await fetch('/api/' + path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Não foi possível concluir.');
  return result;
}
async function action(button, job) {
  if (button) button.disabled = true;
  try { await job(); } catch (e) { notify(e.message, true); } finally { if (button) button.disabled = false; }
}
function modal(title, body) {
  $('dialog-title').textContent = title; $('dialog-body').innerHTML = body;
  if (!$('dialog').open) $('dialog').showModal();
}
$('close-dialog').onclick = () => $('dialog').close();

async function refresh() { state = await api('game'); render(); }

// ---------- navegação ----------
function allowed(name) {
  if (!state) return name === 'connect';
  if (name === 'connect') return true;
  if (!state.connected || !state.synced_at) return false;
  if (name === 'playlists') return true;
  return state.profiles.some(p => p.active);
}
function go(name) {
  if (!allowed(name)) return;
  screen = name;
  for (const s of document.querySelectorAll('.screen')) s.classList.toggle('hidden', s.id !== 'screen-' + name);
  if (name !== 'game') stopAudio();
  render();
  if (name === 'game') loadCard().catch(e => notify(e.message, true));
  if (name === 'playlists') refresh().catch(e => notify(e.message, true));
  if (name === 'preview') loadPlan();
}
for (const b of document.querySelectorAll('[data-go]')) b.onclick = () => go(b.dataset.go);

function render() {
  $('account-name').textContent = state.connected ? state.display_name : 'Não conectado';
  $('mode').textContent = state.connected ? 'Conectado ao Spotify' : 'Sem conexão';
  $('logout').classList.toggle('hidden', !state.connected);
  $('connect').textContent = state.connected ? (syncing ? 'Importando…' : 'Continuar →') : 'Conectar Spotify ↗';
  $('connect').disabled = syncing;
  for (const b of document.querySelectorAll('[data-go]')) {
    b.disabled = !allowed(b.dataset.go);
    b.classList.toggle('current', b.dataset.go === screen);
  }
  if (screen === 'playlists') renderPlaylists();
}

// ---------- conectar e importar ----------
function configure() {
  modal('Conectar sua conta', `<p>Crie um aplicativo na sua conta do <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener noreferrer">Spotify for Developers</a>.</p>
    <ol><li>Crie um app e selecione o uso da Web API.</li><li>Cadastre exatamente este endereço de retorno: <code>${esc(state.redirect)}</code>.</li><li>Copie o Client ID para o campo abaixo.</li><li>Se necessário, adicione sua conta aos usuários autorizados do app.</li></ol>
    <label class="field">Client ID<input id="client-id" autocomplete="off" maxlength="32" placeholder="Identificador de 32 caracteres"></label>
    <p class="muted">Não precisamos de Client Secret nem da sua senha. A autorização acontece no Spotify.</p>
    <div class="dialog-actions"><button id="save-client" class="primary">Salvar e conectar</button></div>`);
  $('save-client').onclick = () => action($('save-client'), async () => { await api('config', {client_id: $('client-id').value}); location.href = '/auth/start'; });
}
$('connect').onclick = () => {
  if (!state.connected) { if (state.configured) location.href = '/auth/start'; else configure(); return; }
  if (!state.synced_at) syncLibrary(); else go('playlists');
};
$('logout').onclick = () => action($('logout'), async () => { const r = await api('logout', {}); screen = 'connect'; await refresh(); go('connect'); notify(r.message); });

async function syncLibrary() {
  if (syncing) return;
  syncing = true; render();
  try {
    const start = await api('sync-start', {}); notify(start.message);
    let result;
    do { result = await api('sync-step', {id: start.id}); notify(result.message); } while (result.remaining > 0);
    await refresh(); go('playlists'); watchCollect();
  } catch (e) { notify(e.message, true); }
  finally { syncing = false; render(); }
}
$('sync').onclick = () => action($('sync'), syncLibrary);

// ---------- coleta em segundo plano ----------
function showCollect(c) {
  const left = c.remaining ? `${c.remaining} músicas ainda sem consulta.` : 'Todas as músicas consultadas.';
  $('collect-status').textContent = c.running ? c.message + ' · ' + left : (c.message ? c.message + ' ' : '') + (c.running ? '' : left);
}
function watchCollect() {
  clearTimeout(collectTimer);
  const tick = async () => {
    try {
      const c = await api('collect-status');
      state.collect = c; showCollect(c);
      if (c.running) collectTimer = setTimeout(tick, 3000);
      else if (screen === 'playlists') await refresh();
    } catch (e) { /* a falha da consulta nunca bloqueia a tela */ }
  };
  tick();
}

// ---------- playlists ----------
function fillList(id, values) {
  $(id).innerHTML = [...new Set(values)].map(v => `<option value="${esc(v)}">`).join('');
}
function renderPlaylists() {
  const active = state.profiles.filter(p => p.active).length;
  $('max-active').textContent = state.max_active;
  $('active-count').textContent = `${active} de ${state.max_active} playlists no jogo`;
  const pr = state.progress;
  $('library-count').textContent = `${pr.total} músicas · ${pr.decided} já distribuídas`;
  showCollect(state.collect);
  $('start-game').disabled = !active;
  fillList('languages', [...LANGUAGES, ...state.languages]);
  fillList('genres', state.genres);
  const list = $('profiles');
  // Keep the card being edited: only rebuild when the set of playlists changed.
  const keys = state.profiles.map(p => p.key).join('|');
  if (list.dataset.keys !== keys) {
    list.innerHTML = '';
    for (const p of state.profiles) list.append(profileCard(p));
    list.dataset.keys = keys;
  } else {
    for (const p of state.profiles) updateCard(list.querySelector(`[data-key="${CSS.escape(p.key)}"]`), p, false);
  }
  $('no-profiles').classList.toggle('hidden', state.profiles.length > 0);
}
function updateCard(card, p, fields = true) {
  if (!card) return;
  if (fields) {
    card.querySelector('.f-name').value = p.name;
    card.querySelector('.f-description').value = p.description;
    card.querySelector('.f-language').value = p.language;
    card.querySelector('.f-genre').value = p.genre;
  }
  card.querySelector('.f-active').checked = p.active;
  card.querySelector('.f-active').disabled = !!p.missing;
  card.classList.toggle('active', p.active);
  card.classList.toggle('missing', !!p.missing);
  card.querySelector('.badge').textContent = p.missing ? 'Não existe mais no Spotify' : p.spotify_id ? 'No Spotify' : 'Nova · só no app';
  const changed = p.count_after !== p.count ? ` → ${p.count_after} depois do jogo` : '';
  card.querySelector('.count').textContent = `${p.count} músicas${changed}`;
  card.querySelector('.f-delete').classList.toggle('hidden', !!p.spotify_id);
  card.querySelector('.counter').textContent = `${card.querySelector('.f-description').value.length}/300`;
}
function profileCard(p) {
  const card = $('profile-template').content.firstElementChild.cloneNode(true);
  card.dataset.key = p.key;
  updateCard(card, p);
  const saved = card.querySelector('.saved');
  const save = async fields => {
    saved.textContent = 'Salvando…';
    try {
      const r = await api('profile-update', {key: p.key, fields});
      Object.assign(p, r.profile);
      const i = state.profiles.findIndex(x => x.key === p.key); if (i >= 0) Object.assign(state.profiles[i], r.profile);
      saved.textContent = 'Salvo no app';
      render();
    } catch (e) {
      saved.textContent = '';
      notify(e.message, true);
      updateCard(card, p); // volta ao último valor válido
    }
  };
  for (const [cls, key] of [['.f-name', 'name'], ['.f-description', 'description'], ['.f-language', 'language'], ['.f-genre', 'genre']]) {
    const input = card.querySelector(cls);
    input.addEventListener('change', () => { if (input.value.trim() !== p[key]) save({[key]: input.value}); });
  }
  card.querySelector('.f-description').addEventListener('input', e => { card.querySelector('.counter').textContent = `${e.target.value.length}/300`; });
  card.querySelector('.f-active').addEventListener('change', e => save({active: e.target.checked}));
  card.querySelector('.f-delete').onclick = () => action(card.querySelector('.f-delete'), async () => {
    if (!confirm(`Apagar a playlist nova "${p.name}" do app? As músicas que você colocou nela saem dela.`)) return;
    const r = await api('profile-delete', {key: p.key}); await refresh(); notify(r.message);
  });
  return card;
}
$('new-playlist').onclick = () => {
  modal('Nova playlist', `<p>Ela fica só no app até a prévia final. No Spotify, será criada como privada.</p>
    <label class="field">Nome<input id="new-name" maxlength="100" autocomplete="off"></label>
    <label class="field">Descrição<textarea id="new-description" maxlength="300" rows="2"></textarea></label>
    <div class="pair"><label class="field">Idioma<input id="new-language" list="languages" maxlength="50" autocomplete="off"></label>
    <label class="field">Gênero ou clima<input id="new-genre" list="genres" maxlength="50" autocomplete="off"></label></div>
    <div class="dialog-actions"><button id="create-playlist" class="primary">Criar</button></div>`);
  $('new-name').focus();
  $('create-playlist').onclick = () => action($('create-playlist'), async () => {
    const r = await api('profile-create', {fields: {name: $('new-name').value, description: $('new-description').value, language: $('new-language').value, genre: $('new-genre').value}});
    $('dialog').close(); await refresh(); notify(r.message);
  });
};
$('start-game').onclick = () => go('game');

// ---------- jogo ----------
let game = null, chosen = new Set(), busy = false, previewToken = 0;
const ORIGIN = {faixa: 'pela faixa', album: 'pelo álbum', letra: 'pela letra', artista: 'pelo artista', ia: 'por IA', manual: 'revisão sua'};
const player = $('player');
const pref = (key, fallback) => { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; } };
const setPref = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* sem armazenamento: só não lembra */ } };
$('autoplay').checked = pref('autoplay', true);
$('volume').value = pref('volume', 0.7); player.volume = +$('volume').value;
$('autoplay').onchange = e => setPref('autoplay', e.target.checked);
$('volume').oninput = e => { player.volume = +e.target.value; setPref('volume', +e.target.value); };

function activeProfiles() { return state.profiles.filter(p => p.active); }
async function loadCard(id) {
  const data = await api('game-card' + (id ? '?id=' + encodeURIComponent(id) : ''));
  showCard(data);
}
function showCard(data) {
  game = data;
  chosen = new Set(data.marks || []);
  const pr = data.progress;
  $('progress-bar').style.width = pr.total ? (100 * pr.decided / pr.total) + '%' : '0';
  $('progress-text').textContent = `${pr.decided} de ${pr.total} distribuídas` + (pr.skipped ? ` · ${pr.skipped} puladas` : '');
  const t = data.track;
  $('board').classList.toggle('hidden', !t);
  $('game-done').classList.toggle('hidden', !!t);
  $('skip').disabled = !t;
  stopAudio();
  if (!t) return;
  $('card-title').textContent = t.title;
  $('card-artists').textContent = t.artists.join(', ');
  $('card-album').textContent = [t.album, t.year].filter(Boolean).join(' · ');
  $('card-cover').classList.toggle('hidden', !t.cover);
  $('card-nocover').classList.toggle('hidden', !!t.cover);
  if (t.cover) $('card-cover').src = t.cover; else $('card-cover').removeAttribute('src');
  const chips = [];
  if (t.genres.length) chips.push(`<span class="chip" title="Gênero ${esc(ORIGIN[t.genre_origin] || '')}">${esc(t.genres.slice(0, 3).join(', '))}<small>${esc(ORIGIN[t.genre_origin] || '')}</small></span>`);
  else chips.push(`<span class="chip faint">${t.pending ? 'Gênero: buscando…' : 'Gênero desconhecido'}</span>`);
  if (t.languages.length) chips.push(`<span class="chip" title="Idioma ${esc(ORIGIN[t.language_origin] || '')}">${esc(t.languages.join(', '))}<small>${esc(ORIGIN[t.language_origin] || '')}</small></span>`);
  else chips.push(`<span class="chip faint">${t.pending ? 'Idioma: buscando…' : 'Idioma desconhecido'}</span>`);
  const extra = t.labels.filter(l => !t.genres.includes(l)).slice(0, 4);
  if (extra.length) chips.push(`<span class="chip faint" title="Outros rótulos das fontes">${esc(extra.join(', '))}</span>`);
  if (t.duration_ms) chips.push(`<span class="chip faint">${Math.floor(t.duration_ms / 60000)}:${String(Math.round(t.duration_ms / 1000) % 60).padStart(2, '0')}</span>`);
  if (t.bpm) chips.push(`<span class="chip faint">${Math.round(t.bpm)} BPM</span>`);
  if (t.explicit) chips.push('<span class="chip faint">Explícita</span>');
  chips.push(`<span class="chip faint">${t.liked ? 'Curtida' + (t.added_at ? ' em ' + new Date(t.added_at).toLocaleDateString('pt-BR') : '') : 'Só em playlist'}</span>`);
  $('card-chips').innerHTML = chips.join('');
  renderZones();
  loadPreview(t.id);
}
function renderZones() {
  const profiles = activeProfiles();
  const half = Math.ceil(profiles.length / 2);
  for (const [side, list] of [['zones-left', profiles.slice(0, half)], ['zones-right', profiles.slice(half)]]) {
    $(side).innerHTML = '';
    for (const p of list) {
      const i = profiles.indexOf(p);
      const zone = $('zone-template').content.firstElementChild.cloneNode(true);
      zone.dataset.key = p.key;
      zone.querySelector('kbd').textContent = i + 1;
      zone.querySelector('.zone-name').textContent = p.name;
      zone.onclick = () => toggle(p.key);
      zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
      zone.addEventListener('dragleave', () => zone.classList.remove('over'));
      zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('over'); mark(p.key); });
      $(side).append(zone);
    }
  }
  updateZones();
}
function updateZones() {
  if (!game || !game.track) return;
  for (const zone of document.querySelectorAll('.zone')) {
    const key = zone.dataset.key, on = chosen.has(key), was = game.in_spotify.includes(key);
    zone.classList.toggle('on', on);
    zone.classList.toggle('leaving', was && !on);
    zone.classList.toggle('suggested', game.suggested.includes(key));
    zone.setAttribute('aria-pressed', on);
    zone.querySelector('.zone-state').textContent = on ? (was ? 'Já está' : 'Entra') : was ? 'Vai sair' : game.suggested.includes(key) ? 'Combina' : '';
  }
}
function toggle(key) { if (chosen.has(key)) chosen.delete(key); else chosen.add(key); updateZones(); }
function mark(key) { chosen.add(key); updateZones(); }

// Arrastar com o ponteiro: o cartão segue o mouse, marca a playlist onde for solto e volta ao lugar.
const card = $('card');
let drag = null;
const zoneAt = (x, y) => document.elementsFromPoint(x, y).map(el => el.closest('.zone')).find(Boolean);
card.addEventListener('pointerdown', e => {
  if (e.button !== 0 || e.target.closest('button') || !game?.track) return;
  drag = {x: e.clientX, y: e.clientY, moved: false, over: null};
  card.setPointerCapture(e.pointerId);
});
card.addEventListener('pointermove', e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (!drag.moved && Math.hypot(dx, dy) < 6) return;
  drag.moved = true;
  card.classList.add('dragging');
  card.style.transform = `translate(${dx}px, ${dy}px) rotate(${Math.max(-8, Math.min(8, dx / 30))}deg) scale(.92)`;
  const zone = zoneAt(e.clientX, e.clientY);
  if (zone !== drag.over) { drag.over?.classList.remove('over'); zone?.classList.add('over'); drag.over = zone; }
});
const endDrag = e => {
  if (!drag) return;
  const {over, moved} = drag; drag = null;
  over?.classList.remove('over');
  card.classList.remove('dragging');
  card.style.transform = '';
  if (moved && over && e.type === 'pointerup') { mark(over.dataset.key); over.classList.add('pulse'); setTimeout(() => over.classList.remove('pulse'), 350); }
};
card.addEventListener('pointerup', endDrag);
card.addEventListener('pointercancel', endDrag);
card.addEventListener('dragstart', e => e.preventDefault());

async function move(path, data) {
  if (busy) return;
  busy = true;
  try { showCard(await api(path, data)); await refreshProfiles(); }
  catch (e) { notify(e.message, true); }
  finally { busy = false; }
}
async function refreshProfiles() { const fresh = await api('game'); state.profiles = fresh.profiles; state.progress = fresh.progress; }
$('next').onclick = () => game?.track && move('game-decide', {id: game.track.id, playlists: [...chosen]});
$('skip').onclick = () => game?.track && move('game-skip', {id: game.track.id});
$('undo').onclick = () => move('game-undo', {});
$('to-preview').onclick = () => go('preview');
$('done-preview').onclick = () => go('preview');

// Áudio: o link de 30 s do Deezer é buscado na hora (expira) e nunca guardado.
function stopAudio() {
  previewToken++;
  player.pause(); player.removeAttribute('src'); player.load();
  $('play').textContent = '▶'; $('play').disabled = true; $('audio-bar').style.width = '0';
  $('audio-status').textContent = '';
}
async function loadPreview(id) {
  const token = ++previewToken;
  $('audio-status').textContent = 'Buscando prévia…';
  try {
    const r = await fetch('/api/preview?id=' + encodeURIComponent(id)).then(x => x.json());
    if (token !== previewToken) return;
    if (!r.url) { $('audio-status').textContent = 'Sem prévia de áudio'; return; }
    player.src = r.url; $('play').disabled = false; $('audio-status').textContent = 'Prévia de 30 s · Deezer';
    if ($('autoplay').checked) player.play().catch(() => { $('audio-status').textContent = 'Clique em ▶ para ouvir'; });
  } catch { if (token === previewToken) $('audio-status').textContent = 'Prévia indisponível'; }
}
function playPause() { if (!player.src) return; if (player.paused) player.play().catch(() => {}); else player.pause(); }
$('play').onclick = playPause;
player.onplay = () => { $('play').textContent = '❚❚'; };
player.onpause = player.onended = () => { $('play').textContent = '▶'; };
player.ontimeupdate = () => { $('audio-bar').style.width = player.duration ? (100 * player.currentTime / player.duration) + '%' : '0'; };

document.addEventListener('keydown', e => {
  if (screen !== 'game' || $('dialog').open || e.target.closest('input, textarea, select')) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); $('undo').click(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey || !game?.track) return;
  const profiles = activeProfiles();
  if (/^[1-8]$/.test(e.key) && profiles[+e.key - 1]) { e.preventDefault(); toggle(profiles[+e.key - 1].key); }
  else if (e.key === 'Enter') { e.preventDefault(); $('next').click(); }
  else if (e.key === ' ') { e.preventDefault(); playPause(); }
  else if (e.key.toLowerCase() === 's') { e.preventDefault(); $('skip').click(); }
});

// ---------- prévia final e gravação ----------
let plan = null;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const STATUS = {create: 'Nova · será criada (privada)', update: 'Vai mudar', same: 'Sem mudanças', skip: 'Nova, sem músicas · não será criada'};
const songList = (list, cls) => list.length ? `<ul class="songs ${cls}">${list.map(t => `<li>${esc(t.title)} <span class="muted">${esc(t.artists.join(', '))}</span></li>`).join('')}</ul>` : '';
async function loadPlan() {
  $('publish').disabled = true; plan = null;
  $('publish-results').classList.add('hidden');
  $('preview-totals').textContent = 'Lendo suas playlists no Spotify…'; $('preview-list').innerHTML = '';
  try {
    plan = await api('publish-preview', {});
    const t = plan.totals;
    $('preview-totals').innerHTML = t.playlists
      ? `<span><b>${plural(t.playlists, 'playlist vai', 'playlists vão')}</b> mudar</span><span><b>${plural(t.create, 'nova', 'novas')}</b></span><span class="plus"><b>+${t.add}</b> entram</span><span class="minus"><b>−${t.remove}</b> saem</span>`
      : '<span>Nada para gravar: o Spotify já está igual às suas escolhas.</span>';
    $('preview-list').innerHTML = plan.items.map(i => `
      <article class="plan ${i.action}">
        <header><h2>${esc(i.rename ? i.rename.to : i.name)}</h2><span class="badge">${STATUS[i.action]}</span></header>
        ${i.rename ? `<p class="change">Nome: <s>${esc(i.rename.from)}</s> → ${esc(i.rename.to)}</p>` : ''}
        ${i.describe ? `<p class="change">Descrição: ${i.describe.from ? `<s>${esc(i.describe.from)}</s> → ` : ''}${esc(i.describe.to) || '<i>vazia</i>'}</p>` : ''}
        <p class="counts">${i.before} → <b>${i.after}</b> músicas ${i.add.length ? `<span class="plus">+${i.add.length}</span>` : ''} ${i.remove.length ? `<span class="minus">−${i.remove.length}</span>` : ''}</p>
        ${i.add.length || i.remove.length ? `<details${i.add.length + i.remove.length <= 6 ? ' open' : ''}><summary>Ver músicas</summary>${songList(i.add, 'plus')}${songList(i.remove, 'minus')}</details>` : ''}
      </article>`).join('');
    $('publish').disabled = !t.playlists;
  } catch (e) { $('preview-totals').textContent = ''; notify(e.message, true); }
}
$('refresh-preview').onclick = () => action($('refresh-preview'), loadPlan);
$('back-game').onclick = () => go('game');
$('publish').onclick = () => {
  if (!plan) return;
  const t = plan.totals;
  modal('Gravar no Spotify?', `<p>Vou alterar <b>${plural(t.playlists, 'playlist', 'playlists')}</b>${t.create ? ` (${plural(t.create, 'nova', 'novas')}, criada${t.create === 1 ? '' : 's'} como privada${t.create === 1 ? '' : 's'})` : ''}: <b>+${t.add}</b> músicas entram e <b>−${t.remove}</b> saem.</p>
    ${t.remove ? '<p>As remoções não têm desfazer automático. Se quiser uma música de volta, coloque-a de novo pelo jogo.</p>' : ''}
    <p class="muted">Se alguma playlist tiver mudado no Spotify depois desta prévia, ela não é alterada e a gravação para ali.</p>
    <div class="dialog-actions"><button id="cancel-publish" class="secondary">Cancelar</button><button id="confirm-publish" class="primary">Gravar agora</button></div>`);
  $('cancel-publish').onclick = () => $('dialog').close();
  $('confirm-publish').onclick = () => action($('confirm-publish'), async () => {
    const r = await api('publish-execute', {id: plan.id});
    $('dialog').close(); plan = null; $('publish').disabled = true;
    const failed = r.results.find(x => x.error);
    $('preview-list').innerHTML = '';
    $('preview-totals').textContent = failed ? '' : 'Gravação concluída. Use "Ler de novo" para conferir o Spotify.';
    $('publish-results').innerHTML = `<h2>${failed ? 'Gravação interrompida' : 'Gravado no Spotify ✓'}</h2><ul>${r.results.map(x => `<li class="${x.error ? 'minus' : ''}"><b>${esc(x.name)}</b>: ${esc(x.status)}${x.error ? ' — ' + esc(x.error) : ` (+${x.added} / −${x.removed})`}${x.warning ? ' · ' + esc(x.warning) : ''}${x.url ? ` · <a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">abrir no Spotify ↗</a>` : ''}</li>`).join('')}</ul>${failed ? '<p class="muted">Nada foi repetido. Clique em "Ler de novo" para uma nova prévia com o que ainda falta.</p>' : ''}`;
    $('publish-results').classList.remove('hidden');
    $('publish-results').scrollIntoView({behavior: 'smooth'});
    notify(failed ? failed.error : 'Playlists gravadas no Spotify.', !!failed);
  });
};

// ---------- início ----------
refresh().then(async () => {
  if (state.connected && state.needs_sync) { go('connect'); await syncLibrary(); }
  else if (state.connected && state.synced_at) { go('playlists'); watchCollect(); }
  else { go('connect'); notify(state.connected ? 'Conectado. Clique em Continuar para importar.' : ''); }
}).catch(e => notify(e.message, true));
