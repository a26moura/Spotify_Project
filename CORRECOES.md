# Log de bugs corrigidos

Cada correção diz o que acontecia, a causa e o que mudou. O commit indicado tem o código da correção (`git show <commit>`). As mais recentes ficam em cima.

## Versão jogo

### 19/11/2026: segundo uso na conta real

| Problema | Causa | Correção |
|---|---|---|
| "Jogar só esta" mostrava as músicas da playlist, mas não dava para mandá-las para outras playlists. | A rodada usava como destino só as playlists marcadas "No jogo", e só a própria playlist estava marcada. O nome "No jogo" sugeria "jogar com as músicas desta playlist". | Na rodada, todas as suas playlists viram destino (até 8), e "No jogo" virou "Destino no jogo". Escolher as músicas virou a primeira etapa do jogo ("Escolher músicas"), com várias opções ao mesmo tempo. |

### 19/11/2026: primeiro uso na conta real (commit `c7c7efc`)

| Problema | Causa | Correção |
|---|---|---|
| A capa do álbum aparecia cortada no cartão. | A área da capa tinha altura fixa e a imagem quadrada era recortada para preencher a largura. | A capa fica quadrada e centralizada, sempre inteira. |
| Algumas músicas apareciam duas vezes no jogo (16 casos, por exemplo "Lonely" do *Trouble* e do *Trouble Deluxe*). | O Spotify tem a mesma gravação (mesmo ISRC) com ids diferentes: single e álbum, edição deluxe, coletânea. O app tratava cada id como uma música. | Músicas com o mesmo ISRC viram um cartão só, com o aviso "2 versões no Spotify". Tirar de uma playlist remove todas as versões; colocar usa a versão curtida. Escolhas já feitas na outra versão continuam valendo. |
| "Dear Friend Across The River" tocava outra música ("What Could Have Been"). | No Deezer, o ISRC dela está cadastrado em outra música do mesmo artista, e o app só conferia o artista. | A música do Deezer só é aceita se o artista **e** o título conferem. Uma combinação errada antiga é apagada (gênero do álbum, BPM e prévia) na próxima coleta, que reconsulta todas as músicas. |
| Algumas músicas ficavam sem prévia de áudio. | A busca no Deezer era só pelo ISRC; se o Deezer não tinha aquele ISRC, não havia outra tentativa. | Sem combinação pelo ISRC, o app busca por título e artista, aceitando até 5 s de diferença na duração. As músicas que o Deezer não tem continuam sem prévia. |

### 19/11/2026: encontrados durante a construção

| Problema | Causa | Correção | Commit |
|---|---|---|---|
| Sincronizar de novo fazia a coleta buscar todas as músicas outra vez. | A reimportação não preservava os campos da coleta rápida (`quick_checked`, id do Deezer, BPM). | Esses campos entram na lista do que a importação preserva. | `e81759c` |
| Se o Spotify recusasse apagar a descrição temporária de uma playlist nova, a gravação travaria naquela playlist em todas as tentativas. | A falha desse ajuste era tratada como falha da playlist inteira. | Vira só um aviso no resultado; as músicas são gravadas normalmente. | `8ed6d01` |
| Depois de gravar, a prévia antiga continuava na tela, sob o texto "Nada foi gravado ainda". O resumo dizia "1 novas". | A tela não era limpa após a gravação, e os totais não tinham singular. | A prévia é limpa após gravar, e os textos usam singular e plural. | `8ed6d01` |
| Descrições com "&" apareciam como "&amp;" e contavam como alteradas. | O Spotify devolve nomes e descrições com entidades HTML. | Nomes e descrições são decodificados antes de comparar e de mostrar. | `8ed6d01` |
| Arrastar o cartão até uma playlist não marcava nada. | O arrastar padrão do navegador (HTML5 drag and drop) não reagia aos movimentos do mouse nos testes. | Arrastar com pointer events: o cartão segue o mouse, marca a playlist onde é solto e volta ao lugar. | `6f780d0` |
| Ctrl+Z voltava a música, mas sem a escolha feita. | Desfazer apagava a escolha em vez de mostrá-la de novo. | O cartão volta com a escolha desfeita marcada, para ajustar. | `6f780d0` |
| O botão "Próxima" ficava fora da tela. | A capa ocupava toda a largura do cartão, deixando-o alto demais. | A altura da capa é limitada ao tamanho da tela. | `6f780d0` |
| Os campos Idioma e Gênero transbordavam do cartão da playlist. | Os campos lado a lado não podiam encolher. | Os dois campos dividem a largura e encolhem. | `9371c54` |
| O erro de nome de playlist repetido aparecia atrás da janela de criação. | O aviso só era mostrado no topo da página. | Com uma janela aberta, o erro aparece dentro dela. | `9371c54` |
| O servidor de demonstração tinha no código o caminho completo da pasta do usuário. | Caminho absoluto copiado do arquivo de rascunho. | Caminho relativo ao próprio arquivo (corrigido antes de ir para o GitHub). | `7e79387` |
| Alguns testes rodavam duas vezes, e a contagem de testes ficava inflada. | Classes de teste herdavam de outras para reaproveitar a preparação e herdavam junto os testes delas. | As classes copiam só a preparação e os auxiliares. | `c7c7efc` |

## Versão anterior (classificação automática, removida em 19/11/2026)

| Data | Problema | Correção | Commit |
|---|---|---|---|
| 19/11 | O gênero amplo do álbum no Deezer ("Rap/Hip Hop") escondia o "reggaeton" ou "trap" do artista nos critérios das playlists. | Os critérios passaram a olhar os rótulos de gênero de todas as fontes. | `2e0bd94` |
| 17/11 | O Ollama colocava em playlists músicas sem gênero nem idioma, adivinhando pelo nome do artista. | Músicas sem dados não iam para o modelo, e um "sim" exigia o dado pedido pela playlist. | `55fe852` |
| 17/11 | "Funk" vindo das fontes (funk americano) caía na playlist de funk brasileiro. | "Funk" das fontes passou a ser funk internacional. | `55fe852` |
| 17/11 | Reimportar as curtidas fazia consultar Deezer e LRCLIB de novo. | A reimportação passou a preservar a marca de consulta. | `55fe852` |
| 15/11 | Um erro temporário (HTTP 503) do MusicBrainz interrompia a consulta de gêneros. | Até três tentativas com espera crescente, respeito ao Retry-After e pausa da fonte; gravações no Spotify nunca são repetidas. | `55fe852` |
