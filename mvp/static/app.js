'use strict';
let state, filter='all', query='', consulting=false, currentPlan=null;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const split=s=>s.split(',').map(x=>x.trim()).filter(Boolean);
function notify(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
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
function render(){
  const tracks=state.tracks, included=tracks.filter(t=>!t.review?.exclude), assigned=included.filter(t=>t.destinations.length);
  $('total').textContent=tracks.length;$('assigned').textContent=assigned.length;$('missing').textContent=included.length-assigned.length;$('playlist-count').textContent=state.playlists.length;
  $('account-name').textContent=state.display_name;$('connect').classList.toggle('hidden',state.connected);$('logout').classList.toggle('hidden',!state.connected);
  $('mode').textContent=state.connected?'Conta conectada · dados locais':'Piloto local · sem conexão';
  $('import').disabled=!state.connected;$('prepare').disabled=!state.connected||!tracks.length;
  $('sample').disabled=state.connected;$('full').disabled=state.connected;
  $('playlist-nav').innerHTML=state.playlists.map(n=>`<button class="nav ${filter===n?'active':''}" data-name="${esc(n)}">${esc(n)}<span class="count">${tracks.filter(t=>t.destinations.includes(n)).length}</span></button>`).join('');
  $('playlist-nav').querySelectorAll('button').forEach(b=>b.onclick=()=>{filter=b.dataset.name;render();});
  for(const n of ['all','pending','excluded'])$(n).classList.toggle('active',filter===n);
  $('view-title').textContent=({all:'Todas as músicas',pending:'Sem destino',excluded:'Fora do projeto'})[filter]||filter;
  let selector=$('view-select');
  if(!selector){selector=document.createElement('select');selector.id='view-select';selector.setAttribute('aria-label','Filtrar biblioteca');selector.onchange=()=>{filter=selector.value;render();};document.querySelector('.filter-row').prepend(selector);}
  selector.innerHTML=[['all','Todas as músicas'],['pending','Sem destino'],['excluded','Fora do projeto'],...state.playlists.map(n=>[n,n])].map(([v,n])=>`<option value="${esc(v)}" ${v===filter?'selected':''}>${esc(n)}</option>`).join('');
  $('view-subtitle').textContent=state.connected?'Escolha os destinos e revise antes de atualizar o Spotify.':'Amostra pessoal revisada. Explore e ajuste sem alterar o Spotify.';
  const visible=tracks.filter(t=>(filter==='all'||filter==='excluded'&&t.review?.exclude||filter==='pending'&&!t.review?.exclude&&!t.destinations.length||t.destinations.includes(filter))&&(`${t.title} ${t.artists.join(' ')}`).toLocaleLowerCase().includes(query));
  $('visible-count').textContent=visible.length+(visible.length===1?' música':' músicas');$('empty').classList.toggle('hidden',visible.length>0);
  $('tracks').innerHTML=visible.map(t=>{
    const genres=t.review?t.review.genres:t.genres, languages=t.review?t.review.languages:t.languages;
    const status=t.review?.exclude?'Fora do projeto':t.review?'Sua escolha':t.lookup==='pending'?'A consultar':'Sugestão para revisar';
    return `<tr><td><a class="track-name" href="${esc(t.url)}" target="_blank" rel="noopener noreferrer">${esc(t.title)}</a><div class="artist">${esc(t.artists.join(', '))}</div></td><td class="meta">${esc(genres.join(', ')||'Sem gênero')}<small>${esc(languages.join(', ')||'Idioma não identificado')}</small></td><td><div class="chips">${t.destinations.map(n=>`<span class="chip ${['Frances','Espanhol'].includes(n)?'blue':''}">${esc(n)}</span>`).join('')||'<span class="muted">'+(t.review?.exclude?'Excluída':'Escolher destino')+'</span>'}</div></td><td><span class="status ${!t.review?'pending':''}">${status}</span><button class="edit-row" data-id="${esc(t.id)}">Editar</button></td></tr>`;
  }).join('');
  $('tracks').querySelectorAll('.edit-row').forEach(b=>b.onclick=()=>editTrack(b.dataset.id));
}
function editTrack(id){
  const t=state.tracks.find(t=>t.id===id), review=t.review;
  modal('Editar organização',`<h3>${esc(t.title)}</h3><p>${esc(t.artists.join(', '))}</p><label class="field">Gêneros (separados por vírgula)<input id="genres" value="${esc((review?review.genres:t.genres).join(', '))}"></label><label class="field">Idiomas (separados por vírgula)<input id="languages" value="${esc((review?review.languages:t.languages).join(', '))}"></label><p>Playlists desejadas — escolha quantas quiser.</p><div class="choices">${state.playlists.map(n=>`<label class="choice"><input type="checkbox" name="destination" value="${esc(n)}" ${t.destinations.includes(n)?'checked':''}>${esc(n)}</label>`).join('')}</div><label><input id="exclude-track" type="checkbox" ${review?.exclude?'checked':''}> Deixar fora das playlists do projeto</label><p class="muted">Suas escolhas são preservadas ao importar ou consultar novamente.</p><details><summary>Informações das fontes</summary><p>${esc(t.lookup_note||'Dados da pesquisa inicial. As fontes podem sugerir mais de um gênero.')}</p><p>Gêneros sugeridos: ${esc(t.genres.join(', ')||'Nenhum')}. Idiomas documentados: ${esc(t.languages.join(', ')||'Nenhum')}.</p>${t.sources.map(s=>`<a class="source" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.label)} · ${esc(s.level)}</a>`).join('')}</details><div class="dialog-actions"><button class="primary" id="save-review">Salvar escolha</button></div>`);
  $('save-review').onclick=()=>action($('save-review'),async()=>{
    const result=await api('review',{id,genres:split($('genres').value),languages:split($('languages').value),playlists:[...document.querySelectorAll('input[name=destination]:checked')].map(x=>x.value),exclude:$('exclude-track').checked});
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
    await refresh();notify(result.message);
  });
}
$('close-dialog').onclick=close;
for(const f of ['all','pending','excluded'])$(f).onclick=()=>{filter=f;render();};
$('search').oninput=e=>{query=e.target.value.toLocaleLowerCase();render();};
$('connect').onclick=configure;
$('logout').onclick=()=>action($('logout'),async()=>{const r=await api('logout',{});await refresh();notify(r.message);});
$('import').onclick=()=>action($('import'),async()=>{notify('Importando músicas curtidas…');const r=await api('import',{});await refresh();notify(r.message);});
for(const [id,full] of [['sample',false],['full',true]])$(id).onclick=()=>action($(id),async()=>{const r=await api('demo',{full});await refresh();notify(r.message+' As músicas sem revisão ficam visíveis para classificação.');});
$('pilot').onclick=()=>action($('pilot'),async()=>{const r=await api('pilot-review',{});await refresh();notify(r.message);});
$('enrich').onclick=()=>action($('enrich'),async()=>{
  consulting=true;$('stop').classList.remove('hidden');
  try{let result;do{notify('Consultando fontes públicas. Você pode parar após a música atual…');result=await api('enrich',{});await refresh();notify(result.message+' Restantes: '+result.remaining);}while(consulting&&result.remaining>0);}
  finally{consulting=false;$('stop').classList.add('hidden');}
});
$('stop').onclick=()=>{consulting=false;notify('A consulta será interrompida após a música atual. O progresso fica salvo.');};
$('prepare').onclick=()=>action($('prepare'),destinationDialog);
$('edit-names').onclick=()=>{
  modal('Suas playlists',`<p>Separe os nomes por vírgulas. Espanhol e Frances usam o idioma; os outros nomes correspondem aos gêneros ou às suas escolhas manuais.</p><label class="field">Nomes<input id="names" value="${esc(state.playlists.join(', '))}"></label><p class="muted">Para remover uma playlist, retire primeiro suas associações nas músicas revisadas.</p><div class="dialog-actions"><button class="primary" id="save-names">Salvar playlists</button></div>`);
  $('save-names').onclick=()=>action($('save-names'),async()=>{const r=await api('names',{names:split($('names').value)});close();filter='all';await refresh();notify(r.message);});
};
$('about').onclick=()=>modal('Fontes e sugestões','<p>MusicBrainz fornece candidatos, gêneros e idiomas das obras. Wikidata complementa os dados quando existe um vínculo direto. Uma correspondência de título e artista ainda precisa de revisão da versão.</p><p>As informações da amostra foram pesquisadas anteriormente. Nenhum áudio é analisado e nenhuma informação é enviada a modelos de IA.</p><p>Este piloto usa tags do MusicBrainz em contexto pessoal não comercial (CC BY-NC-SA 3.0). Dados estruturados do Wikidata são CC0. A publicação para terceiros depende de avaliar permissões, acesso ao Spotify e hospedagem.</p><a href="https://musicbrainz.org/doc/About/Data_License" target="_blank" rel="noopener noreferrer">Licenças MusicBrainz</a> · <a href="https://www.wikidata.org/wiki/Wikidata:Copyright" target="_blank" rel="noopener noreferrer">Wikidata</a>');
refresh().then(()=>notify(state.connected?'Conta conectada. Importe suas curtidas para começar.':`Piloto local: ${state.tracks.length} músicas disponíveis. Nenhuma alteração será feita no Spotify sem conexão e confirmação.`)).catch(e=>notify(e.message,true));
