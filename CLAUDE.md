# Spotify Project — contexto para o Claude Code

Responda em português. Leia README.md, mvp/README.md, mvp/CLASSIFICACAO.md e mvp/FLUXO.md antes de mudanças grandes.

## O que é
App local (Python 3, só biblioteca padrão, servidor em mvp/server.py, interface em mvp/static/) que importa curtidas e playlists do Spotify, classifica gênero e idioma, distribui as músicas em playlists com ajuda do Ollama local e grava no Spotify só depois de prévia e confirmação.

## Estado atual (16/11/2026)
- Conta Spotify real conectada (351 curtidas, 7 playlists). Dados em mvp/runtime/app.sqlite3 (pessoal, não publicar).
- Ollama: modelo ministral-3:8b (mvp/runtime/metadata.json).
- Classificação em cadeia, com origem salva por campo (genre_origin / language_origin). Gênero: faixa (MusicBrainz/Wikidata) > album (Deezer por ISRC) > artista (identidade confirmada) > ia. Idioma: faixa > letra (LRCLIB + lyrics_language.py, sem IA) > ia. Ollama só preenche campo vazio. Lógica em providers.py (Enricher), classification.py (merge_metadata) e core.py (infer_origin, ORIGIN_RANK, needs_complements).
- Filtro por origem na biblioteca (static/app.js: originMatches/originSelector).
- Dois botões: "1. Classificar músicas" (sync + fontes + Ollama) e "2. Organizar nas playlists" (distribuição Ollama + prévia).
- Última execução: 118 de 351 consultadas; 88 com gênero (47 faixa, 41 artista); idioma fraco (49). Parou porque o MusicBrainz recusou consultas (limite ~1 req/s por IP). Agora há até 8 pausas automáticas de até 5 min.

## Fontes complementares (implementado 16/11/2026, ainda não rodado na conta real)
- Deezer: gênero do álbum por ISRC. Termos: só uso pessoal/privado/não comercial; não guardar imagens. Público/comercial exige acordo.
- LRCLIB: idioma detectado localmente na letra; a letra nunca é guardada (licença não declarada).
- Testes com Enricher que simulam só o MusicBrainz usam Enricher(store, complements=False) para não chamar a rede.
- Primeira execução real (16/11): 185 de 351 consultadas; gênero 157 (66 faixa, 74 álbum, 17 artista); idioma 177 (72 faixa, 105 letra).

## Correções de 17/11/2026
- O Ollama não distribui músicas sem gênero/idioma; um "sim" exige dados para o critério da playlist; critérios explícitos sempre valem (core.py: has_evidence, needs_routing, model_may_say_yes, suggest).
- "funk" sozinho vindo das fontes = Funk Internacional (core.matches_rule). ROUTING_VERSION=2 invalida decisões antigas.
- Reimportação preserva complements_checked.
- Próximos passos sugeridos: terminar a etapa 1 (166 pendentes); playlists para Rock/Pop/Inglês (130 músicas com dados sem destino); modo rápido (Deezer/LRCLIB antes do MusicBrainz); filtro "decisões da IA para conferir".

## Regras
- Rodar testes: `cd mvp; python -m unittest discover -s tests -v` (104 testes passando).
- Nunca gravar no Spotify sem prévia e confirmação do usuário; nunca repetir gravações automaticamente.
- Revisões manuais têm prioridade sobre qualquer fonte.
- Usar o Git para histórico (sem pastas de backup). A pesquisa inicial (validação das 40 faixas, exportação, scripts) fica em arquivo/pesquisa-inicial/, fora do Git.
- Não versionar mvp/runtime/, mvp/data/ nem arquivo/ (dados pessoais; ver .gitignore).
