# Revisões de código — Módulo 4

A aplicação conecta o cliente do Módulo 4 a registros duráveis por item.
Uma análise síncrona válida move somente `todo` para `in_progress`; itens já
iniciados ou concluídos preservam o status. A conclusão continua manual.
A integração fica desabilitada por padrão. As evidências locais abaixo não
comprovam publicação ou disponibilidade de produção.

## API do Backlog

`POST /projects/{project_id}/items/{item_id}/code-reviews` recebe `request_id`
(UUID), `expected_version` (inteiro positivo), `arquitetura`, `usar_ia` e
exatamente uma origem: `pr_url` ou `arquivos` (`caminho`/`conteudo`).
Exige sessão online válida, `backlog:read`, `backlog:update_status` e projeto
editável. Responde 201 com um registro durável, inclusive para falha, bloqueio
ou resultado incerto. Provedor desabilitado retorna 503 sem criar tentativa.

O registro contém `id`, `request_id`, `project_id`, `item_id`, `status`,
`created_at`, `updated_at`, `source` (tipo, PR e caminhos), `arquitetura`,
`usar_ia`, `result`, `error`, `status_effect` e `item_version`.
Estados: `pending`, `succeeded`, `failed`, `blocked`, `uncertain`.
Efeitos: `started`, `preserved`, `not_applied_conflict`, `not_applied_access`,
`not_applied_error`. A tentativa pendente usa inicialmente
`not_applied_error`, pois nenhuma mudança foi aplicada.

Conteúdo de entrada não é persistido: somente caminhos/PR, preferências e
SHA-256 do pedido completo, incluindo a versão. Resultados do provedor são
persistidos e podem conter trechos citados pelo próprio relatório.

A mesma combinação de projeto, item e UUID devolve o estado gravado sem novo
POST. Conteúdo diferente com o mesmo UUID retorna 409. Tentativas pendentes
após interrupção e resultados incertos nunca são reenviados. Nova análise
explícita exige outro UUID e pode duplicar uma análise já feita pelo provedor.

A tentativa pendente é confirmada sob lease e lock curtos, liberados antes
do HTTP. A resposta é persistida antes de revalidar sessão e permissões.
Antes da mudança de status, outro lease é adquirido, o acesso atual é
revalidado e a versão do item é verificada sob lock. Mudança concorrente
preserva item e resultado com `not_applied_conflict`. A mudança real de status,
versão, histórico e captura M6 são atômicos com o efeito final do registro.
Perda de acesso preserva o resultado internamente com `not_applied_access`
e retorna a recusa de acesso sem expor o relatório nessa resposta.

`GET` no mesmo caminho recebe `limit` (1–100, padrão 20) e `offset` (>=0,
padrão 0), retornando `{items,total,limit,offset,enabled}`. `GET /{review_id}`
retorna um registro daquele projeto/item. Ambos exigem `backlog:read` e
funcionam com o provedor desabilitado. Não há histórico global ou retry.

## Contrato do proprietário

Base: `https://revisor-codigo-ia-gio-ach9dbg3g9ekazf3.chilecentral-01.azurewebsites.net`.
HTTP Basic somente no backend. Health público; Swagger e OpenAPI autenticados
não tipam o corpo nem o resultado da análise.

`POST /api/analisar` recebe PR HTTPS do GitHub ou até 20 arquivos Python
relativos, com limite total local de 100.000 bytes UTF-8. Arquiteturas:
`multicamadas`, `clean`, `mvc`, `hexagonal`, `onion`. IA fica desativada até
escolha explícita em `usar_ia`.

Uma análise estática real de código fictício retornou HTTP201 em 16/11/2026,
embora o Swagger declare somente 200. O cliente aceita 200/201 com resposta
validada: `id`, `criado_em`, `arquitetura`, `arquivos`, `achados`, `testes`,
`testes_executados`, `pr`, `ia`, `markdown`. Achados contêm arquivo, linha
opcional, categoria, gravidade, título e sugestão; IA contém `status`/`texto`.
JSON não finito, inclusive overflow numérico aninhado, é recusado.

Uma resposta válida não significa merge, aprovação de negócio ou conclusão.
O ingresso antigo de eventos permanece separado e desabilitado. A API do
Módulo 4 não anunciou callback. Não consultamos histórico global nem
publicamos comentários em PR.

O destino é restrito à origem oficial ou HTTP loopback explícito para testes.
O cliente usa Basic dedicado, sem Bearer/cookies do usuário, proxies,
redirecionamento ou retries. Prazo total de 60 segundos, leitura de 10 segundos,
conexão de 5 segundos e resposta limitada a 1 MiB. Credencial/cota recusada
gera bloqueio; timeout, 5xx e recibo inválido permanecem incertos. Erros são
sanitizados e não armazenam corpo de falha nem detalhes de autenticação.

## Configuração e migração

Configure `MODULE4_ENABLED`, `MODULE4_BASE_URL`, `MODULE4_USERNAME` e
`MODULE4_PASSWORD` somente no backend. Usuário e senha são secretos;
configuração habilitada incompleta é recusada. Nunca colocar credenciais em
frontend, Git, logs ou exemplos. `CODE_REVIEW_ENABLED` continua separado.

`module4_reviews` pertence ao schema do Backlog. Execute `backlog-service init`
com papel de migração antes de habilitar a função. A criação da tabela é
aditiva e idempotente e não ocorre no startup. O papel runtime precisa de
SELECT/INSERT/UPDATE nessa tabela. Desabilitar `MODULE4_ENABLED` permite
rollback da aplicação preservando todos os registros.

## Validação local

```powershell
uv run python -m pytest tests/test_module4_client.py tests/test_module4_service.py tests/test_module4_api.py tests/test_architecture.py -q
```

Os testes cobrem HTTP real local, Basic dedicado, limite/prazo sem reenvio,
persistência antes do POST, replay, perda de sessão/permissão, conflito de
versão, rollback e captura M6. PostgreSQL descartável loopback verifica
migração, concorrência entre UUIDs iguais/diferentes e persistência após
reinício. Os testes não precisam de senha real nem chamadas externas.
