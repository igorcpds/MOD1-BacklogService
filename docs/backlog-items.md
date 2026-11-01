# Backlog expandido e coordenação de escrita

O serviço mantém `/projects/{id}/stories` e seus campos/ordenação por prioridade.
Os mesmos registros UUID são acessíveis por `/items`, com tipos `story`, `epic`,
`task`. `/epics` e `/tasks` são aliases tipados de listagem/criação. Histórias
podem referenciar épicos e tarefas podem referenciar histórias do mesmo projeto.

Campos novos: persona/ação/benefício (obrigatórios com `guided=true`), MoSCoW
opcional `must/should/could/wont`, estimativa decimal string de 0 a 1000000 com
até quatro casas e unidade `points/hours`, responsável UUID, bloqueio e motivo.
A prioridade `high/medium/low` é independente de MoSCoW. Responsável é validado
na API de Projetos ao criar ou alterar a atribuição; autoria nunca é transferida
implicitamente. Edições de status/texto preservam responsáveis removidos ou
desativados. Leituras de itens/quadro expõem `assignee_available`: true quando
elegível, false quando indisponível, null sem responsável ou quando não é possível
confirmar disponibilidade. Essa projeção não grava dados de outra API nem expõe
perfil/email. Falha na confirmação de uma nova atribuição continua negando a escrita.

`PATCH /items/{id}` aceita `expected_version`; divergência retorna 409. Somente
alteração exclusiva de status usa `backlog:update_status`; demais mudanças usam
`backlog:update`. Campos imutáveis e desconhecidos são recusados. Históricos
append-only são gravados na mesma transação, sem criar eventos anteriores para
registros migrados. `GET /items/{id}/history` é paginado.

`GET/POST /items/{id}/dependencies` e `DELETE /items/{id}/dependencies/{target}`
formam um grafo dirigido sem ciclos, referências externas ou autodependência.
Bloqueio é ortogonal aos três status. O quadro expõe dependências não concluídas.

`GET /board` retorna versão e colunas `todo/in_progress/done`; limite de 5000
itens por quadro, sem paginação fictícia. Leitura que detecta alteração concorrente
retorna 409 para atualização do quadro. `POST /items/reorder` exige
`backlog:reorder`, `expected_version` e a lista completa do projeto ou do grupo
`status`/`moscow_priority`. Fragmentos filtrados, duplicatas e versões antigas
retornam 409. Escritas avançam a versão; repetição idempotente de aprovação/evento
não avança. A ordenação nova usa posições canônicas; a ordenação legada de
`/stories` permanece por prioridade.

## Segurança entre serviços

JWT é validado localmente e seu estado é consultado em `GET /auth/me` a cada
requisição, sem cache positivo. `AUTH_API_BASE_URL` padrão 127.0.0.1:8000;
`AUTH_SESSION_CHECK_ENABLED=true` no runtime. `access/v2` de Projetos é obrigatório
por padrão, validando IDs, catálogo, definições de papéis e permissões efetivas.
`PROJECTS_LEGACY_ACCESS_ENABLED=true` é compatibilidade explicitamente optada para
testes isolados/consumidores antigos; não garante políticas novas de ciclo de vida
ou papéis. Nunca há fallback automático de v2 para v1.

Projetos planejados/ativos permitem escrita; suspensos/concluídos/arquivados
recusam mutações antes de consultas ao conteúdo. Cada mutação obtém lease na API
de Projetos antes da transação de escrita; a liberação ocorre após commit/rollback.
Falha de aquisição não grava. Falha de liberação retorna 503 e pode deixar lease
persistida; não há retry silencioso nem expiração automática. Recuperação exige
operador verificar que o escritor terminou e liberar pela API autorizada de
Projetos. Resposta perdida após commit exige reler antes de repetir uma criação.

`GET /content-summary` conta todos os tipos, históricos, recomendações e eventos,
não adquire lease e permanece disponível durante congelamento de exclusão de
Projetos. Ausência de resposta nunca significa backlog vazio. Não há acesso a
banco estrangeiro.

O resumo retorna `stories`, `epics`, `tasks`, `history`, `recommendations`,
`recommendation_events`, `review_events` e `total`, que soma os sete contadores.
`history` conta somente histórico de item; auditoria de recomendações e recibos
de revisão têm contadores próprios. Recomendações pendentes impedem considerar
o projeto vazio. O consumidor valida o total e falha com segurança diante de
contrato incompatível.

## Migração e reversão

Execute explicitamente `backlog-service init` antes de iniciar a nova versão.
O comando cria tabelas faltantes e adiciona colunas, idempotentemente, preservando
IDs, textos, autor, prioridades, status e datas. Legados recebem tipo história,
versão 1, posições estáveis e campos vazios/nulos. Não há conversão inferida para
MoSCoW nem extração de persona de texto. Startup e readiness não executam DDL.

Faça backup antes de migrar. Rollback de código pode manter colunas/tabelas
aditivas, mas a versão antiga só entende histórias: não volte ao escritor antigo
após criar épicos/tarefas sem estratégia explícita de compatibilidade. Não remova
registros novos para simular reversão. Testes usam SQLite e PostgreSQL loopback
descartável; jamais bancos remotos como Neon.
