# Fluxo do jogo

1. **Conectar.** Depois do login, o app sincroniza: lê as curtidas e, uma por vez, as playlists criadas por você. Informações já coletadas e escolhas do jogo são preservadas. Ao terminar, começa a coleta em segundo plano (Deezer e LRCLIB), na ordem em que as músicas vão aparecer no jogo. "Sincronizar de novo" repete a leitura.

2. **Playlists.** Cada playlist sua vira um cartão:
   - nome e descrição (até 300 caracteres), que vão para o Spotify só na prévia final;
   - idioma e gênero ou clima, opcionais, com sugestões tiradas da sua biblioteca;
   - **Destino no jogo**, até 8 playlists: os lugares para onde você arrasta as músicas.

   Cada mudança é salva no app ao sair do campo. Se você não editou o nome ou a descrição e eles mudaram no Spotify, o app segue o Spotify; o que você editou é mantido. "+ Nova playlist" cria uma playlist só no app, que pode ser apagada enquanto não for gravada. Uma playlist apagada no Spotify aparece como "Não existe mais" e sai do jogo.

3. **Escolher músicas.** "Escolher músicas →" abre a primeira etapa do jogo: de onde vêm as músicas da rodada. Dá para marcar mais de uma opção:
   - **Ainda não jogadas**: as que você nunca classificou (e as puladas);
   - **Sem playlist**: as que não estão em nenhuma playlist;
   - **Todas as músicas**: a biblioteca inteira, de novo;
   - **as músicas de uma ou mais playlists**, para reclassificá-las.

   As músicas da rodada ficam fixas quando ela começa (tirar uma música de uma playlist não a tira da rodada) e aparecem mesmo se você já as tiver classificado. Na rodada, todas as suas playlists viram destino (se forem até 8; se forem mais, as playlists escolhidas são somadas às que já são destino). "Trocar músicas" volta para esta etapa.

4. **Jogo.**
   - **O cartão:** capa, título, artistas, álbum e ano, gênero e idioma com a origem, outros rótulos das fontes, duração, BPM, explícita, data da curtida ou "Só em playlist".
   - **O áudio:** a prévia de 30 s toca sozinha; a opção pode ser desligada e o volume é lembrado.
   - **Marcar playlists:** arraste o cartão até uma playlist ou aperte 1–8, e clique de novo para desmarcar.
   - **Estados de cada playlist:**
     - **Entra**: você marcou e ela ainda não tem a música;
     - **Já está**: estava na playlist e continua;
     - **Vai sair**: estava e você desmarcou;
     - **Combina**: o idioma ou o gênero da playlist bate com a música.
   - **Teclas:** **Enter** salva e passa para a próxima, **S** pula (a música volta no fim da fila), **Espaço** toca ou pausa, **L** muda o coração, **Ctrl+Z** desfaz e mostra de novo a escolha desfeita.
   - **Coração (♥ Like):** vermelho quando a música está nas curtidas ou vai entrar; cinza quando não está ou vai sair. A mudança só vai para o Spotify na gravação, depois das playlists.
   - **Músicas repetidas:** a mesma gravação (mesmo ISRC) com dois ids no Spotify aparece uma vez, com "2 versões no Spotify". Ao tirar a música de uma playlist, todas as versões saem; ao colocar, entra a versão do cartão (a curtida, se houver).
   - **Ordem e andamento:** as músicas com informação aparecem primeiro, agrupadas por idioma, gênero e artista; as que ainda estão sendo consultadas vêm depois. O andamento fica salvo para continuar depois.

5. **Prévia.** Lida do Spotify na hora. Por playlist: o que entra (+), o que sai (−), quantas músicas tinha e quantas vai ter, nome e descrição que mudam, playlists novas (criadas privadas; uma nova sem músicas não é criada). Um cartão "Músicas curtidas" lista as que entram (♥) e as que saem (♡) das curtidas e avisa quais das que saem não ficam em nenhuma playlist. "Gravar no Spotify" mostra um resumo e pede confirmação; remoções não têm desfazer automático.

6. **Gravação.** Uma playlist por vez: cria (se for nova), ajusta nome e descrição, adiciona e remove em lotes de até 100. Por último, se todas as playlists deram certo, muda as curtidas: primeiro as que entram, depois as que saem. Se uma playlist mudou no Spotify desde a prévia, ela não é alterada e a gravação para ali. O resultado mostra cada playlist com link para o Spotify. Depois de gravar, "Ler de novo" deve mostrar "Nada para gravar".

As escolhas valem só para as playlists ativas no momento da jogada; as outras mantêm o que foi decidido antes. Músicas que você não tocou ficam como estão no Spotify.
