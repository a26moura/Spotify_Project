# Spotify Project

Organizador pessoal que distribui as músicas curtidas no Spotify em playlists por gênero, idioma e outros critérios escolhidos pelo usuário. Roda localmente (Python 3, só biblioteca padrão), classifica com fontes públicas e com um modelo local (Ollama) e só grava no Spotify depois de uma prévia confirmada.

## Como usar

1. Abra `mvp/INICIAR.cmd` (requer Python 3.10+). O navegador abre em http://127.0.0.1:8765.
2. Conecte o Spotify (OAuth PKCE, só o Client ID; instruções na tela e em [mvp/README.md](mvp/README.md)).
3. Em **Escolher critérios**, defina cada playlist: nome, descrição, gêneros, idiomas e/ou artistas. Dentro de um campo vale OU; entre campos vale E (ex.: Trap **e** Português).
4. **1. Classificar músicas**: sincroniza a conta e preenche gênero e idioma pelas fontes; o Ollama completa só o que ficar vazio.
5. **2. Organizar nas playlists**: o Ollama decide a participação em cada playlist, com justificativa. Confira a prévia e confirme para criar ou completar as playlists.

O app só adiciona músicas: não remove faixas, não desfaz curtidas e nunca repete uma gravação automaticamente. Suas revisões manuais têm prioridade sobre qualquer fonte.

## Como a classificação funciona

Cada campo guarda a sua origem, e uma fonte mais forte substitui uma mais fraca:

| Campo | Ordem de confiança |
|---|---|
| Gênero | faixa (MusicBrainz/Wikidata) > álbum (Deezer, por ISRC) > artista (MusicBrainz, identidade confirmada) > IA (Ollama) |
| Idioma | faixa (MusicBrainz/Wikidata) > letra (LRCLIB, detecção local sem IA) > IA (Ollama) |

Na distribuição, o modelo só decide sobre músicas que já têm gênero ou idioma, e um "sim" só vale se a música tiver o dado que a playlist pede. Os critérios explícitos da playlist sempre valem. Detalhes em [mvp/CLASSIFICACAO.md](mvp/CLASSIFICACAO.md).

## Estrutura

```text
Spotify_Project/
  README.md              Este arquivo
  CLAUDE.md              Contexto e regras para o Claude Code
  mvp/
    INICIAR.cmd          Inicia o servidor local
    server.py            Servidor HTTP local, sessões, OAuth e rotas da API
    core.py              Regras, critérios, origens e banco SQLite por conta
    providers.py         Spotify, MusicBrainz, Wikidata, Deezer, LRCLIB, prévia e gravação
    classification.py    Ollama (classificação e distribuição) e mesclagem por origem
    lyrics_language.py   Detecção local de idioma pela letra
    static/              Interface (HTML, CSS, JS)
    tests/               Testes automatizados (APIs simuladas)
    README.md            Instalação, conexão e comportamento de gravação
    CLASSIFICACAO.md     Cadeia de classificação, fontes e limites
    FLUXO.md             Fluxo de organização
    PIPELINE.md          Desenho da pipeline
    VALIDACAO.md         Histórico de verificações
```

Ficam fora do Git (dados pessoais): `mvp/runtime/` (banco, configuração, cache), `mvp/data/` (amostra pessoal) e `arquivo/` (pesquisa inicial: exportação da biblioteca, validação das 40 faixas e scripts exploratórios).

## Testes

```powershell
cd mvp
python -m unittest discover -s tests -v
```

## Fontes, termos e privacidade

- **Spotify**: modo de desenvolvimento; os termos restringem o uso de conteúdo da plataforma em modelos de IA e o acesso público exige aprovação. [Developer Policy](https://developer.spotify.com/policy), [modos de acesso](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- **MusicBrainz**: dados básicos CC0; gêneros e tags CC BY-NC-SA 3.0. Limite de ~1 consulta/s. [Licença](https://musicbrainz.org/doc/About/Data_License).
- **Wikidata**: CC0. [Licença](https://www.wikidata.org/wiki/Wikidata:Copyright).
- **Deezer**: API gratuita só para uso pessoal, privado e não comercial; imagens não podem ser armazenadas. O app guarda só ID, título e gêneros do álbum. [Termos](https://developers.deezer.com/termsofuse).
- **LRCLIB**: não declara licença das letras; o app detecta o idioma e descarta a letra. [Documentação](https://lrclib.net/docs).
- **Ollama**: modelo local; nenhuma informação vai para serviços de IA externos.

Este projeto é uma ferramenta pessoal e não comercial. Um site público exigiria aprovação do Spotify, acordos com fontes como o Deezer, HTTPS, armazenamento seguro de tokens e política de dados. Não exponha o servidor local na internet.

## Situação (17/11/2026)

- Conta real conectada (351 curtidas). Primeira execução com as fontes novas: 185 músicas consultadas; 157 com gênero e 177 com idioma.
- Corrigido: a IA distribuía músicas sem dados adivinhando pelo nome do artista; "funk" vindo das fontes agora é tratado como funk internacional.
- Próximos passos: terminar a etapa 1 nas músicas pendentes; campo "rótulos que não contam" por playlist (generaliza a regra do funk); sugerir playlists para gêneros sem destino (Rock, Pop, Inglês); modo rápido (Deezer/LRCLIB antes do MusicBrainz); filtro "decisões da IA para conferir".
