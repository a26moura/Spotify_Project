# Resultado da revisão humana

## Confirmações

- **A Million Dreams:** idioma corrigido para Inglês, conforme confirmação no chat.
- **Oliveira Dos Cen Anos:** deixar fora das playlists do projeto. Não remover das curtidas do Spotify.

A planilha preenchida foi preservada como recebida. As confirmações posteriores estão em `revisao-consolidada.json`, junto dos valores originais.

## Resultado

| Indicador | Quantidade |
|---|---:|
| Entradas com resposta ou comentário do usuário | 40 |
| Incluídas no projeto | 39 |
| Excluídas das playlists do projeto | 1 |
| Gênero preenchido | 35 |
| Idioma preenchido, incluindo a confirmação | 39 |
| Incluídas com destino de playlist, sem gênero preenchido | 4 |
| Gênero preenchido igual à sugestão | 12 |
| Gênero preenchido seleciona parte da sugestão | 10 |
| Classificadas manualmente sem sugestão | 12 |
| Gênero preenchido diferente da sugestão | 1 |

As últimas quatro categorias somam as 35 respostas de gênero. A comparação normaliza acentos e maiúsculas. Não é uma taxa de acerto: os campos de decisão continuam Pendente, há preferências pessoais de agrupamento e uma dúvida explícita sobre o gênero de Moonlight on the River. A meta de 80% de aceitação continua sem medição conclusiva.

## Gênero e destino são campos diferentes

O usuário identifica Faded como Eletrônica e prefere incluí-la em Pop. Também quer La Bachata na playlist Reggaeton, sem preencher um gênero alternativo. Essas escolhas devem ser armazenadas como destinos desejados, sem substituir automaticamente o gênero musical.

Quatro músicas incluídas têm apenas destino informado nos comentários: Life Goes On (Pop), Not Like Us (Pop), Take Me Back To Eden (Rock) e La Bachata (Reggaeton). O gênero pode continuar desconhecido sem impedir a organização manual.

As playlists em Espanhol e Francês demonstram interesse em agrupamento por idioma. A revisão de ReawakeR escolhe Japonês, mas a fonte registra Japonês e Inglês: manter ambos os registros evita tratar uma preferência como prova de ausência de outro idioma.

## Requisitos propostos a partir da revisão

1. Manter separadamente gênero sugerido, gênero informado pelo usuário, idioma e playlists desejadas.
2. Permitir vários destinos para uma faixa e preservar preferências pessoais nas atualizações.
3. Oferecer “Deixar fora do projeto” sem alterar as músicas curtidas no Spotify.
4. Permitir destino manual quando gênero estiver ausente ou incerto.
5. Tornar a revisão mais simples: o usuário preencheu os campos e comentários, mas não utilizou o menu de decisões. Uma ação clara para salvar a revisão deve evitar esse desencontro.

## Próximo passo

Confirmar as categorias das playlists antes de desenhar a pipeline. Candidatas de gênero presentes nas respostas: Rock, Pop, Reggaeton, Sertanejo, Trap, Funk, Eletrônica e Vallenato. O usuário pode preferir agrupar Vallenato apenas em Espanhol. Categorias por idioma e regras de inclusão devem ser definidas separadamente.
