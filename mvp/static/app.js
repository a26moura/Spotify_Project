'use strict';
let page=1, pageSize=25;
let state, filter='all', originFilter='all', query='', consulting=false, currentPlan=null, organizing=false, experimentRunning=false, syncing=false, stopRequested=false;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const split=s=>s.split(',').map(x=>x.trim()).filter(Boolean);
function notify(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);if(error&&$('dialog').open){let message=$('dialog-error');if(!message){message=document.createElement('p');message.id='dialog-error';message.setAttribute('role','alert');$('dialog-body').prepend(message);}message.textContent=text;}}
async function api(path,data){
  const response=await fetch('/api/'+path,data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf},body:JSON.stringify(data)});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Não foi possível concluir.');
  return result;
}
async function refresh(){state=await api('state');render();}
function modal(title,body){$('dialog-title').textContent=title;$('dialog-body').innerHTML=body;if(!$('dialog').open)$('dialog').showModal();}
function close(){ $('dialog').close(); }
async function action(button,job){button.disabled=true;try{await job();}catch(e){notify(e.message,true);}finally{button.disabled=false;}}
const ORIGIN_LABEL={faixa:'pela faixa',album:'pelo álbum',letra:'pela letra',artista:'pelo artista',ia:'sugestão de IA'};
function originMatches(t){
  const g=t.review?'manual':t.genre_origin, l=t.review?'manual':t.language_origin;
  switch(originFilter){
    case 'faixa':case 'album':case 'artista':case 'ia':return g===originFilter;
    case 'lang-letra':return l==='letra';
    case 'lang-ia':return l==='ia';
    case 'manual':return !!t.review;
    case 'no-genre':return !t.review&&!t.genres.length;
    case 'no-language':return !t.review&&!t.languages.length;
    default:return true;
  }
}
function originSelector(){
  let el=$('origin-filter');
  const tracks=state.tracks, n=f=>{const keep=originFilter;originFilter=f;const c=tracks.filter(originMatches).length;originFilter=keep;return c;};
  el.innerHTML=[['all','Qualquer origem'],['faixa','Gênero pela faixa'],['album','Gênero pelo álbum (Deezer)'],['artista','Gênero pelo artista'],['ia','Gênero por IA'],['lang-letra','Idioma pela letra (LRCLIB)'],['lang-ia','Idioma por IA'],['no-genre','Sem gênero'],['no-language','Sem idioma'],['manual','Revisadas por você']]
    .map(([v,label])=>`<option value="${v}" ${v===originFilter?'selected':''}>${label}${v==='all'?'':' ('+n(v)+')'}</option>`).join('');
}
function busy(){return syncing||consulting||organizing||experimentRunning;}
function showStop(visible){$('stop-progress').disabled=false;$('stop-progress').classList.toggle('hidden',!visible);}
function render(){
  const tracks=state.tracks, included=tracks.filter(t=>!t.review?.exclude), assigned=included.filter(t=>t.destinations.length), working=busy();
  const withGenre=tracks.filter(t=>t.genres.length||t.review).length, withLanguage=tracks.filter(t=>t.languages.length||t.review).length, toLookup=tracks.filter(t=>t.lookup==='pending'&&!t.review).length;
  $('total').textContent=tracks.length;$('assigned').textContent=assigned.length;$('missing').textContent=included.length-assigned.length;$('playlist-count').textContent=state.playlists.length;
  $('account-name').textContent=state.display_name;$('connect').classList.toggle('hidden',state.connected);$('logout').classList.toggle('hidden',!state.connected);$('logout').disabled=working;
  $('mode').textContent=state.connected?'Conta conectada · dados locais':'Sem conexão com o Spotify';
  $('step1-status').textContent=!state.connected?'Conecte o Spotify para começar.':!tracks.length?'Nenhuma curtida carregada ainda.':`${withGenre}/${tracks.length} com gênero · ${withLanguage}/${tracks.length} com idioma${toLookup?' · '+toLookup+' a consultar':''}`;
  $('step2-status').textContent=!state.rules.length?'Defina as playlists e critérios primeiro.':!state.ollama_configured?'Selecione um modelo Ollama em Ferramentas avançadas.':`${assigned.length} com destino · ${included.length-assigned.length} sem destino`;
  $('step3-status').textContent=state.connected?'Só adiciona músicas. Para esvaziar uma playlist, use “Recomeçar uma playlist” na etapa 2.':'Disponível depois de conectar o Spotify.';
  $('classify').disabled=!state.connected||working;
  $('organize').disabled=!tracks.length||working;
  $('organize').title=!state.rules.length?'Defina as playlists e critérios primeiro.':!state.ollama_configured?'Selecione um modelo Ollama em Ferramentas avançadas.':'';
  $('edit-names').disabled=working;$('restart').disabled=working||!state.playlists.length;
  $('prepare').disabled=!state.connected||!tracks.length||working;
  $('spotify-library').disabled=working;
  $('import').disabled=!state.connected||working;
  $('collect-labels').disabled=working||!tracks.length;
  $('ai-fill').disabled=working||!tracks.length;
  $('route-local').disabled=working||!state.rules.length||!state.ollama_configured||!tracks.length;
  $('sources').disabled=working;
  const retryCount=tracks.filter(retryEligible).length;
  $('retry-classification').textContent=`Tentar de novo sem classificação (${retryCount})`;
  $('retry-classification').disabled=!retryCount||working;
  $('playlist-cards').innerHTML=state.playlists.map(n=>{
    const rule=state.rules.find(r=>r.name===n);
    const criteria=rule?[rule.description,rule.genres.join(' / '),rule.languages.join(' / '),rule.artists.join(' / ')].filter(Boolean).join(' · '):'';
    const count=tracks.filter(t=>t.destinations.includes(n)).length;
    return `<button class="playlist-card ${filter===n?'active':''}" data-name="${esc(n)}" aria-pressed="${filter===n}" aria-label="Ver músicas da playlist ${esc(n)}, ${count}"><strong>${esc(n)}</strong><span class="card-count">${count}</span><small title="${esc(criteria)}">${esc(criteria||'Interpretação pelo Ollama')}</small></button>`;
  }).join('')||'<p class="muted">Nenhuma playlist definida. Use “Editar playlists e critérios” na etapa 2.</p>';
  $('playlist-cards').querySelectorAll('button').forEach(b=>b.onclick=()=>{filter=filter===b.dataset.name?'all':b.dataset.name;page=1;render();if(filter!=='all')$('library').scrollIntoView({block:'start'});});
  $('view-title').textContent=({all:'Todas as músicas',pending:'Sem destino',excluded:'Fora do projeto'})[filter]||'Playlist: '+filter;
  $('view-select').innerHTML=[['all','Todas as músicas'],['pending','Sem destino'],['excluded','Fora do projeto'],...state.playlists.map(n=>[n,'Playlist: '+n])].map(([v,n])=>`<option value="${esc(v)}" ${v===filter?'selected':''}>${esc(n)}</option>`).join('');
  $('view-subtitle').textContent=state.connected?'Clique em Editar para corrigir gênero, idioma ou destino. Suas escolhas têm prioridade.':'Conecte o Spotify e classifique suas curtidas para começar.';
  originSelector();
  const visible=tracks.filter(t=>originMatches(t)&&(filter==='all'||filter==='excluded'&&t.review?.exclude||filter==='pending'&&!t.review?.exclude&&!t.destinations.length||t.destinations.includes(filter))&&(`${t.title} ${t.artists.join(' ')}`).toLocaleLowerCase().includes(query));
  $('visible-count').textContent=visible.length+(visible.length===1?' música':' músicas');$('empty').classList.toggle('hidden',visible.length>0);
  const pages=Math.max(1,Math.ceil(visible.length/pageSize));page=Math.min(page,pages);
  $('page-info').textContent=`Página ${page} de ${pages} · ${visible.length?((page-1)*pageSize+1):0}–${Math.min(page*pageSize,visible.length)} de ${visible.length}`;
  $('previous-page').disabled=page===1;$('next-page').disabled=page===pages;
  $('tracks').innerHTML=visible.slice((page-1)*pageSize,page*pageSize).map(t=>{
    const genres=t.review?t.review.genres:[...new Set([...t.genres,...(t.source_labels||[]).filter(x=>x.kind!=='language').map(x=>x.label)])], languages=t.review?t.review.languages:t.languages;
    const status=t.review?.exclude?'Fora do projeto':t.review?'Sua escolha':t.genre_origin==='artista'?'Gênero pelo artista — confira':t.genre_origin==='album'?'Gênero pelo álbum — confira':t.lookup==='pending'?'A consultar':t.routing_required&&t.routing_pending?'A distribuir com Ollama':t.routing_required&&t.routing?.decisions?.some(d=>d.verdict==='uncertain')?'Decisão incerta do Ollama':t.destinations.length?'Sugestão para revisar':t.genres.length||t.languages.length?'Sem critério correspondente':'Sem dados suficientes';
    return `<tr><td><a class="track-name" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">${esc(t.title)}</a><div class="artist">${esc(t.artists.join(', '))}</div></td><td class="meta">${esc(genres.join(', ')||'Sem gênero')}${!t.review&&t.genre_origin&&t.genre_origin!=='faixa'?`<span class="origin origin-${t.genre_origin}">${ORIGIN_LABEL[t.genre_origin]}</span>`:''}<small>${esc(languages.join(', ')||'Idioma não identificado')}${!t.review&&['ia','letra'].includes(t.language_origin)?' · '+ORIGIN_LABEL[t.language_origin]:''}</small></td><td><div class="chips">${t.destinations.map(n=>`<span class="chip ${['Frances','Espanhol'].includes(n)?'blue':''}">${esc(n)}</span>`).join('')||'<span class="muted">'+(t.review?.exclude?'Excluída':'Escolher destino')+'</span>'}</div></td><td><span class="status ${!t.review?'pending':''}">${status}</span><button class="edit-row" data-id="${esc(t.id)}">Editar</button></td></tr>`;
  }).join('');
  $('tracks').querySelectorAll('.edit-row').forEach(b=>b.onclick=()=>editTrack(b.dataset.id));
}
function editTrack(id){
  const t=state.tracks.find(t=>t.id===id), review=t.review;
  modal('Editar organização',`<h3>${esc(t.title)}</h3><p>${esc(t.artists.join(', '))}</p><label class="field">Gêneros (separados por vírgula)<input id="genres" value="${esc((review?review.genres:t.genres).join(', '))}"></label><label class="field">Idiomas (separados por vírgula)<input id="languages" value="${esc((review?review.languages:t.languages).join(', '))}"></label><p>Playlists desejadas — escolha quantas quiser.</p><div class="choices">${state.playlists.map(n=>`<label class="choice"><input type="checkbox" name="destination" value="${esc(n)}" ${t.destinations.includes(n)?'checked':''}>${esc(n)}</label>`).join('')}</div><label><input id="exclude-track" type="checkbox" ${review?.exclude?'checked':''}> Deixar fora das playlists do projeto</label><p class="muted">Suas escolhas são preservadas ao importar ou consultar novamente.</p><details><summary>Informações das fontes</summary><p>${esc(t.lookup_note||'Dados da pesquisa inicial. As fontes podem sugerir mais de um gênero.')}</p><p>Origem do gênero: <strong>${esc(ORIGIN_LABEL[t.genre_origin]||'sem gênero')}</strong> · origem do idioma: <strong>${esc(ORIGIN_LABEL[t.language_origin]||'sem idioma')}</strong></p><p>Gêneros sugeridos: ${esc(t.genres.join(', ')||'Nenhum')}. Idiomas registrados/sugeridos: ${esc(t.languages.join(', ')||'Nenhum')}.</p>${t.sources.map(s=>`<a class="source" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.label)} · ${esc(s.level)}</a>`).join('')}</details><div class="dialog-actions"><button class="primary" id="save-review">Salvar escolha</button></div>`);
  const decisions=document.createElement('div');decisions.className='plan-row';decisions.innerHTML=`<h3>Rótulos encontrados nas fontes</h3><p>${esc((t.source_labels||[]).map(x=>x.label+' ('+x.source+')').join(', ')||'Nenhum rótulo registrado ainda.')}</p><h3>Interpretação das playlists pelo Ollama</h3>${t.routing_pending?'<p>As informações ou playlists mudaram. Execute a distribuição novamente.</p>':''}${(t.routing?.decisions||[]).map(d=>`<p><strong>${esc(d.playlist)}</strong>: ${esc({yes:'Pertence',no:'Não pertence',uncertain:'Informação insuficiente'}[d.verdict])} — ${esc(d.reason)}</p>`).join('')}`;$('dialog-body').append(decisions);
  const mode=document.createElement('label');mode.className='field';
  mode.innerHTML=`<input type="checkbox" id="automatic-track" ${!review||review.automatic?'checked':''}> Distribuir automaticamente pelos critérios das playlists`;
  $('exclude-track').parentElement.before(mode);
  function toggleDestinations(){document.querySelectorAll('input[name=destination]').forEach(input=>{input.disabled=$('automatic-track').checked;});}
  $('automatic-track').onchange=toggleDestinations;toggleDestinations();
  if(t.artist_genres?.length){
    const box=document.createElement('div');box.className='plan-row';
    box.innerHTML=`<p>Sugestão anterior pelo artista: <strong>${esc(t.artist_genres.join(', '))}</strong>. Pode não representar esta faixa.</p><button class="secondary" id="accept-artist">Usar estes gêneros nesta revisão</button>`;
    $('genres').parentElement.before(box);
    $('accept-artist').onclick=()=>{$('genres').value=[...new Set([...split($('genres').value),...t.artist_genres])].join(', ');$('automatic-track').checked=true;toggleDestinations();};
  }
  $('save-review').onclick=()=>action($('save-review'),async()=>{
    const result=await api('review',{id,automatic:$('automatic-track').checked,genres:split($('genres').value),languages:split($('languages').value),playlists:[...document.querySelectorAll('input[name=destination]:checked')].map(x=>x.value),exclude:$('exclude-track').checked});
    currentPlan=null;close();await refresh();notify(result.message);
  });
}
function configure(){
  if(state.configured){location.href='/auth/start';return;}
  modal('Conectar sua conta',`<p>Para este piloto, crie um aplicativo na sua conta do <a href="https://developer.spotify.com/dashboard" target="_blank" rel="noopener noreferrer">Spotify for Developers</a>.</p><ol><li>Crie um app e selecione o uso da Web API.</li><li>Cadastre exatamente este endereço de retorno: <code>${esc(state.redirect)}</code>.</li><li>Copie o Client ID para o campo abaixo.</li><li>Se necessário, adicione sua conta aos usuários autorizados do app.</li></ol><p class="muted">O modo de desenvolvimento exige Premium do responsável pelo app. Se o painel não permitir criar apps, a prévia local continua disponível.</p><label class="field">Client ID<input id="client-id" autocomplete="off" maxlength="32" placeholder="Identificador de 32 caracteres"></label><p>Não precisamos de Client Secret nem da sua senha. A autorização acontece no Spotify.</p><div class="dialog-actions"><button id="save-client" class="primary">Salvar e conectar</button></div>`);
  $('save-client').onclick=()=>action($('save-client'),async()=>{await api('config',{client_id:$('client-id').value});location.href='/auth/start';});
}
async function destinationDialog(){
  const result=await api('targets',{});
  for(const name of state.playlists){
    const matches=result.playlists.filter(p=>p.name.trim().toLocaleLowerCase()===name.trim().toLocaleLowerCase());
    if(!state.targets[name]&&matches.length===1)state.targets[name]=matches[0].id;
  }
  modal('Onde salvar suas playlists?',`<p>Escolha uma playlist sua ou crie uma nova. A próxima tela mostrará as adições antes de confirmar.</p>${state.playlists.map((n,i)=>`<label class="field">${esc(n)}<select id="target-${i}"><option value="">Criar nova playlist privada</option>${result.playlists.map(p=>`<option value="${esc(p.id)}" ${state.targets[n]===p.id?'selected':''}>${esc(p.name)} (${esc(p.id.slice(-5))})</option>`).join('')}</select></label>`).join('')}<p class="muted">Atualizações adicionam músicas ausentes. Não removem faixas que já estão no Spotify.</p><div class="dialog-actions"><button id="make-plan" class="primary">Preparar prévia</button></div>`);
  $('make-plan').onclick=()=>action($('make-plan'),async()=>{
    const targets=Object.fromEntries(state.playlists.map((n,i)=>[n,$('target-'+i).value]));
    currentPlan=await api('plan',{targets});showPlan();
  });
}
function showPlan(){
  modal('Confirme a atualização',`<p>Serão adicionadas somente as músicas abaixo. Playlists novas serão privadas. A confirmação vale por 10 minutos.</p>${currentPlan.plans.map(p=>`<div class="plan-row"><strong>${esc(p.name)}</strong><span>${p.uris.length} a adicionar · ${p.already} já presentes</span><p class="muted">${p.id?'Atualizar '+esc(p.target_name):p.total?'Criar nova playlist':'Sem músicas: não será criada'}</p>${p.tracks.length?`<details><summary>Ver as ${p.tracks.length} músicas</summary><ul>${p.tracks.map(t=>`<li>${esc(t.title)}</li>`).join('')}</ul></details>`:''}</div>`).join('')}<label class="field"><input type="checkbox" id="confirm-write"> Conferi a prévia e autorizo estas adições no Spotify.</label><div class="dialog-actions"><button id="write" class="primary" disabled>Confirmar e atualizar Spotify</button></div>`);
  $('confirm-write').onchange=()=>{$('write').disabled=!$('confirm-write').checked;};
  $('write').onclick=()=>action($('write'),async()=>{
    const result=await api('execute',{id:currentPlan.id,confirm:true});currentPlan=null;
    modal('Resultado da atualização',result.results.map(r=>`<div class="plan-row"><strong>${esc(r.name)}</strong><p>${esc(r.status)}${r.added!==undefined?' · '+r.added+' adicionadas':''}</p>${r.error?`<p>${esc(r.error)}</p>`:''}${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">Abrir no Spotify</a>`:''}</div>`).join('')+'<p>Se houve falha, prepare outra prévia. O aplicativo consultará as músicas existentes antes de adicionar novamente.</p>');
    try{await syncLibrary();notify(result.message);}catch(error){await refresh();notify('Gravação encerrada. Não foi possível atualizar a leitura da conta: '+error.message,true);}
  });
}
$('close-dialog').onclick=close;
$('view-select').onchange=()=>{filter=$('view-select').value;page=1;render();};
$('origin-filter').onchange=()=>{originFilter=$('origin-filter').value;page=1;render();};
$('search').oninput=e=>{query=e.target.value.toLocaleLowerCase();page=1;render();};
$('connect').onclick=configure;
$('logout').onclick=()=>action($('logout'),async()=>{const r=await api('logout',{});await refresh();notify(r.message);});
$('import').onclick=()=>action($('import'),syncLibrary);
function stopClassification(){stopRequested=true;consulting=false;notify('Parando após a música atual. Nenhuma nova música ou etapa será iniciada; resultados concluídos ficam salvos.');$('stop-progress').disabled=true;}
$('stop-progress').onclick=stopClassification;
$('prepare').onclick=()=>action($('prepare'),destinationDialog);
$('edit-names').onclick=editRules;

function editRules(){
  modal('Escolha suas playlists e critérios',`<p>Dê um nome e descreva a intenção de cada playlist. O Ollama interpretará os rótulos encontrados nos sites para decidir os destinos.</p><p>Valores no mesmo campo significam <strong>ou</strong>; campos diferentes significam <strong>e</strong>. Exemplo: gênero Pop + idioma Espanhol seleciona pop em espanhol. Campos vazios não restringem; sem critérios, o modelo interpreta o nome e a descrição e pode sinalizar informação insuficiente.</p><p><strong>Rótulos que não contam</strong> tiram da playlist qualquer música com um desses gêneros, mesmo que ela atenda aos outros critérios. Use os nomes como as fontes escrevem (veja em Editar → Informações das fontes). Ex.: em Trap - Br, <em>trap latino, Latin Music</em>; em Funk, <em>funk internacional</em>. Quando os rótulos não diferenciam (trap americano e brasileiro aparecem só como <em>trap</em>), combine com o idioma, ex.: Português.</p><p class="muted">Renomear aqui preserva destinos e escolhas locais. O nome de uma playlist já existente no Spotify permanece como está.</p><div id="rule-list"></div><button id="add-rule" class="secondary">＋ Adicionar playlist</button><div class="dialog-actions"><button class="primary" id="save-rules">Salvar critérios</button></div>`);
  function addRule(rule={name:'',genres:[],languages:[],artists:[]},existing=false){
    const row=document.createElement('fieldset');row.className='rule-editor';
    if(existing)row.dataset.previousName=rule.name;
    row.innerHTML=`<legend>Playlist</legend><label class="field">Nome<input data-field="name" maxlength="80" value="${esc(rule.name)}" placeholder="Ex.: Meu pop em espanhol"></label><label class="field">Descrição / intenção da playlist<input data-field="description" maxlength="1000" value="${esc(rule.description||'')}" placeholder="Ex.: rock alternativo e indie para viajar"></label><div class="rule-fields">${[['genres','Gêneros','Pop, Rock'],['languages','Idiomas','Espanhol'],['artists','Artistas','Nome exato do artista']].map(([key,label,placeholder])=>`<label class="field">${label}<input data-field="${key}" value="${esc(rule[key].join(', '))}" placeholder="${placeholder}"></label>`).join('')}</div><label class="field">Rótulos que não contam<input data-field="exclude_labels" value="${esc((rule.exclude_labels||[]).join(', '))}" placeholder="Ex.: trap latino, Latin Music"></label><button class="text-button remove-rule">Remover esta playlist</button>`;
    row.querySelector('.remove-rule').onclick=()=>row.remove();$('rule-list').append(row);
  }
  state.rules.forEach(r=>addRule(r,true));$('add-rule').onclick=()=>addRule();
  $('save-rules').onclick=()=>action($('save-rules'),async()=>{
    const rules=[...document.querySelectorAll('.rule-editor')].map(row=>{
      const rule={name:row.querySelector('[data-field=name]').value,description:row.querySelector('[data-field=description]').value};
      if(row.dataset.previousName)rule.previous_name=row.dataset.previousName;
      for(const field of ['genres','languages','artists','exclude_labels'])rule[field]=split(row.querySelector(`[data-field=${field}]`).value);
      return rule;
    });
    const result=await api('rules',{rules});currentPlan=null;close();filter='all';await refresh();notify(result.message);
  });
}

function retryEligible(t){return !t.review&&!t.genres.length&&!t.languages.length&&!t.destinations.length;}
async function consultSources(source='ollama',onlyEmpty=false){
  if(!organizing)stopRequested=false;
  consulting=true;showStop(true);render();
  let result, pauses=0;
  const pending=t=>t.lookup==='pending'&&!t.review&&(!onlyEmpty||retryEligible(t));
  beginProgress(state.tracks.filter(pending).length);
  try{
    while(consulting){
      const current=state.tracks.find(pending);
      processingTrack(current);
      notify('Classificando músicas. Você pode parar após a música atual…');
      try{result=await api('enrich',{source,only_empty:onlyEmpty});}
      catch(error){
        // Compatibility with the running server: only its explicit metadata cooldown
        // message can schedule a retry. Never retry playlist writes or other API calls.
        const delay=source==='musicbrainz'?metadataCooldown(error.message):0;
        if(!delay)throw error;
        if(!consulting)return false;
        if(pauses>=8)throw new Error('A fonte continua indisponível após oito retomadas automáticas. O progresso está salvo. Tente mais tarde em Ferramentas avançadas → Buscar rótulos nos sites, ou revise e salve apenas as músicas já organizadas.');
        pauses++;
        if(!await waitForMetadata(Math.min(300,Math.max(delay,60*2**(pauses-1))),pauses))return false;
        continue;
      }
      if(result.track)completeTrack(result.track,result.note);
      await refresh();notify(result.message+' Restantes: '+result.remaining);
      if(result.remaining===0)return !stopRequested;
    }
    return false;
  }catch(error){progressLog('Falha: '+error.message);throw error;}finally{finishProgress(progress.done>=progress.total?'Concluído':'Interrompido');consulting=false;showStop(false);render();}
}

function metadataCooldown(message){
  if(!/(MusicBrainz|Wikidata|musicbrainz\.org|www\.wikidata\.org)/i.test(message)||!/consultas? pausad[ao]s?/i.test(message))return 0;
  const match=message.match(/Aguarde (\d+) segundos/i);
  return match?Number(match[1]):0;
}
async function waitForMetadata(seconds,attempt){
  const deadline=Date.now()+seconds*1000;
  while(consulting&&Date.now()<deadline){
    const remaining=Math.ceil((deadline-Date.now())/1000);
    notify(`Fonte temporariamente indisponível. Retomada automática ${attempt}/8 em ${remaining}s. Você pode parar; suas revisões estão salvas.`);
    await new Promise(resolve=>setTimeout(resolve,Math.min(1000,remaining*1000)));
  }
  return consulting;
}

$('classify').onclick=()=>action($('classify'),async()=>{
  organizing=true;stopRequested=false;render();
  try{
    await syncLibrary();
    if(!state.tracks.length){notify('Sua biblioteca não contém músicas curtidas disponíveis.');return;}
    await api('labels-start',{});await refresh();
    notify('Buscando gênero e idioma nas fontes (faixa, álbum, letra e artista)…');
    if(!await consultSources('musicbrainz')||stopRequested){notify('Classificação interrompida. O que já foi classificado está salvo; clique de novo para continuar de onde parou.');return;}
    if(!state.ollama_configured){notify('Fontes consultadas. Para completar o que ficou vazio com IA, selecione um modelo em Ferramentas avançadas → Modelo Ollama.');return;}
    if(!await completeWithAI())return;
    const g=state.tracks.filter(t=>t.genres.length||t.review).length,l=state.tracks.filter(t=>t.languages.length||t.review).length;
    notify(`Classificação concluída: ${g}/${state.tracks.length} com gênero e ${l}/${state.tracks.length} com idioma. Use o filtro de origem para conferir. Depois clique em Organizar nas playlists (etapa 2).`);
  }finally{organizing=false;render();}
});
$('organize').onclick=()=>action($('organize'),async()=>{
  if(!state.rules.length){notify('Defina as playlists e seus critérios antes de organizar.');editRules();return;}
  if(!state.ollama_configured){notify('Selecione um modelo Ollama para distribuir nas playlists.');sourceDialog();return;}
  organizing=true;stopRequested=false;render();
  try{
    if(!await distributeLocally()||stopRequested){notify('Distribuição interrompida. Decisões concluídas foram salvas.');return;}
    await destinationDialog();
  }finally{organizing=false;render();}
});
$('about').onclick=()=>modal('Fontes e sugestões','<p>Ollama executa um modelo local para sugerir gêneros e idiomas a partir de título, artistas e metadados disponíveis. Não analisa áudio. As respostas são hipóteses para revisão, e não evidências documentais.</p><p>O botão Classificar músicas busca gênero e idioma no MusicBrainz e Wikidata (faixa), no Deezer (gênero do álbum, pelo ISRC), no LRCLIB (idioma detectado localmente na letra, sem guardar a letra) e no MusicBrainz (artista), e completa o que faltar com o Ollama. O botão Organizar nas playlists usa o Ollama para interpretar cada playlist pelo nome, descrição e critérios e mostra a prévia antes de salvar no Spotify. Uma música pode pertencer a várias playlists. Em Ferramentas avançadas, você também pode executar cada etapa separadamente. O botão Parar interrompe após a música atual. Suas revisões manuais têm prioridade.</p>');
refresh().then(async()=>{if(state.connected&&state.needs_sync)await syncLibrary();else notify(state.connected?'Biblioteca carregada. Classificações anteriores preservadas.':'Conecte o Spotify para carregar curtidas e playlists.');}).catch(e=>notify(e.message,true));

function sourceDialog(){
  modal('Fontes de classificação',`<p>O Ollama sugere gêneros e idiomas usando um modelo local. As sugestões podem conter erros; suas revisões são preservadas.</p><p>Modelo: <strong>${esc(state.ollama_model||'Não selecionado')}</strong></p><button id="load-models" class="secondary">Buscar modelos instalados</button><label class="field">Modelo local<select id="ollama-model"><option value="${esc(state.ollama_model||'')}">${esc(state.ollama_model||'Busque os modelos instalados')}</option></select></label><button id="save-ollama" class="secondary">Salvar modelo</button><p class="muted">Abra o Ollama neste computador. Instale um modelo de texto no Ollama caso a lista esteja vazia. Modelos de nuvem não são utilizados.</p><label class="field">Fonte<select id="metadata-source"><option value="saved">Somente dados salvos</option><option value="ollama" ${state.ollama_configured?'selected':''} ${state.ollama_configured?'':'disabled'}>Ollama — sugestões locais</option><option value="musicbrainz">MusicBrainz + Wikidata</option></select></label><p>O teste seleciona até 30 músicas sem destino e sem revisão. Os resultados só entram na biblioteca quando você aplicar.</p><div class="choices"><button id="run-experiment" class="primary">Testar até 30 músicas</button><button id="add-categories" class="secondary">Adicionar Eletrônica, Hip-Hop/Rap e Metal</button></div><details><summary>Classificar a biblioteca</summary><p>Processa as músicas pendentes sem revisão manual.</p><label><input type="checkbox" id="retry-missing"> Reclassificar músicas sem destino e sem revisão</label><div class="dialog-actions"><button id="run-source" class="secondary">Classificar biblioteca</button></div></details>`);
  $('load-models').onclick=()=>action($('load-models'),async()=>{const r=await api('ollama-models',{});$('ollama-model').innerHTML=r.models.length?r.models.map(n=>`<option value="${esc(n)}" ${n===state.ollama_model?'selected':''}>${esc(n)}</option>`).join(''):'<option value="">Nenhum modelo local instalado</option>';notify(r.models.length+' modelos locais encontrados.');});
  $('save-ollama').onclick=()=>action($('save-ollama'),async()=>{const r=await api('metadata-config',{ollama_model:$('ollama-model').value});await refresh();sourceDialog();notify(r.message);});
  $('add-categories').onclick=()=>action($('add-categories'),async()=>{const r=await api('extra-rules',{});await refresh();close();notify(r.message);});
  $('run-source').onclick=()=>action($('run-source'),async()=>{
    const source=$('metadata-source').value;
    if(source==='saved')throw new Error('Escolha Ollama ou MusicBrainz para classificar a biblioteca.');
    if($('retry-missing').checked)await api('retry-unclassified',{});
    close();await refresh();await consultSources(source);
  });
  $('run-experiment').onclick=()=>runExperiment($('metadata-source').value);
}
async function runExperiment(source){
  experimentRunning=true;render();
  let start, result;
  try{
    start=await api('experiment-start',{source});
    beginProgress(start.total);
    modal('Teste de classificação',`<p id="experiment-progress" role="status">Preparando ${start.total} músicas…</p><p id="experiment-current"></p><p id="experiment-eta"></p><details><summary>Log do teste</summary><pre id="experiment-log" class="classification-log"></pre></details><button id="stop-experiment" class="secondary">Parar teste</button>`);
    $('stop-experiment').onclick=()=>{experimentRunning=false;$('experiment-progress').textContent='Parando após a consulta atual…';};
    do{
      if(!experimentRunning)break;
      processingTrack(result?result.next_track:start.next_track);
      result=await api('experiment-step',{id:start.id});
      if(result.results.length>progress.done){const row=result.results[result.results.length-1];completeTrack(row,row.note);}
      if($('experiment-progress'))$('experiment-progress').textContent=`${result.results.length}/${start.total} verificadas · ${result.assigned} com destino proposto · ${result.seconds}s em consultas`;
    }while(result.remaining>0);
    if(!experimentRunning||!result||result.remaining){notify('Teste interrompido. Nenhum resultado foi aplicado à biblioteca.');close();return;}
    modal('Resultado do teste',`<p>${source==='saved'?'Teste local dos novos critérios, sem consultas externas.':'Consulta de metadados concluída; a correção musical dos resultados ainda precisa da sua revisão.'}</p><p><strong>${result.assigned}/${result.results.length}</strong> com destino proposto · ${result.seconds}s em consultas.</p>${result.results.map(r=>`<div class="plan-row"><strong>${esc(r.title)}</strong><p>${esc(r.artists.join(', '))} · motivo anterior: ${esc(r.reason)}</p><p>Gêneros: ${esc(r.genres.join(', ')||'Não encontrados')}<br>Idiomas: ${esc((r.languages||[]).join(', ')||'Não identificados')}<br>Destinos propostos: ${esc(r.after.join(', ')||'Nenhum')}${r.artist_genres.length?'<br>Sugestão pelo artista, ainda não aplicada: '+esc(r.artist_genres.join(', ')):''}</p><p class="muted">${esc(r.note||'')}</p></div>`).join('')}<p>Aplicar salva os resultados locais e adiciona os três critérios. Não cria playlists no Spotify. Suas revisões são preservadas.</p><label class="field"><input type="checkbox" id="confirm-experiment"> Conferi os resultados e os novos critérios.</label><div class="dialog-actions"><button id="apply-experiment" class="primary" disabled>Aplicar à biblioteca local</button></div>`);
    $('confirm-experiment').onchange=()=>{$('apply-experiment').disabled=!$('confirm-experiment').checked;};
    $('apply-experiment').onclick=()=>action($('apply-experiment'),async()=>{const r=await api('experiment-apply',{id:start.id,confirm:true});await refresh();close();notify(r.message);});
  }catch(e){progressLog('Falha: '+e.message);notify(e.message,true);modal('Teste pausado',`<p>${esc(e.message)}</p><p>Nenhum resultado foi aplicado. Confira a fonte e inicie outro teste quando estiver disponível.</p>`);}
  finally{finishProgress(progress.done>=progress.total?'Teste concluído':'Teste interrompido');experimentRunning=false;render();}
}
$('sources').onclick=sourceDialog;
const retryButton=$('retry-classification');
retryButton.onclick=()=>{
  const count=state.tracks.filter(retryEligible).length;
  modal('Tentar novamente sem classificação',`<p>${count} músicas sem gênero e sem idioma serão consultadas novamente no Ollama, sem reutilizar a resposta anterior em cache.</p><p>Músicas classificadas, com destino definido ou com revisão manual ficam de fora. Um novo teste ainda pode terminar sem informação suficiente.</p><p>Modelo local: <strong>${esc(state.ollama_model||'Não configurado')}</strong></p><div class="dialog-actions"><button id="retry-settings" class="secondary">Configurar fonte</button><button id="retry-start" class="primary" ${!state.ollama_configured||!count?'disabled':''}>Tentar novamente</button></div>`);
  $('retry-settings').onclick=sourceDialog;
  $('retry-start').onclick=()=>action($('retry-start'),async()=>{
    const result=await api('retry-unclassified',{only_empty:true});close();await refresh();
    if(!result.count){notify('Nenhuma música sem classificação para tentar novamente.');return;}
    await consultSources('ollama',true);
  });
};
$('dialog').addEventListener('close',()=>{if(experimentRunning)experimentRunning=false;});

$('previous-page').onclick=()=>{page--;render();$('library').scrollIntoView({block:'start'});};
$('next-page').onclick=()=>{page++;render();$('library').scrollIntoView({block:'start'});};
$('page-size').onchange=()=>{pageSize=Number($('page-size').value);page=1;render();};
let progress={total:0,done:0,started:0,timer:null,logs:[],current:''};
function duration(seconds){seconds=Math.max(0,Math.ceil(seconds));return seconds<60?seconds+'s':Math.floor(seconds/60)+'min '+seconds%60+'s';}
function beginProgress(total){
  clearInterval(progress.timer);progress={total,done:0,started:Date.now(),timer:null,logs:[],current:'Preparando…'};
  $('classification-progress').classList.remove('hidden');updateProgress();progress.timer=setInterval(updateProgress,1000);
}
function progressLog(message){
  progress.logs.push(new Date().toLocaleTimeString()+' · '+message);progress.logs=progress.logs.slice(-100);
  for(const id of ['classification-log','experiment-log'])if($(id)){$(id).textContent=progress.logs.join('\n');$(id).scrollTop=$(id).scrollHeight;}
}
function processingTrack(track){if(!track)return;progress.current=track.title+' — '+track.artists.join(', ');progressLog('Processando: '+progress.current);updateProgress();}
function completeTrack(track,note){progress.done++;progress.completedAt=Date.now();progressLog('Concluída: '+track.title+(note?' · '+note:''));updateProgress();}
function updateProgress(){
  const elapsed=(Date.now()-progress.started)/1000;
  const estimate=progress.done?Math.max(0,((progress.completedAt-progress.started)/1000/progress.done)*progress.total-elapsed):null;
  const eta=progress.done>=progress.total?'Finalizado':estimate===null?'Calculando estimativa após a primeira música…':estimate===0?'Recalculando estimativa…':'Tempo restante estimado: '+duration(estimate);
  $('classification-count').textContent=`${progress.done}/${progress.total} músicas · Decorrido: ${duration(elapsed)}`;
  $('classification-bar').max=Math.max(1,progress.total);$('classification-bar').value=progress.done;
  $('classification-current').textContent=progress.current;$('classification-eta').textContent=eta;
  if($('experiment-current'))$('experiment-current').textContent='Processando: '+progress.current;
  if($('experiment-eta'))$('experiment-eta').textContent=eta;
}
function finishProgress(status){clearInterval(progress.timer);progress.current=status;updateProgress();$('classification-eta').textContent=status;progressLog(status);}

async function syncLibrary(){
  syncing=true;render();
  try{
    notify('Carregando suas curtidas e playlists do Spotify…');
    const start=await api('sync-start',{});notify(start.message);
    let result;
    do {result=await api('sync-step',{id:start.id});notify(result.message);} while(result.remaining>0);
    await refresh();notify(result.message);
  }finally{syncing=false;render();}
}
function spotifyLibraryDialog(){
  const playlists=state.spotify_library?.playlists||[];
  modal('Sua biblioteca no Spotify',`<p>${playlists.length} playlists sincronizadas. A classificação considera suas músicas curtidas. As faixas já presentes nas playlists são preservadas.</p>${!playlists.length?'<p>Conecte sua conta e sincronize a biblioteca para ver suas playlists.</p>':''}${playlists.map((p,i)=>`<div class="plan-row"><strong>${esc(p.name)}</strong><p>${p.unavailable?'Conteúdo indisponível para este aplicativo':p.tracks.length+' músicas carregadas'} · ${p.owned?'Sua playlist':'Playlist seguida ou compartilhada'}</p>${p.owned?`<button class="secondary" data-adopt="${i}" ${Object.values(state.targets).includes(p.id)?'disabled':''}>${Object.values(state.targets).includes(p.id)?'Já vinculada':'Usar na organização'}</button>`:''}${p.tracks.length?`<details><summary>Ver músicas existentes</summary><ul>${p.tracks.map(t=>`<li>${esc(t.title)} — ${esc(t.artists.join(', '))}</li>`).join('')}</ul></details>`:''}</div>`).join('')}<p>Para playlists com o mesmo nome de um critério, escolha o destino na prévia. Apenas suas próprias playlists podem receber adições. Para esvaziar uma, use Recomeçar uma playlist (etapa 2).</p>`);
  document.querySelectorAll('[data-adopt]').forEach(b=>b.onclick=()=>action(b,async()=>{const r=await api('adopt-playlist',{id:playlists[Number(b.dataset.adopt)].id});await refresh();editRules();notify(r.message);}));
}
async function clearPlaylistDialog(id){
  const preview=await api('clear-preview',{id});
  if(!preview.count){modal('Esvaziar playlist',`<p>A playlist <strong>${esc(preview.name)}</strong> já está vazia no Spotify.</p><div class="dialog-actions"><button id="clear-back" class="secondary">Voltar</button></div>`);$('clear-back').onclick=restartDialog;return;}
  modal('Esvaziar playlist',`<p>Prévia: <strong>${preview.count} músicas</strong> serão removidas da playlist <strong>${esc(preview.name)}</strong> no Spotify. A playlist continua existindo; suas curtidas, classificações e revisões locais não mudam.</p><p>Esta ação não pode ser desfeita pelo aplicativo. Depois, use “Organizar nas playlists” (etapa 2) para preenchê-la de novo.</p><details><summary>Ver as ${preview.count} músicas</summary><ul>${preview.tracks.map(t=>`<li>${esc(t.title)} — ${esc(t.artists.join(', '))}</li>`).join('')}</ul></details><div class="dialog-actions"><button id="clear-back" class="secondary">Cancelar</button><button id="clear-confirm" class="primary">Remover ${preview.count} músicas</button></div>`);
  $('clear-back').onclick=restartDialog;
  $('clear-confirm').onclick=()=>action($('clear-confirm'),async()=>{const r=await api('clear-execute',{id:preview.id,confirm:true});await refresh();restartDialog();notify(r.message);});
}
function restartDialog(){
  const linked=name=>state.targets[name]&&(state.spotify_library?.playlists||[]).find(p=>p.id===state.targets[name]);
  modal('Recomeçar uma playlist',`<p>Escolha onde recomeçar. As duas opções podem ser usadas juntas.</p><ul><li><strong>Só no app</strong> apaga as decisões do Ollama para essa playlist. Nada muda no Spotify. Na próxima “Organizar nas playlists”, o Ollama reavalia as músicas só para ela. Critérios explícitos e revisões manuais continuam valendo.</li><li><strong>Esvaziar no Spotify</strong> remove todas as músicas da playlist na sua conta, depois de uma prévia e da sua confirmação. A playlist continua existindo.</li></ul>${state.playlists.map((n,i)=>{const p=linked(n),count=state.tracks.filter(t=>t.destinations.includes(n)).length;return `<div class="plan-row"><strong>${esc(n)}</strong><span>${count} com destino no app</span><p class="muted">${p?'No Spotify: '+esc(p.name)+(p.unavailable?'':' · '+p.tracks.length+' músicas na última sincronização'):'Ainda sem playlist vinculada no Spotify'}</p><button class="secondary" data-reset="${i}">Só no app</button><button class="secondary" data-empty="${i}" ${!p||!state.connected?'disabled':''}>Esvaziar no Spotify</button></div>`;}).join('')||'<p>Nenhuma playlist definida.</p>'}`);
  document.querySelectorAll('[data-reset]').forEach(b=>b.onclick=()=>{
    const name=state.playlists[Number(b.dataset.reset)];
    modal('Recomeçar só no app',`<p>As decisões do Ollama para <strong>${esc(name)}</strong> serão apagadas neste computador. O Spotify não muda.</p><p>Músicas que entram pelos critérios explícitos da playlist ou por revisão manual continuam com esse destino.</p><div class="dialog-actions"><button id="reset-back" class="secondary">Cancelar</button><button id="reset-confirm" class="primary">Apagar decisões</button></div>`);
    $('reset-back').onclick=restartDialog;
    $('reset-confirm').onclick=()=>action($('reset-confirm'),async()=>{const r=await api('routing-reset',{name});currentPlan=null;await refresh();restartDialog();notify(r.message);});
  });
  document.querySelectorAll('[data-empty]').forEach(b=>b.onclick=()=>action(b,()=>clearPlaylistDialog(state.targets[state.playlists[Number(b.dataset.empty)]])));
}
$('restart').onclick=restartDialog;
$('spotify-library').onclick=spotifyLibraryDialog;

async function distributeLocally(){
  await api('route-start',{});await refresh();
  consulting=true;showStop(true);render();
  beginProgress(state.tracks.filter(t=>t.routing_pending).length);
  try{
    while(consulting&&!stopRequested){
      processingTrack(state.tracks.find(t=>t.routing_pending));
      notify('Etapa 2: Ollama está decidindo os destinos pelas informações da música…');
      const result=await api('route-step',{});
      if(result.track)completeTrack(result.track,result.note);
      await refresh();notify(result.message+' Restantes: '+result.remaining);
      if(result.remaining===0)return !stopRequested;
    }
    return false;
  }finally{finishProgress(stopRequested?'Interrompido':'Distribuição encerrada');consulting=false;showStop(false);render();}
}
async function completeWithAI(){
  const r=await api('ai-fill-start',{});await refresh();
  if(!r.count){notify('Nenhuma música sem gênero ou idioma para completar com o Ollama.');return true;}
  notify('Etapa 2: completando gênero e idioma com o Ollama ('+r.count+' músicas)…');
  if(!await consultSources('ollama')||stopRequested){notify('Complemento com IA interrompido. Resultados concluídos foram salvos.');return false;}
  return true;
}
const aiButton=$('ai-fill');
aiButton.onclick=()=>action(aiButton,async()=>{stopRequested=false;if(!state.ollama_configured){sourceDialog();return;}await completeWithAI();});
const labelsButton=$('collect-labels');
labelsButton.onclick=()=>action(labelsButton,async()=>{stopRequested=false;await api('labels-start',{});await refresh();await consultSources('musicbrainz');});
const routeButton=$('route-local');
routeButton.onclick=()=>action(routeButton,async()=>{stopRequested=false;await distributeLocally();});
