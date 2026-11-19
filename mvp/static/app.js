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
  render();
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

// ---------- início ----------
refresh().then(async () => {
  if (state.connected && state.needs_sync) { go('connect'); await syncLibrary(); }
  else if (state.connected && state.synced_at) { go('playlists'); watchCollect(); }
  else { go('connect'); notify(state.connected ? 'Conectado. Clique em Continuar para importar.' : ''); }
}).catch(e => notify(e.message, true));
