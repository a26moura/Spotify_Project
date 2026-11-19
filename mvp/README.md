# Spotify Project — app local

## Iniciar

1. Abra `INICIAR.cmd` nesta pasta (Python 3.10+, sem bibliotecas extras). O navegador abre em **http://127.0.0.1:8765**. Mantenha o terminal aberto.
2. Encerre com Ctrl+C no terminal.

Sem conta: `python demo_server.py` abre **http://127.0.0.1:8799** com músicas fictícias, banco temporário e um Spotify simulado (nada sai do computador, exceto a prévia de áudio de uma música pública do Deezer).

## Conectar o Spotify

Clique em **Conectar Spotify**. A tela explica como criar um aplicativo em https://developer.spotify.com/dashboard e cadastrar o retorno **http://127.0.0.1:8765/callback** (exatamente esse endereço, não `localhost`).

Informe só o **Client ID** (não é segredo; fica em `runtime/config.json`, ou use a variável `SPOTIFY_CLIENT_ID`). Não há Client Secret nem senha no app: o login acontece na página do Spotify, com Authorization Code + PKCE e validação de state. No modo de desenvolvimento, o responsável pelo app precisa de Premium e as contas de teste precisam estar autorizadas no painel.

## O que é lido e o que é gravado

- **Leitura**: curtidas (com a data) e as playlists criadas por você, com o conteúdo. Playlists que você só segue não entram. Músicas que estão só numa playlist sua, sem curtida, também entram no jogo.
- **Gravação** (só na prévia final, depois da confirmação):
  - adicionar e remover músicas das suas playlists, em lotes de até 100;
  - mudar nome e descrição;
  - criar playlists novas, sempre privadas.
- A prévia lê o Spotify na hora. Na gravação, cada playlist é lida de novo e, se mudou desde a prévia, não é alterada e a gravação para ali.
- A prévia é de uso único e deixa de valer com qualquer nova escolha no jogo ou nas playlists.
- Em falha, nada é repetido automaticamente: "Ler de novo" mostra o que ainda falta.
- Uma playlist nova nasce com uma descrição temporária (identificador do app) e logo recebe a sua descrição. Se a resposta da criação se perder, a próxima prévia encontra a playlist por esse identificador em vez de criar outra.
- Curtidas nunca são alteradas.

## Dados e segurança

SQLite em `runtime/app.sqlite3`, separado por ID da conta Spotify: músicas e informações coletadas, cópia das playlists da última sincronização, perfis das playlists e escolhas do jogo (guardadas como "entra"/"sai" em relação ao Spotify, com histórico para desfazer). Tokens OAuth ficam só na memória e somem ao desconectar ou reiniciar.

O servidor escuta só em `127.0.0.1`, valida Host, Origin e token CSRF nas mutações, usa cookies HttpOnly/SameSite=Lax e não registra URLs de callback. A política de conteúdo permite só capas do Spotify (`i.scdn.co`) e áudio do Deezer (`*.dzcdn.net`) além do próprio app.

Esta é uma ferramenta local, **não uma implantação pública**.

## Testes

`python -m unittest discover -s tests -v` nesta pasta. Os testes usam Spotify, Deezer e LRCLIB simulados e banco temporário; não comprovam o acesso real da sua conta à API.

- [Spotify: migração de endpoints de fevereiro de 2026](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [Spotify: PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Spotify: remover itens de playlist](https://developer.spotify.com/documentation/web-api/reference/remove-items-playlist)
