# Verificação — 13 de novembro de 2026

22 testes automatizados aprovados com Python 3.14, bancos temporários e Spotify simulado.

Cobertura: importação, isolamento por conta, preservação de revisões, exclusões, critérios combinados, renomeação e preservação de destinos, classificação automática usando metadados corrigidos, inicialização sem amostra pessoal, persistência do Client ID, invalidação da prévia, criação/preenchimento e atualização sem duplicações, falhas parciais e respostas perdidas, lotes de 100, paginação e relinking, Origin/CSRF e confirmação com validade e uso único.

A execução precisa de acesso normal aos diretórios temporários. O ambiente restrito de execução inicial impediu o SQLite de abri-los; a mesma suíte executada com acesso autorizado passou.

A integração real com a conta ainda depende do Client ID e do login oficial. Os testes não criaram playlists reais. Metadados incompletos continuam exigindo revisão; não foi medida uma nova taxa de classificação.

Interface verificada no navegador: carregamento das 40 faixas, salvamento e renomeação de regras preservando associações, busca e mudança de uma faixa para distribuição automática. Teste adicional de callback OAuth simulado confirma que o primeiro login preserva critérios sem copiar faixas pessoais.

## Correção HTTP 503 — 15/11/2026

29 testes aprovados. Novos cenários: recuperação de erros transitórios, cache após sucesso, limite de três tentativas, pausa por fonte após esgotamento, respeito a Retry-After (segundos/data), falhas permanentes sem repetição e garantia de não repetir gravações no Spotify. Consulta fictícia real ao MusicBrainz concluída com sucesso. A disponibilidade externa continua variável; não foi revalidada a classificação da biblioteca pessoal.

