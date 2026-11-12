# Spotify Project

Organizador de músicas curtidas em playlists por gênero, idioma e agrupamentos escolhidos pelo usuário.

## Objetivo

Começar com uma ferramenta pessoal para a biblioteca de 336 entradas do Spotify e avaliar, depois, a possibilidade de hospedar um site para outros usuários. Hospedar uma interface não significa obter autorização para acesso público irrestrito à API do Spotify.

O projeto está na fase de validação dos dados. Ainda não há site, aplicação de produção, integração OAuth própria ou criação automática de playlists.

## Decisões já tomadas

- Categorias de gênero amplas: sertanejo, trap, reggaeton, pop, rock etc.
- O sistema sugere categorias; o usuário escolhe quais viram playlists e pode renomear ou juntar categorias.
- Uma música pode pertencer a várias playlists.
- Gênero, idioma e agrupamento cultural são dimensões separadas. “Em espanhol” e “Latinas” não são equivalentes.
- Prévia e revisão antes de criar as playlists; músicas incertas ficam para revisão.
- Atualização por botão, preservando correções e evitando duplicações.
- MusicBrainz e Wikidata são as primeiras fontes em avaliação.
- IA é opcional e só será incorporada se houver dados com uso permitido e melhoria mensurável sobre as regras básicas.

## Etapas do projeto

| Etapa | Entrega | Situação |
|---|---|---|
| 1. Amadurecer a ideia | Objetivo, categorias e experiência inicial | Concluída nesta primeira definição |
| 2. Pesquisar viabilidade | Fontes, licenças e limites do Spotify | Pesquisa inicial concluída; condições para lançamento público pendentes |
| 3. Coletar biblioteca | Títulos, artistas e links de 336 entradas | Concluída |
| 4. Validar 40 músicas | Consultas, evidências e sugestões para revisão | Ver status em `validacao/STATUS.md` |
| 5. Revisar com o usuário | Respostas, preferências e exclusões | Respostas coletadas; ver `validacao/RESULTADO-REVISAO.md`. Aceitação formal e tempo não medidos |
| 6. Escolher classificação | Comparar regras e possível uso de IA; validar permissões | Pendente |
| 7. Desenhar pipeline | Entrada, identidade, enriquecimento, categorias, revisão e saída | Pendente; ainda não é uma arquitetura aprovada |
| 8. Implementar MVP | Login, importação, sugestões, prévia, criação e botão de atualização | Pendente |
| 9. Testar ponta a ponta | Correções persistentes, duplicações, falhas parciais e versões | Pendente |
| 10. Hospedar piloto | Site e acesso limitado conforme permissões disponíveis | Pendente |
| 11. Avaliar abertura pública | Acesso à API, licenças comerciais, custos e privacidade | Pendente |

## Validação atual

A amostra tem 40 faixas escolhidas intencionalmente para incluir variedade de artistas, colaborações, versões e possíveis dificuldades. Não é uma amostra estatística da biblioteca.

Consultamos candidatos por título e artista, gêneros e idiomas documentados. A tabela distingue evidência da própria música, contexto do lançamento, hipótese pelo artista e ausência de informação suficiente.

O objetivo inicial de 80% de aceitação é uma **meta**, não um resultado. A aceitação só poderá ser medida depois da revisão do usuário. Cobertura de catálogo não equivale à precisão de classificação.

A exportação inicial não contém ISRC, álbum ou duração. Por isso, um candidato com o mesmo título e artista não confirma a gravação exata. Há 336 URLs únicas, mas também títulos/artistas repetidos em URLs diferentes; deduplicação por URL não resolve toda duplicação musical.

### Como revisar

Abra [a tabela de revisão](validacao/revisao-40.md). Para cada linha, escolha `aceitar`, `corrigir` ou `não sei`, e registre os gêneros/idiomas desejados. Também é possível enviar as correções no chat usando os números da amostra.

Não aprovar automaticamente a partir de gênero do artista. As correções serão decisões pessoais, e não precisam substituir a informação original da fonte.

## Arquivos

```text
Spotify_Project/
  README.md                      Plano e decisões do projeto
  musicas-curtidas.json           Biblioteca original com 336 entradas
  musicas-curtidas.md             Biblioteca em formato legível
  research_sample.py             Consulta exploratória às duas fontes
  repair_wikidata_labels.py       Auditoria dos rótulos multilíngues do Wikidata
  build_review.py                Gera tabela e métricas a partir das respostas
  validacao/
    STATUS.md                    Situação da validação e indicadores
    METODOLOGIA.md                Seleção, regras, limites e atribuição
    amostra.json                 As 40 faixas selecionadas
    resultados-brutos.json       Candidatos e evidências consultadas
    revisao-40.md                Tabela para revisão humana e fontes por faixa
    revisao-40.json              Sugestões e campos de revisão estruturados
    respostas/                  Cache das respostas, URLs e datas
```

## Reproduzir a pesquisa

Os scripts usam Python 3 e a biblioteca padrão, sem dependências externas. Execute no diretório do projeto:

```powershell
python research_sample.py
python repair_wikidata_labels.py
python build_review.py
```

Os dois primeiros scripts acessam APIs públicas e enviam títulos/artistas necessários às consultas. A coleta respeita intervalos entre requisições e mantém cache local. Ela não solicita sua senha nem acessa sua conta do Spotify. O script de consulta retoma resultados concluídos; não é um mecanismo de atualização de catálogo em produção.

**Faça uma cópia da revisão antes de executar `build_review.py` novamente:** ele recria `revisao-40.md` e `revisao-40.json`, incluindo os campos de decisões. Não sobrescrever revisões humanas será um requisito do aplicativo futuro.

## Restrições e decisões pendentes

- MusicBrainz: dados básicos CC0; associações de gênero e tags têm licença CC BY-NC-SA 3.0. O estudo é pessoal e não comercial; uso comercial requer avaliação específica.
- Wikidata: dados estruturados CC0. Cobertura e qualidade variam por registro.
- Spotify: seus termos restringem análise e entrada de conteúdo da plataforma em modelos de IA. Uma fonte externa não resolve automaticamente a admissibilidade de toda a integração.
- É preciso validar o acesso oficial da aplicação à biblioteca e a criação de playlists antes do MVP.
- Ainda falta definir o critério de “Latinas” e a política de remoção quando uma música deixa de ser curtida. A proposta inicial é não remover automaticamente, mas isso ainda deve ser confirmado no desenho do comportamento.
- Não há escolha definitiva de framework, hospedagem, banco de dados ou modelo de IA.
- A biblioteca e o cache são materiais de trabalho pessoais. Não publicar esses arquivos por padrão junto ao site ou repositório público.

Fontes: [Spotify Developer Policy](https://developer.spotify.com/policy), [modos de acesso](https://developer.spotify.com/documentation/web-api/concepts/quota-modes), [MusicBrainz — licenças](https://musicbrainz.org/doc/About/Data_License), [Wikidata — licença](https://www.wikidata.org/wiki/Wikidata:Copyright).

## Próxima decisão

Conferir a [proposta de distribuição nas oito playlists](PLAYLISTS.md) com as 39 músicas incluídas já tendo destino. Depois disso, desenhar a pipeline e o MVP.

## Revisão em planilha editável

Abra [a planilha de validação](validacao/revisao-editavel.xlsx) no Excel ou LibreOffice. As 40 músicas já estão preenchidas. Edite as células amarelas.

- Decisão de gênero: Aceitar, Corrigir, Classificar ou Não sei.
- Seu gênero: preencha ao corrigir ou classificar uma música sem sugestão. Separe vários gêneros com vírgulas.
- Seu idioma: correção opcional. Vazio mantém o original; Não sei descarta a sugestão incerta.
- Observações: registre dúvidas sobre a faixa ou categoria.
- Situação indica pendências. Os contadores se atualizam pelas decisões válidas.

Salve o arquivo após revisar. As alterações ficam nesta planilha e ainda não são sincronizadas automaticamente com o JSON ou com o Spotify. Não rode a geração novamente sobre sua cópia preenchida.

## Revisão preenchida consolidada

A revisão das 40 faixas e as confirmações do chat foram registradas em [Resultado da revisão](validacao/RESULTADO-REVISAO.md) e [Dados consolidados](validacao/revisao-consolidada.json). Há 39 faixas incluídas no projeto e 1 excluída. A planilha original foi preservada. Use a consolidação para considerar as confirmações posteriores de idioma e exclusão. Nenhuma playlist foi criada ou alterada no Spotify.

## Playlists escolhidas

POP, Sertanejo, Reggaeton, Espanhol, Frances, Trap, Rock e Funk. Os nomes estão confirmados; a distribuição das músicas é uma proposta em [PLAYLISTS.md](PLAYLISTS.md), com os dados em [playlists-definidas.json](validacao/playlists-definidas.json). Espanhol e Frances agrupam por idioma. Nenhuma playlist foi criada ou alterada no Spotify nesta etapa.


## Testar o MVP local

A versão local está implementada na pasta `mvp`. Abra [INICIAR.cmd](mvp/INICIAR.cmd) e acesse http://127.0.0.1:8765. A amostra de 40 músicas funciona sem conexão ao Spotify. Consulte [as instruções](mvp/README.md) e [o resultado dos testes](mvp/VALIDACAO.md). A integração real depende de criar um aplicativo no Spotify for Developers e configurar o Client ID. Nenhuma playlist foi alterada no Spotify.
