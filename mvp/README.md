# Spotify Project — MVP local

Aplicativo local para importar curtidas, consultar gêneros e idiomas, editar destinos e confirmar adições às playlists do Spotify. A interface já inclui a amostra pessoal de 40 músicas e as oito playlists escolhidas.

## Iniciar

1. Abra `INICIAR.cmd` nesta pasta. Requer Python 3.10 ou superior, sem instalação de bibliotecas adicionais. O iniciador tenta primeiro o Python já disponível neste computador.
2. Abra **http://127.0.0.1:8765** no navegador. Mantenha o terminal em execução.
3. Teste a amostra local. “Opções do piloto” permite carregar a exportação de 336 músicas. Dados da exportação não são uma leitura atual da conta.
4. Encerre com Ctrl+C no terminal.

## Conectar o Spotify

Clique em **Conectar Spotify**. A tela explica como criar um aplicativo em https://developer.spotify.com/dashboard e configurar o retorno **http://127.0.0.1:8765/callback**. Use exatamente esse endereço, não `localhost`.

Informe somente o **Client ID**. Não é necessário Client Secret. O Client ID informado na tela vale pela execução atual; alternativamente, configure a variável de ambiente `SPOTIFY_CLIENT_ID` antes de iniciar. A senha é informada somente na página oficial do Spotify. O fluxo utiliza Authorization Code com PKCE e validação de state.

O responsável pelo app precisa de Spotify Premium no modo de desenvolvimento. Contas de teste precisam estar autorizadas no painel. A disponibilidade de cadastro e a aprovação de acesso público são controladas pelo Spotify.

Após conectar:

1. Clique em **Importar curtidas**. Todas as páginas da biblioteca são lidas antes de atualizar o banco.
2. Para sua conta pessoal, em **Opções do piloto**, use **Aplicar minha revisão de 40 faixas**. Essa operação é explícita, por ID, e preserva revisões já salvas. Não aplicar a outras pessoas.
3. Use **Consultar gêneros e idiomas**. Cada faixa é consultada e salva separadamente. Pode parar e continuar depois. Resultados ambíguos permanecem sem classificação.
4. Edite gêneros, idiomas, destinos e exclusões. São campos independentes. Músicas sem gênero também aceitam destinos manuais.
5. Clique em **Revisar atualização**. Escolha criar playlists privadas ou atualizar playlists que pertencem à conta.
6. Confira cada música na prévia, marque a autorização e confirme. A prévia expira em 10 minutos e é invalidada por mudanças de biblioteca/revisão/configuração.

## Comportamento de atualização

- Apenas adiciona faixas ausentes. Não remove músicas de playlists nem desfaz curtidas.
- Deduplica por URI/ID Spotify, considerando `linked_from` quando fornecido. Versões diferentes com IDs diferentes continuam sendo músicas diferentes.
- Consulta o conteúdo atual antes da prévia e novamente antes de adicionar. Envia lotes de até 100 URIs.
- Guarda os IDs das playlists gerenciadas, sem escolher automaticamente playlists de terceiros pelo nome.
- Em falha de rede, não repete uma gravação cegamente. Uma nova prévia reconcilia o conteúdo. Uma descrição identificadora auxilia a recuperação de uma criação cuja resposta foi perdida.
- Não garante exclusão de concorrência com aplicativos externos alterando a mesma playlist simultaneamente. Dentro deste processo, as operações são serializadas.
- Uma playlist sem músicas e sem destino existente não é criada vazia.
- Correções e exclusões permanecem salvas quando uma faixa deixa de ser curtida e depois retorna.

## Dados e separação de contas

SQLite em `runtime/app.sqlite3` armazena biblioteca, revisões, nomes e destinos separados por ID da conta Spotify. A amostra usa um perfil local separado. Tokens OAuth ficam somente na memória e são descartados ao desconectar, expirar a sessão ou reiniciar o processo. A desconexão não apaga a revisão local nem revoga a autorização do app na conta Spotify.

O servidor escuta exclusivamente em `127.0.0.1`. Valida Host, Origin e token CSRF nas mutações. Cookies são HttpOnly e SameSite=Lax. URLs de callback com códigos OAuth não são registradas em logs. Nenhuma senha ou Client Secret é armazenado.

Esta é uma base para evolução multiusuário, **não uma implantação pública pronta**. Antes de hospedar: separar a amostra pessoal da distribuição, HTTPS, sessão e armazenamento de tokens protegidos apropriados ao ambiente, limites por usuário, filas, política de exclusão de dados, revisão de licenças e acesso aprovado pelo Spotify. Não expor este servidor local na internet.

## Fontes e limites

MusicBrainz é consultado por ISRC quando disponível, ou título e artista. Apenas um candidato com título e artista compatíveis permite enriquecimento. Ambiguidade permanece explícita. Gêneros da gravação e idiomas das obras são apresentados como sugestões. Wikidata é consultado quando há vínculo direto no registro MusicBrainz. Cache de sete dias e espaçamento mínimo de 1,1 segundo entre consultas sem cache. Para uso continuado, configure `MUSICBRAINZ_USER_AGENT` com identificação e contato do aplicativo.

As 40 faixas reutilizam a pesquisa já realizada, preservando a proveniência. As sugestões não substituem escolhas humanas. Não há IA, classificação por áudio ou inferência de idioma a partir do título. As tags do MusicBrainz usadas neste piloto são CC BY-NC-SA 3.0; dados estruturados Wikidata são CC0. A abertura comercial depende de avaliação própria.

- [Spotify: migração de endpoints de fevereiro de 2026](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [Spotify: PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Spotify: endereços de retorno](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri)
- [MusicBrainz: licença](https://musicbrainz.org/doc/About/Data_License)
- [Wikidata: licença](https://www.wikidata.org/wiki/Wikidata:Copyright)

## Estrutura e testes

- `core.py`: regras, banco por conta e preservação de revisões.
- `providers.py`: Spotify, enriquecimento, prévia e gravação.
- `server.py`: servidor local, sessões e OAuth.
- `static/`: interface editável.
- `tests/test_mvp.py`: testes de importação, isolamento, exclusão, deduplicação, falhas parciais, confirmação e segurança das requisições.

Execute `python -m unittest discover -s tests -v` nesta pasta. Os testes usam Spotify simulado e banco temporário. Testes aprovados não comprovam acesso real da conta à API: login e gravação reais dependem do cadastro do aplicativo e da confirmação do usuário.
