# Coleta de rótulos e distribuição independente

O botão **1. Classificar músicas** sincroniza a conta, busca os rótulos nos sites e completa o que faltar com o Ollama. O botão **2. Organizar nas playlists** usa o Ollama para decidir a participação em cada playlist. A gravação no Spotify continua exigindo a prévia e sua confirmação.

Também é possível executar separadamente em Ferramentas:

1. **Buscar rótulos nos sites**: consulta MusicBrainz e Wikidata mesmo sem playlists definidas. Guarda todos os nomes de gêneros e tags retornados para a gravação identificada, sem reduzi-los a uma categoria única. Tags ficam identificadas como tags; não são automaticamente gêneros. Não une resultados de gravações diferentes ou ambíguas.
2. **Distribuir nas playlists com Ollama**: lê as informações da música e o nome, descrição e critérios de cada playlist. Salva uma decisão por playlist (pertence, não pertence ou informação insuficiente), com justificativa. Uma música pode pertencer a várias playlists.

As decisões ficam separadas dos rótulos. Em Editar, consulte os rótulos originais e as justificativas. Se mudar os rótulos ou critérios, as decisões antigas deixam de definir destinos até nova distribuição. Revisões manuais e exclusões têm prioridade. Reimportar as curtidas preserva os rótulos, revisões e decisões válidas.

**Parar classificação** aparece no painel de progresso durante coleta e distribuição. Aguarda terminar a música em andamento, salva o resultado já obtido e não inicia a próxima música nem a próxima etapa. Não cancela instantaneamente uma requisição que o serviço já esteja processando. A retomada usa o progresso salvo.

Fontes podem não reconhecer uma gravação ou não fornecer rótulos. O modelo local pode sinalizar falta de informação; ele não analisa áudio. Não há promessa de classificar todas as faixas.

Validação: suíte automatizada, interface com serviços simulados e teste de distribuição real no modelo local ministral-3:8b com dados fictícios. Nenhuma gravação no Spotify real foi feita durante esta implementação.

## Cadeia de classificação (16/11/2026)

Gênero e idioma de cada música são preenchidos em ordem de confiança. Cada campo guarda sua origem:

1. **Pela faixa**: gêneros e idiomas documentados para a gravação/obra no MusicBrainz e Wikidata.
2. **Pelo artista**: quando a faixa não tem gênero documentado, usa até 4 gêneros do artista principal no MusicBrainz (ou Wikidata do artista). O artista só é aceito quando todas as gravações compatíveis apontam para o mesmo artista, ou quando a busca encontra um único artista com nome exato. Nomes ambíguos ficam sem gênero. Idioma nunca é deduzido pelo artista.
3. **Sugestão de IA**: com um modelo Ollama selecionado, completa somente o campo que continua vazio (gênero e/ou idioma). Cada música é enviada uma vez por modelo. Resposta inválida não interrompe as demais.

Uma origem mais forte substitui uma mais fraca; uma mais fraca nunca substitui uma mais forte. Revisões manuais continuam prioritárias.

O botão 1. Classificar músicas executa 1 → 2 → 3; a distribuição fica no botão 2. Organizar nas playlists. Se o MusicBrainz recusar consultas, o app faz até oito pausas automáticas (no máximo 5 minutos cada) antes de parar; clicar de novo continua de onde parou. Em Ferramentas: **1. Buscar rótulos nos sites** (faixa + artista) e **1b. Completar gênero/idioma com Ollama**. Faixas já consultadas antes desta versão e sem gênero são consultadas de novo para tentar o artista (as respostas anteriores vêm do cache).

Na biblioteca, o filtro de origem mostra: gênero pela faixa, pelo artista, por IA, idioma por IA, sem gênero, sem idioma e revisadas por você. Gêneros pelo artista e por IA aparecem com uma etiqueta na coluna Gênero / Idioma.

Validação: 86 testes automatizados (9 novos em tests/test_origins.py) e interface verificada com dados simulados. A consulta real ao MusicBrainz não pôde ser executada no ambiente de desenvolvimento; a cobertura real será conhecida na primeira execução.

## Fontes complementares: Deezer e LRCLIB (16/11/2026)

A cadeia passou a ter mais dois passos, sem chave de API:

- **Gênero pelo álbum (Deezer)**: quando a faixa não tem gênero documentado, o app procura a gravação pelo ISRC (`/track/isrc:…`) e lê os gêneros do álbum. Só aceita se o artista principal do Spotify estiver entre os artistas creditados no Deezer. Gêneros regionais amplos (Latin Music, Brazilian Music, World Music, Films/Games etc.) ficam como rótulos, mas não contam como gênero; nesse caso, o passo pelo artista continua. Origem: `album`.
- **Idioma pela letra (LRCLIB)**: quando não há idioma documentado, o app busca a letra pelo título, artista e duração e detecta o idioma localmente (`lyrics_language.py`), por palavras frequentes exclusivas de cada língua (português, espanhol, inglês, francês, italiano, alemão) e pela escrita (japonês, coreano, chinês, russo, árabe, hindi). Sem IA. Letras curtas ou mistas demais ficam sem idioma; até dois idiomas são aceitos (ex.: inglês + espanhol). Faixas marcadas como instrumentais recebem "Instrumental". Origem: `letra`.

Ordem de confiança por campo:

- Gênero: faixa > álbum > artista > IA.
- Idioma: faixa > letra > IA.

Privacidade e termos: a letra não é guardada; o cache guarda só o idioma detectado (30 dias). Do Deezer, guarda só o ID, título e gêneros do álbum (sem imagens). Os termos do Deezer permitem a API gratuita apenas para uso pessoal, privado e não comercial; um site público ou comercial exigiria acordo com o Deezer. O LRCLIB não declara licença para as letras; por isso o app só lê e descarta. Espaçamento entre consultas: Deezer 0,25 s, LRCLIB 0,7 s, MusicBrainz/Wikidata 1,1 s (por serviço).

Falhas temporárias do Deezer ou do LRCLIB não interrompem a classificação: a música fica consultada, mas sem a marca `complements_checked`, e será tentada de novo no próximo "1. Classificar músicas". Músicas consultadas antes desta versão que ainda não têm gênero de faixa/álbum ou idioma de faixa/letra também voltam a ser consultadas uma vez (o MusicBrainz responde do cache quando possível).

Filtros novos na biblioteca: "Gênero pelo álbum (Deezer)" e "Idioma pela letra (LRCLIB)".

Validação: 99 testes automatizados (13 novos em tests/test_complements.py, todos com respostas simuladas) e uma consulta real às duas APIs com uma música pública conhecida, sem dados da conta. A cobertura real na sua biblioteca será conhecida na próxima execução.

## Distribuição com evidência (17/11/2026)

Correções após a primeira execução real, em que o Ollama colocou músicas sem nenhum dado em playlists, adivinhando pelo nome do artista (ex.: "Clint Eastwood" em Funk por causa de "Del The Funky Homosapien"):

- **Sem dados, sem IA**: músicas sem gênero e sem idioma não são enviadas ao Ollama na etapa 2 e não recebem destino do modelo. Primeiro termine a etapa 1.
- **Evidência por critério**: um "sim" do modelo só vale para uma playlist com critério de gênero se a música tiver gênero; com critério de idioma, se tiver idioma.
- **Seus critérios sempre valem**: se a música atende aos critérios explícitos da playlist, ela entra, mesmo que o modelo diga não ou que a decisão esteja desatualizada.
- **Funk brasileiro**: o rótulo "funk" sozinho vindo de MusicBrainz, Deezer ou Wikidata é tratado como "Funk Internacional" e não atende ao critério Funk. "funk carioca", "baile funk", "brazilian funk", sua revisão e a sugestão de IA ("Funk", separada de "Funk Internacional") continuam valendo. As instruções do modelo explicam isso e dizem que nomes não são evidência de gênero.
- **Decisões antigas refeitas**: a versão das decisões (`ROUTING_VERSION` em core.py) mudou, então o botão 2 refaz a distribuição das músicas que têm dados. Até lá, só valem os critérios explícitos.
- **Bug corrigido**: a marca `complements_checked` agora é preservada ao sincronizar, e as músicas não voltam todas para a fila a cada clique.

## Rótulos que não contam (17/11/2026)

Cada playlist tem o campo **Rótulos que não contam**. Se a música tiver um desses gêneros, ela fica fora da playlist, mesmo que atenda aos demais critérios, e um "sim" do Ollama também é descartado.

- Considera os gêneros da música e os rótulos de gênero de todas as fontes (faixa, álbum e artista), inclusive os de origem mais fraca, como "Latin Music" do álbum. Tags livres do MusicBrainz não contam.
- Com revisão manual, valem só os gêneros que você escreveu.
- A comparação ignora acentos e maiúsculas e usa as categorias amplas (ex.: excluir "Rock" exclui "alternative rock").
- O "funk" sozinho das fontes aparece como "funk internacional"; em Funk, use `funk internacional` para deixar isso explícito.
- Use os nomes como as fontes escrevem (Editar → Informações das fontes). Quando as fontes não diferenciam, a exclusão não ajuda: 21 Savage e Matuê aparecem os dois como `hip hop`, `trap`. Nesse caso, combine com o idioma (ex.: Trap + Português).
- O campo só é salvo quando preenchido, então playlists sem exclusões mantêm as decisões já tomadas pelo Ollama.

## Modelo recomendado: qwen3.5:9b (18/11/2026)

Teste com 30 músicas da biblioteca cujo gênero e idioma vieram das fontes (gabarito), usando o mesmo prompt do app, numa RTX 5060 Laptop (8 GB):

| Modelo | Respondeu gênero | Acertou gênero | Acertou idioma | Tempo/música |
|---|---|---|---|---|
| ministral-3:8b | 1/30 | 1 | 0 | 3,0 s |
| ministral-3:3b | 2/30 | 2 | 0 | 2,7 s |
| qwen3.5:4b | 30/30 | 17 | 18/25 | 3,5 s |
| qwen3.5:9b | 28/30 | 20 | 25/28 | 1,9 s |

- Os modelos ministral marcam "incerto" em quase tudo com este prompt; na prática não completam nada.
- O qwen3.5:9b cabe inteiro na GPU (5,6 GB) e é o modelo padrão desde 18/11.
- Modelos com raciocínio (qwen3.5) precisam de `think: false`: sem isso, o raciocínio consome o limite de resposta e toda classificação é rejeitada. O app agora envia `think: false` nas duas chamadas (classificar e distribuir); modelos sem raciocínio ignoram o parâmetro.
- Erros típicos do 9b: rap brasileiro rotulado como Pop ou Funk (ex.: Orochi), trilha sonora como Trap. Por isso a IA continua só preenchendo campos vazios; revise as sugestões com o filtro "Gênero por IA".

## Critérios de gênero usam os rótulos de todas as fontes (19/11/2026)

O gênero do álbum no Deezer é amplo ("Rap/Hip Hop", "Pop") e, por ser uma origem mais forte, substituía o gênero do artista ("reggaeton", "trap") como gênero principal. Por isso, músicas como LA GRACIOSA (Quevedo) e Me Rehúso (Danny Ocean) não entravam em Reggaeton.

Agora o critério de gênero de uma playlist considera o gênero principal e também os rótulos de gênero de todas as fontes (faixa, álbum e artista), os mesmos usados em "Rótulos que não contam". Tags livres do MusicBrainz continuam fora. Com revisão manual, valem só os seus gêneros. O "funk" sozinho das fontes continua sendo funk internacional.

Efeito na biblioteca real (simulação, sem gravar): Reggaeton 4 → 8, Trap - Br 2 → 5 (Matuê, WIU) e Rock 38 → 42. As demais playlists não mudaram.

Limite: músicas sem nenhum rótulo de reggaeton nas fontes (ex.: faixas do Bad Bunny marcadas só como "latin", "bomba" ou "electronic") dependem do Ollama na etapa 2 ou de revisão manual.

## Gênero do artista sempre coletado como rótulo (19/11/2026)

Antes, o artista só era consultado quando a faixa e o álbum não tinham gênero. Assim, faixas do Bad Bunny com "bomba" ou "latin" nunca recebiam o "reggaeton" que o Wikidata lista para o artista.

- Agora o passo 1 sempre busca os gêneros do artista principal (MusicBrainz e também Wikidata) e os guarda como rótulos `artist-genre`. O gênero principal só vem do artista quando nada mais foi encontrado; a ordem de confiança não muda.
- A identidade do artista continua conservadora (mesmo critério de antes); nomes ambíguos ficam sem rótulo.
- O gênero do artista vale para todas as músicas dele. Para evitar exageros, um rótulo complementar só conta pela categoria ampla quando ela é única: "alternative rock" conta como Rock, mas "pop rock" (Rock e Pop) não conta como nenhuma das duas. O nome exato sempre conta. Use revisão manual ou "Rótulos que não contam" para exceções.
- Músicas já classificadas voltam uma vez para a fila do botão 1 (marca `artist_labels`). As respostas do artista ficam no cache, então cada artista é consultado uma vez.

Teste real (banco temporário, sem gravar): PIToRRO DE COCO e LA CANCIÓN (Bad Bunny, J Balvin) e Criminal (Natti Natasha) passaram a atender Reggaeton.
