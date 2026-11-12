# Validação exploratória — 40 músicas curtidas

## Objetivo

Medir a utilidade de MusicBrainz e Wikidata para sugerir gêneros amplos e idiomas, antes de implementar o produto. Este estudo não treina modelos nem chama uma API de IA para classificação.

## Amostra

Amostra intencional, não aleatória e não representativa estatisticamente das 336 entradas. As 40 posições estão fixadas em `research_sample.py`. A seleção inclui faixas recentes, artistas diferentes, músicas brasileiras e internacionais, colaborações, versões ao vivo, remix e trilhas. Essas características orientaram a seleção; não são rótulos de gênero confirmados.

Não extrapolar percentuais desta amostra para toda a biblioteca. Uma segunda etapa deveria usar uma amostra aleatória e um conjunto separado para validar mudanças nas regras.

## Consulta e identidade

- MusicBrainz: pesquisa por título e primeiro artista, até 15 candidatos. Correspondência normalizada de título/artista e preferência heurística de versão. Consulta gêneros da gravação, até dois grupos de lançamento e primeiro artista, além de idioma das obras relacionadas.
- Wikidata: pesquisa de título, até 10 candidatos, valida título/alias e pelo menos um intérprete. Consulta P136 (gênero), P407 (idioma) e P175 (intérprete). Uma auditoria posterior inclui os rótulos padrão multilíngues (`mul`), além de idiomas específicos, e exclui entidades que representam apenas videoclipes ou álbuns. Isso evita perder artistas que usam rótulo padrão em vez de nome cadastrado separadamente em inglês.
- A busca limitada pode perder registros existentes. “Não localizado” significa não encontrado pelo método, não ausência comprovada da base.
- O Spotify exportado não inclui ISRC, duração ou álbum. Portanto, a gravação exata permanece pendente de confirmação, mesmo quando título e artista correspondem.
- Títulos podem ser simplificados na busca (como remoção de sufixo “Ao Vivo” e participações), mas o original é preservado e a ressalva de versão deve aparecer na revisão.
- Idioma de lançamento no MusicBrainz descreve texto da edição e não necessariamente o idioma cantado. Não é utilizado como idioma da faixa.

## Evidências e propostas

Gênero da gravação ou de entidade musical correspondente no Wikidata é evidência direta de catálogo, ainda sujeita a erro. Gênero de álbum/single é contexto. Gênero do artista é uma hipótese fraca para a faixa. As três origens devem permanecer distinguíveis.

As categorias amplas são propostas por regras explícitas e revisão editorial das evidências. Não inferir idiomas pelo título nem gêneros pela nacionalidade. Tags culturais, trilhas e idioma não devem ser confundidos com gêneros. Contagem de votos do MusicBrainz não é probabilidade de acerto.

## Métricas

1. Identificação candidata: entradas com correspondência de título e artista/intérprete.
2. Cobertura direta: entradas com pelo menos um gênero no registro musical candidato.
3. Cobertura contextual: entradas que dependem de gênero do lançamento ou artista.
4. Idioma documentado: entradas com idioma da obra ou P407.
5. Aceitação: sugestões aceitas sem alteração / sugestões efetivamente revisadas pelo usuário. Ainda não medida.
6. Trabalho manual: faixas corrigidas, deixadas pendentes e tempo de revisão. Ainda não medido.

80% de aceitação é uma meta experimental, não um resultado. Cobertura e precisão não são equivalentes.

## Origem e licenças

- Dados e respostas de MusicBrainz: https://musicbrainz.org/doc/MusicBrainz_Database e https://musicbrainz.org/doc/About/Data_License . Dados básicos CC0; tags e associações de gênero CC BY-NC-SA 3.0. Este é um estudo pessoal não comercial. Atribuição ao MusicBrainz e contribuidores; derivados desses dados seguem a licença aplicável. Não pressupor autorização comercial.
- Dados estruturados Wikidata: CC0, https://www.wikidata.org/wiki/Wikidata:Copyright .
- Respostas consultadas ficam em `respostas/`, acompanhadas de URL e data. `resultados-brutos.json` conserva candidatos e evidências.
- Os dados da biblioteca identificam a coleção pessoal e não devem ser publicados por padrão. O estudo não altera playlists.
- A análise técnica não resolve, por si só, a admissibilidade de um produto integrado ao Spotify. Sua política de análise e IA permanece uma questão separada antes de lançamento público: https://developer.spotify.com/policy .

## Revisão humana

Para cada faixa: aceitar, corrigir ou deixar pendente. Pode haver vários gêneros. Registrar uma correção não significa aplicá-la a todas as músicas do artista. “Latinas” é uma escolha editorial separada de idioma, e permanece a definir.
