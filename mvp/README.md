# Spotify Project — app local e site

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
  - criar playlists novas, sempre privadas;
  - colocar nas curtidas ou tirar delas as músicas cujo coração você mudou no jogo (`PUT` e `DELETE /me/library`, até 40 por requisição), só depois que todas as playlists foram gravadas. Isso pede a permissão `user-library-modify`: quem conectou antes de 19/11/2026 precisa desconectar e conectar de novo.
- A prévia lê o Spotify na hora. Na gravação, cada playlist é lida de novo e, se mudou desde a prévia, não é alterada e a gravação para ali.
- A prévia é de uso único e deixa de valer com qualquer nova escolha no jogo ou nas playlists.
- Em falha, nada é repetido automaticamente: "Ler de novo" mostra o que ainda falta.
- Uma playlist nova nasce com uma descrição temporária (identificador do app) e logo recebe a sua descrição. Se a resposta da criação se perder, a próxima prévia encontra a playlist por esse identificador em vez de criar outra.
- Curtidas só mudam quando você muda o coração no jogo e confirma na prévia. Uma música tirada das curtidas que não está em nenhuma playlist some do app na próxima sincronização (a prévia avisa).

## Dados e segurança

SQLite em `runtime/app.sqlite3`, separado por ID da conta Spotify: músicas e informações coletadas, cópia das playlists da última sincronização, perfis das playlists e escolhas do jogo (guardadas como "entra"/"sai" em relação ao Spotify, com histórico para desfazer). Tokens OAuth ficam só na memória e somem ao desconectar ou reiniciar.

Sem `PUBLIC_URL`, o servidor escuta só em `127.0.0.1`. Em qualquer modo, valida Host, Origin e token CSRF nas mutações, usa cookies HttpOnly/SameSite=Lax (com `Secure` em HTTPS) e não registra URLs de callback. A política de conteúdo permite só capas do Spotify (`i.scdn.co`) e áudio do Deezer (`*.dzcdn.net`) além do próprio app.

## Rodar como site

O mesmo `server.py` vira site quando a variável `PUBLIC_URL` existe. Nesse modo ele escuta em `0.0.0.0`, aceita só pedidos para o endereço de `PUBLIC_URL`, lê o Client ID só de `SPOTIFY_CLIENT_ID` (a tela de configurar fica desligada) e recusa qualquer mudança de quem não conectou o Spotify.

| Variável | Valor |
|---|---|
| `PUBLIC_URL` | Endereço do site, sem caminho nem barra final: `https://spotify-project.onrender.com` |
| `SPOTIFY_CLIENT_ID` | Client ID do app no Spotify for Developers |
| `SPOTIFY_PROJECT_DB` | Banco num **disco persistente** (ex.: `/var/data/app.sqlite3`); sem ele, o progresso some a cada publicação |
| `PORT` | Normalmente definida pela hospedagem |

Passos no Render (o `render.yaml` na raiz já descreve o serviço):

1. Envie a branch para o GitHub e, no Render, crie um **Blueprint** a partir do repositório.
2. Preencha `PUBLIC_URL` com o endereço que o Render der ao serviço e `SPOTIFY_CLIENT_ID`.
3. No painel do Spotify, adicione o endereço de retorno `PUBLIC_URL` + `/callback` (ex.: `https://spotify-project.onrender.com/callback`). O endereço local pode continuar cadastrado.
4. No modo de desenvolvimento do Spotify, só as contas cadastradas em **User Management** conseguem entrar.

Outras hospedagens (Railway, Fly.io) funcionam igual: comando `python mvp/server.py`, as variáveis acima e um volume para o banco.

Sessões e tokens continuam só na memória: depois de cada reinício ou publicação é preciso conectar de novo (as escolhas ficam no banco).

## Testes

`python -m unittest discover -s tests -v` nesta pasta. Os testes usam Spotify, Deezer e LRCLIB simulados e banco temporário; não comprovam o acesso real da sua conta à API.

- [Spotify: migração de endpoints de fevereiro de 2026](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)
- [Spotify: PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow)
- [Spotify: remover itens de playlist](https://developer.spotify.com/documentation/web-api/reference/remove-items-playlist)
