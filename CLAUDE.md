# Spotify Project — contexto para o Claude Code

Responda em português. Leia README.md, mvp/README.md, mvp/FLUXO.md e mvp/CLASSIFICACAO.md antes de mudanças grandes.

## O que é
App local (Python 3, só biblioteca padrão; servidor em mvp/server.py, interface em mvp/static/) em forma de jogo: importa curtidas e as playlists próprias do Spotify, busca informações das músicas, mostra uma música por vez com prévia de 30 s, o usuário arrasta para as playlists e, depois de uma prévia final confirmada, o app grava no Spotify.

## Estado (20/11/2026)
- Nova versão (jogo) concluída em 6 etapas em 19–20/11/2026; ainda **não usada na conta real**. Remoção de músicas e limpeza da descrição temporária só foram testadas com Spotify simulado.
- Conta real: 351 curtidas, 7 playlists. Dados em mvp/runtime/app.sqlite3 (pessoal, não publicar). Informações coletadas na versão anterior (MusicBrainz/Wikidata/Ollama, ~185 músicas) continuam no banco e aparecem nos cartões.
- A versão anterior (critérios por playlist, distribuição pelo Ollama, rótulos que não contam, recomeçar/esvaziar playlist) foi removida; está no histórico do Git até o commit 8ed6d01.

## Módulos
- core.py: Store (tracks, cache, spotify_library), record(), import_tracks(items, playlist_items) com liked=False para músicas só em playlist; KEEP_ON_IMPORT preserva informações coletadas; ORIGIN_RANK/infer_origin (gênero faixa > album > artista > ia; idioma faixa > letra > ia); all_genre_labels.
- game.py: perfis de playlist (tabela profiles; chave = id do Spotify ou "new:..." para criadas no app, ligadas por spotify_id), até 8 ativas; escolhas como {'add','remove'} relativas à cópia da última sincronização (tabela decisions) + history para desfazer; queue, card, suggested ("Combina"), overview, apply_published.
- collector.py: thread que roda Enricher.quick (Deezer por ISRC: gênero do álbum, BPM, deezer_id; LRCLIB: idioma pela letra) depois da sincronização; 3 passadas.
- publish.py: prepare (lê o Spotify ao vivo; por playlist add/remove/rename/describe; ação create/update/same/skip) e execute (uma por vez; recusa playlist que mudou desde a prévia; para na primeira falha; nova playlist privada com descrição-marcador para recuperar criação perdida, depois PUT com a descrição do usuário).
- providers.py: Spotify (library com added_at, playlists próprias, playlist_tracks, contents), Enricher (get com espaçamento/retentativas/cache, deezer_album_genres, lyrics_languages, quick, preview), request_json.
- server.py: GET /api/game, /api/game-card, /api/collect-status, /api/preview (fora do LOCK), /auth/start, /callback; POST via métodos post_<nome>: config, logout, sync-start/sync-step, collect-start, profile-update/create/delete, game-decide/skip/undo, publish-preview/publish-execute.
- static/: telas #screen-connect, #screen-playlists, #screen-game, #screen-preview; cartões de playlist do <template id=profile-template>, zonas do <template id=zone-template>; arrastar com pointer events (não HTML5 DnD).
- demo_server.py: `cd mvp; python demo_server.py` → http://127.0.0.1:8799 com dados fictícios, banco temporário e Spotify simulado (DemoSpotify).

## Regras
- Rodar testes: `cd mvp; python -m unittest discover -s tests -v` (67 testes passando). Helpers compartilhados em tests/helpers.py (HTTPTests sobe o servidor com banco temporário e coletor simulado).
- Nunca gravar no Spotify sem prévia e confirmação do usuário; nunca repetir gravações automaticamente. A prévia é de uso único e invalidada por qualquer escolha (Handler.invalidate).
- Remoção no Spotify: DELETE /playlists/{id}/items com {"items":[{"uri":...}]}, até 100 por requisição.
- CSP: além de 'self', só img https://i.scdn.co e media https://*.dzcdn.net.
- Deezer: só uso pessoal/não comercial; não guardar imagens; o link da prévia expira e não é guardado. LRCLIB: a letra nunca é guardada.
- Revisões manuais (campo review, da versão anterior) têm prioridade sobre qualquer fonte.
- Commits e PRs sem atribuição ao Claude: não adicionar "Co-Authored-By: Claude" nem "Generated with Claude Code".
- Usar o Git para histórico (sem pastas de backup). A pesquisa inicial fica em arquivo/pesquisa-inicial/, fora do Git.
- Não versionar mvp/runtime/, mvp/data/ nem arquivo/ (dados pessoais; ver .gitignore).
