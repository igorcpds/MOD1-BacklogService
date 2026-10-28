# Contrato — backlog 0.2.0

| Método | Rota | Resultado |
| --- | --- | --- |
| POST | `/projects/{project_id}/stories` | 201, Story |
| GET | `/projects/{project_id}/stories` | 200, StoryPage |
| GET | `/projects/{project_id}/stories/{story_id}` | 200, Story |
| PATCH | `/projects/{project_id}/stories/{story_id}` | 200, Story |
| GET | `/health/live` | 200, processo ativo |
| GET | `/health/ready` | 200/503, tabela própria acessível |

Histórias exigem `Authorization: Bearer <JWT>` e retornam `Cache-Control: no-store`.
Readiness verifica apenas o banco do backlog; não garante disponibilidade externa.

POST aceita `title` (aparado, 1–120 caracteres Unicode), `description` e
`acceptance_criteria` (opcionais, padrão vazio, até 2000 cada), `priority`
(`high`, `medium`, `low`, padrão `medium`). HTML e quebras de linha são texto literal.
Campos extras, null e outros tipos são recusados. PATCH aceita subconjunto não vazio
de `title` (aparado, 1–120), `description`/`acceptance_criteria` (0–2000), `priority`
e `status` (`todo`, `in_progress`, `done`); null é recusado mesmo junto a campos válidos.
Descrição e critérios vazios apagam o texto anterior. IDs, autor, projeto e datas
não são editáveis. Não há alteração de schema nem migração nesta versão.

Story contém `id`, `project_id`, `created_by`, `title`, `description`,
`acceptance_criteria`, `priority`, `status`, `created_at`, `updated_at`.
IDs/datas UTC vêm do servidor; autor do JWT, projeto da rota. StoryPage contém
`items`, `total`, `limit`, `offset`. Paginação: `limit=20` (1–100), `offset=0`
(não negativo). Ordem: alta → média → baixa, criação crescente, UUID no desempate.
PATCH com os mesmos valores preserva `updated_at`; alterações efetivas atualizam a data.

GET da coleção aceita `q` (padrão vazio, aparado, até 200 caracteres Unicode),
`status` e `priority` opcionais com os mesmos enums das histórias. A busca literal
ignora maiúsculas/minúsculas em título ou descrição, ou corresponde ao UUID exato
da história. `%`, `_` e `!` não são curingas. Critérios de aceite não participam
da busca. Texto vazio só desativa a busca; os filtros continuam ativos.
Os filtros combinam AND e são aplicados antes de calcular `total`, `limit` e `offset`,
preservando a ordenação. Exemplo: `?q=entrega&status=done&priority=high&limit=20`.

## Acesso

RS256, `typ=JWT`, `kid`, issuer/audience configurados, `iat`/`exp` inteiros,
`sub`/`jti` UUIDs. JWKS exclusivamente configurado: timeout 5 s, cache 300 s,
refresh mínimo 30 s inclusive falhas. Um kid novo pode aguardar esse intervalo;
chaves conhecidas em cache não esperam rede. Não há revogação imediata.

Cada operação confirma acesso por GET `/projects/{project_id}` na API configurada,
com o mesmo Bearer, timeout 5 s, sem retry/redirect/cache de autorização.
UUID do projeto e proprietário precisam coincidir com rota e JWT. Nenhuma história
é consultada/gravada antes disso. Sem FK/join/leitura de outros módulos;
`created_by` registra autoria, não autorização.

| Status | Significado |
| --- | --- |
| 401 | Token ausente/inválido ou rejeitado por projetos; `WWW-Authenticate: Bearer` |
| 404 | Projeto ausente/alheio, história ausente ou de outro projeto; mesma mensagem |
| 422 | Entrada, busca, enum ou paginação inválida, sem repetir valores |
| 503 | Banco/JWKS/projetos indisponíveis ou inconsistentes; mensagem genérica |

Não reenviar automaticamente POST/PATCH após timeout: a gravação pode ter ocorrido.
Sucesso seguido de falha de recarga confirma a gravação e orienta atualizar a lista.
