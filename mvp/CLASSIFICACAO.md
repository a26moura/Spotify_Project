# Informações das músicas

O jogo não depende de classificação: quem decide a playlist é você. As informações servem para ajudar a decidir (no cartão) e para destacar as playlists que combinam.

## Fontes

| Informação | Fonte | Como |
|---|---|---|
| Título, artistas, álbum, ano, capa, duração, explícita, data da curtida | Spotify | Na sincronização. A capa vem do endereço do Spotify e não é guardada como imagem. |
| Gênero do álbum, BPM, id da faixa | Deezer | Pelo ISRC. Só é aceito se o artista principal da faixa estiver entre os artistas do Deezer. Resultado em cache por 30 dias. |
| Prévia de 30 s | Deezer | Buscada no momento em que o cartão aparece (o link expira) e nunca guardada. |
| Idioma | LRCLIB + `lyrics_language.py` | A letra é baixada, o idioma é detectado localmente por palavras características e a letra é descartada. Pede pelo menos 30 palavras; mistura de dois idiomas aparece como dois idiomas; "Instrumental" quando o LRCLIB marca a faixa assim. |

A coleta (`collector.py`) roda em segundo plano depois da sincronização, uma música por vez, com espaçamento entre consultas (Deezer 0,25 s, LRCLIB 0,7 s). Músicas cuja fonte falhou temporariamente são tentadas de novo (até 3 passadas, com pausa de 60 s); depois ficam pendentes até a próxima coleta.

## Origem e prioridade

Cada campo guarda de onde veio (`genre_origin`, `language_origin`), e uma fonte mais forte nunca é substituída por uma mais fraca:

- Gênero: faixa > álbum > artista > IA.
- Idioma: faixa > letra > IA.

"Faixa", "artista" e "IA" são origens de informações coletadas pela versão anterior do app (MusicBrainz, Wikidata e Ollama), que continuam no banco. A coleta atual só adiciona "álbum" e "letra". Gêneros de álbum genéricos do Deezer ("Latin Music", "Brazilian Music"…) só preenchem um gênero vazio; ficam sempre como rótulos extras. Revisões manuais feitas na versão anterior continuam valendo acima de qualquer fonte.

## "Combina" no jogo

Uma playlist aparece como **Combina** quando:
- o idioma dela é um dos idiomas da música ("Misto" nunca combina); ou
- o gênero ou clima dela aparece em algum rótulo de gênero da música (gênero principal, gêneros do álbum e do artista). Palavras com 3 letras ou mais também contam como trecho, então "funk" combina com "funk carioca".

É só um destaque visual; nada é marcado sozinho.

## Limites

- Músicas sem ISRC, ou que o Deezer não tem, ficam sem gênero do álbum, BPM e prévia de áudio.
- O gênero do álbum nem sempre é o da faixa.
- A detecção de idioma precisa da letra no LRCLIB e falha em letras curtas.
- Não há análise de áudio.
