# Contrato — backlog 0.1.0

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
Campos extras, null e outros tipos são recusados. PATCH aceita somente `priority`
e/ou `status` (`todo`, `in_progress`, `done`), ao menos um campo não null.

Story contém `id`, `project_id`, `created_by`, `title`, `description`,
`acceptance_criteria`, `priority`, `status`, `created_at`, `updated_at`.
IDs/datas UTC vêm do servidor; autor do JWT, projeto da rota. StoryPage contém
`items`, `total`, `limit`, `offset`. Paginação: `limit=20` (1–100), `offset=0`
(não negativo). Ordem: alta → média → baixa, criação crescente, UUID no desempate.
PATCH com os mesmos valores preserva `updated_at`; alterações efetivas atualizam a data.

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
| 422 | Entrada/paginação inválida, sem repetir valores |
| 503 | Banco/JWKS/projetos indisponíveis ou inconsistentes; mensagem genérica |

Não reenviar automaticamente POST/PATCH após timeout: a gravação pode ter ocorrido.
Sucesso seguido de falha de recarga confirma a gravação e orienta atualizar a lista.
