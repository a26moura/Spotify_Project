# Spotify Project

Organizador pessoal em forma de jogo: as suas músicas aparecem uma a uma, com capa, informações e prévia de 30 s, e você as arrasta para as playlists onde elas combinam. No final, uma prévia mostra o que entra e o que sai de cada playlist, e só depois da sua confirmação o app grava no Spotify. Roda localmente (Python 3, só biblioteca padrão).

## Como usar

1. Abra `mvp/INICIAR.cmd` (Python 3.10+). O navegador abre em http://127.0.0.1:8765.
2. **Conectar**: login no Spotify (OAuth PKCE, só o Client ID; instruções na tela e em [mvp/README.md](mvp/README.md)). O app importa as curtidas e as playlists criadas por você, e começa a buscar informações das músicas em segundo plano.
3. **Playlists**: edite nome e descrição, diga o idioma e o gênero (ou clima) de cada playlist, crie novas e marque até 8 para o jogo.
4. **Jogo**: arraste o cartão para uma ou mais playlists (ou use as teclas 1–8). Músicas que já estão numa playlist aparecem marcadas; desmarcar significa tirar dela. Enter passa, Espaço toca/pausa, S pula, Ctrl+Z desfaz. O progresso fica salvo. Para revisar uma playlist, use **Jogar só esta** no cartão dela: a rodada mostra só as músicas daquela playlist.
5. **Prévia**: confira, por playlist, as músicas que entram e saem e as mudanças de nome e descrição. **Gravar no Spotify** pede confirmação.

O app nunca grava sem prévia confirmada, nunca repete uma gravação automaticamente e não mexe em playlists que mudaram no Spotify depois da prévia. Playlists novas são criadas como privadas. Detalhes do fluxo em [mvp/FLUXO.md](mvp/FLUXO.md).

Para ver o app sem a sua conta: `cd mvp; python demo_server.py` abre http://127.0.0.1:8799 com músicas fictícias e um Spotify simulado.

## Informações das músicas

| Informação | De onde vem |
|---|---|
| Título, artistas, álbum, ano, capa, duração, explícita, data da curtida | Spotify |
| Gênero do álbum, BPM, prévia de 30 s | Deezer, pelo ISRC ou, se não achar, por título e artista (com conferência de artista, título e duração) |
| Idioma | Detectado localmente na letra do LRCLIB (a letra não é guardada) |

O idioma e o gênero da playlist só destacam sugestões no jogo ("Combina"); quem decide é você. A mesma gravação com dois ids no Spotify (single e álbum, edição deluxe) vira um cartão só, pelo ISRC. Detalhes em [mvp/CLASSIFICACAO.md](mvp/CLASSIFICACAO.md).

## Estrutura

```text
Spotify_Project/
  README.md              Este arquivo
  CLAUDE.md              Contexto e regras para o Claude Code
  mvp/
    INICIAR.cmd          Inicia o servidor local
    server.py            Servidor HTTP local, sessões, OAuth e rotas da API
    core.py              Banco SQLite por conta, importação e origem das informações
    game.py              Perfis das playlists, escolhas do jogo, desfazer, fila e cartão
    collector.py         Coleta em segundo plano (Deezer e LRCLIB)
    publish.py           Prévia final e gravação no Spotify
    providers.py         Spotify, Deezer e LRCLIB
    lyrics_language.py   Detecção local de idioma pela letra
    demo_server.py       Demonstração com dados fictícios e Spotify simulado
    static/              Interface (HTML, CSS, JS)
    tests/               Testes automatizados (APIs simuladas)
    README.md            Instalação, conexão, segurança e gravação
    CLASSIFICACAO.md     Fontes das informações e limites
    FLUXO.md             O fluxo do jogo, passo a passo
```

Ficam fora do Git (dados pessoais): `mvp/runtime/` (banco, configuração, cache), `mvp/data/` e `arquivo/` (pesquisa inicial).

## Testes

```powershell
cd mvp
python -m unittest discover -s tests -v
```

## Fontes, termos e privacidade

- **Spotify**: modo de desenvolvimento; o acesso público exige aprovação. [Developer Policy](https://developer.spotify.com/policy), [modos de acesso](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- **Deezer**: API gratuita só para uso pessoal, privado e não comercial; imagens não podem ser armazenadas. O app guarda só IDs, título e gêneros do álbum e BPM; o link da prévia é buscado na hora e não é guardado. [Termos](https://developers.deezer.com/termsofuse).
- **LRCLIB**: não declara licença das letras; o app detecta o idioma e descarta a letra. [Documentação](https://lrclib.net/docs).

Este projeto é uma ferramenta pessoal e não comercial. Um site público exigiria aprovação do Spotify, acordos com fontes como o Deezer, HTTPS, armazenamento seguro de tokens e política de dados. Não exponha o servidor local na internet.

## Histórico

- Até 19/11/2026 o app classificava com MusicBrainz, Wikidata e Ollama e distribuía as músicas automaticamente por critérios. Essa versão foi substituída pelo jogo (veja o histórico do Git). As informações já coletadas continuam no banco e aparecem nos cartões.
