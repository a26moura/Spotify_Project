# Fluxo de organização

1. Ao conectar o Spotify, o aplicativo sincroniza curtidas, playlists e conteúdo acessível das playlists. Classificações e revisões locais da mesma conta são preservadas. A sincronização pode ser repetida em Ferramentas avançadas → Sincronizar conta e playlists.
2. Na etapa 3, em Playlists do Spotify, consulte as músicas existentes e use uma playlist própria na organização. Defina seus critérios. Também é possível criar critérios para uma playlist nova. O nome de uma playlist não é considerado evidência de gênero.
3. **1. Classificar músicas** atualiza a leitura da conta e consulta MusicBrainz e Wikidata para músicas pendentes, reutilizando resultados salvos. Faixas sem gênero e sem idioma podem ser tentadas novamente. Restrições e indisponibilidade dos serviços ainda podem causar espera. Ollama continua disponível como alternativa local em Ferramentas avançadas.
4. O aplicativo calcula a distribuição das curtidas, abre a escolha dos destinos e mostra a prévia. Uma playlist existente com nome único igual ao critério é sugerida; vínculos já salvos têm prioridade. Confira os destinos antes de confirmar.
5. Somente após confirmação cria playlists privadas e adiciona músicas ausentes nas existentes. A organização não remove faixas. Ao terminar, atualiza a leitura da biblioteca. Falhas de gravação exigem nova prévia para evitar repetição cega.

Para recomeçar uma playlist, use etapa 2 → Recomeçar uma playlist. Há duas opções, que podem ser usadas juntas. **Só no app** apaga as decisões do Ollama para aquela playlist (critérios explícitos e revisões manuais continuam valendo); na próxima distribuição o Ollama reavalia as músicas apenas para ela, mantendo as decisões das outras. Nada muda no Spotify. **Esvaziar no Spotify** vale para playlists já vinculadas: o aplicativo mostra a prévia com as músicas atuais e só remove todas após confirmação. Se a playlist mudou no Spotify depois da prévia, nada é removido e é preciso preparar outra prévia. A playlist continua existindo; curtidas, classificações e revisões locais não mudam. Depois, "2. Organizar nas playlists" a preenche de novo.

Tela: no topo ficam as três etapas (Classificar músicas, Organizar nas playlists, Salvar no Spotify), cada uma com seu botão principal; abaixo, as playlists (clique para filtrar), a lista de músicas e, ao final, Ferramentas avançadas com as etapas em partes, o modelo Ollama e o teste de 30 músicas.

Playlists seguidas aparecem na lista, mas seu conteúdo pode não estar disponível pela API. Somente playlists pertencentes à conta podem ser usadas como destino nesta versão. As músicas de playlists que não estão nas curtidas são mostradas no inventário, preservadas no Spotify e não redistribuídas.

As playlists selecionadas para organização usam os critérios já suportados pelo aplicativo, até 30. O inventário pode exibir mais playlists. Não há músicas ou playlists de teste carregadas automaticamente.

Validação: testes automatizados com respostas simuladas e fluxo completo na interface usando conta simulada. Não houve gravação no Spotify real durante a implementação.
