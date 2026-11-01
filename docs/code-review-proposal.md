# Proposta local de eventos de revisão de código

Este é um adaptador preparado e testado localmente. O contrato do produtor de
outro grupo ainda não foi recebido/acordado; a integração real de US-096 permanece
pendente. Não se presume que aprovação de review signifique merge ou conclusão.
Nenhuma chamada é enviada a outro grupo por este serviço.

## Configuração e autenticação

Padrão desabilitado (`CODE_REVIEW_ENABLED=false`). Habilitar requer, no backend:

- `CODE_REVIEW_ENABLED=true`.
- `CODE_REVIEW_KEY`: segredo dedicado de 32 a 512 caracteres, fora do frontend.
- `CODE_REVIEW_PROJECT_IDS`: lista JSON de UUIDs autorizados para esse principal.
- `CODE_REVIEW_EVENT_MAPPING`: objeto JSON de nomes de evento acordados para
  `todo`, `in_progress` ou `done`. Não existe mapeamento padrão.

A rota proposta é `POST /projects/{project_id}/code-review/events`. São obrigatórios
`X-Code-Review-Key` e `Authorization: Bearer <token atual do ator>`. A chave
identifica o principal de integração `code-review`, limitado pela lista de
projetos; ela não concede os direitos do usuário. O Bearer é validado localmente,
consultado na Identidade e autorizado por Projetos a cada requisição. O ator
precisa de `backlog:update_status`. Não há chave/Bearer delegado persistido, logado
ou enviado ao navegador. O header de integração não é liberado no CORS do produto.

Sem configuração completa ou sem mapeamento do tipo recebido: 503, sem escrita.
Chave ausente/incorreta/duplicada ou Bearer inválido: 401. Projeto fora do escopo,
ID do corpo divergente do caminho ou permissão insuficiente: 403. Essas decisões
não consultam o item. Ausência de item autorizado usa o 404 genérico do serviço.

## Envelope versionado proposto

```json
{
  "schema_version": 1,
  "event_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "project_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "item_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  "event_type": "nome_previamente_acordado",
  "occurred_at": "2026-10-31T12:00:00Z",
  "expected_item_version": 3
}
```

UUIDs são obrigatórios; versão de schema é o inteiro 1; versão do item é inteiro
positivo. Timestamp exige fuso e é normalizado para UTC; não aceita mais de cinco
minutos no futuro. Tipo tem até 80 caracteres `a-z/A-Z/0-9/_.:-`. Campos extras e
valores de tipo incompatível retornam 422 sanitizado. O corpo não aceita texto de
item, senha, override administrativo, identidade arbitrária de principal ou
transição livre de status.

## Concorrência e auditoria

A operação obtém lease de escrita em Projetos antes da primeira escrita local,
serializa alterações do projeto e grava status, versão, histórico e recibo numa
única transação. Libera a lease somente após commit/rollback. Estados de projeto
suspenso/concluído/arquivado impedem a alteração.

`event_id` é único por projeto. A representação normalizada do envelope recebe
hash SHA-256: repetição idêntica retorna o recibo original, sem nova versão,
histórico ou mudança do quadro. Reutilização do ID com outro corpo retorna 409.
Eventos distintos devem ter `occurred_at` estritamente crescente por item;
empate/evento antigo retorna 409. `expected_item_version` divergente também retorna
409, protegendo edições manuais ou outra integração que ocorreram antes do evento.
Não há retry/reordenação silenciosa de eventos recusados.

Recibo contém `event_id`, `project_id`, `item_id`, `item_version`, `status` e
`applied_at`. Ele descreve a aplicação original daquele evento; uma leitura do
item confirma o estado atual após outras mudanças. Histórico registra ator humano,
principal de integração, ID/tipo do evento e diff de status. Recibos aceitos e
históricos são conteúdo relevante para exclusão segura. Requisições recusadas não
criam recibos de sucesso nem alteram itens.

Execute explicitamente `backlog-service init` para a tabela aditiva de recibos.
Startup não altera schema. Testes usam chaves/atores sintéticos, HTTP controlado,
SQLite e PostgreSQL loopback descartável; isso não comprova compatibilidade com o
produtor real ou funcionamento de sua autenticação/transporte.
