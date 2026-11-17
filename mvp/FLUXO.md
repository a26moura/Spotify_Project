# Fluxo de organização

1. Ao conectar o Spotify, o aplicativo sincroniza curtidas, playlists e conteúdo acessível das playlists. Classificações e revisões locais da mesma conta são preservadas. A sincronização pode ser repetida em Ferramentas → Sincronizar conta e playlists.
2. Em Ver playlists do Spotify, consulte as músicas existentes e use uma playlist própria na organização. Defina seus critérios. Também é possível criar critérios para uma playlist nova. O nome de uma playlist não é considerado evidência de gênero.
3. **1. Classificar músicas** atualiza a leitura da conta e consulta MusicBrainz e Wikidata para músicas pendentes, reutilizando resultados salvos. Faixas sem gênero e sem idioma podem ser tentadas novamente. Restrições e indisponibilidade dos serviços ainda podem causar espera. Ollama continua disponível como alternativa local em Ferramentas.
4. O aplicativo calcula a distribuição das curtidas, abre a escolha dos destinos e mostra a prévia. Uma playlist existente com nome único igual ao critério é sugerida; vínculos já salvos têm prioridade. Confira os destinos antes de confirmar.
5. Somente após confirmação cria playlists privadas e adiciona músicas ausentes nas existentes. Não remove faixas. Ao terminar, atualiza a leitura da biblioteca. Falhas de gravação exigem nova prévia para evitar repetição cega.

Playlists seguidas aparecem na lista, mas seu conteúdo pode não estar disponível pela API. Somente playlists pertencentes à conta podem ser usadas como destino nesta versão. As músicas de playlists que não estão nas curtidas são mostradas no inventário, preservadas no Spotify e não redistribuídas.

As playlists selecionadas para organização usam os critérios já suportados pelo aplicativo, até 30. O inventário pode exibir mais playlists. Não há músicas ou playlists de teste carregadas automaticamente.

Validação: testes automatizados com respostas simuladas e fluxo completo na interface usando conta simulada. Não houve gravação no Spotify real durante a implementação.
