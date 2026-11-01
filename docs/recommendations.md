# Recomendações de backlog com aprovação humana

`POST /projects/{id}/recommendations` recebe `{kind:"initial_backlog",constraints?:{}}`
e cria uma recomendação pendente. GET da coleção é paginado e GET por UUID retorna
o rascunho. `/approve` e `/reject` recebem `{expected_version:1}`. As rotas exigem
acesso atual ao projeto; geração/decisão usam `backlog:create`, leituras usam
`backlog:read`. Estados são pending/approved/rejected/expired, com versões.

A fonte é `GET /projects/{id}` autorizado com o mesmo Bearer, incluindo descrição,
escopo e requisitos reais, junto aos IDs/versões/títulos dos itens atuais. Não há
consulta a schemas estrangeiros ou resumo recursivo. Limite de contexto: 64 KiB;
restrições fornecidas pelo usuário: 4 KiB. Não são enviados perfis/custos/pessoas.
Evidências são caminhos conhecidos `project.description`, outros campos de projeto
fornecidos ou `items.UUID` autorizados. IDs inventados e referências a responsáveis,
épicos ou histórias externas são recusados nas sugestões iniciais.

O rascunho expõe modelo/provedor, `simulated`, justificativa, evidências,
`context_version` e até 50 sugestões estritamente validadas. Cada sugestão segue
os limites de uma história; não pode criar tarefas/épicos implicitamente.
Aprovação reconsulta a fonte, compara hash/versões e permissões, obtém lease de
Projetos e cria todas as histórias em uma única transação com histórico e auditoria
da decisão. Repetição da mesma aprovação retorna o resultado sem duplicar itens.
Mudança de fonte torna o rascunho expirado e retorna 409; rejeição não cria itens.
Rascunhos e eventos contam como conteúdo relevante no protocolo de exclusão.

## Adaptador proposto de IA

Padrão desabilitado: configure `AI_BASE_URL` e `AI_MODEL` apenas no backend para
habilitar. `AI_API_KEY` opcional vai somente no header Bearer para o provedor;
nunca é emitida pela API do produto. Base HTTPS confiável ou HTTP loopback;
sem redirects ou retry automático. `AI_TIMEOUT_SECONDS=30` (1–60), resposta
máxima 256 KiB. Erros preservam o trabalho e retornam 503, sem sucesso fictício.

Contrato genérico configurável:

```json
POST {AI_BASE_URL}/generate
{"schema_version":1,"kind":"initial_backlog","model":"configured-model","context":{}}
```

Resposta esperada:

```json
{"summary":"Resumo","justification":"Justificativa","evidence":["project.description"],"suggestions":[{"title":"História proposta","description":"Descrição"}]}
```

Campos desconhecidos, limites excessivos e sugestões inválidas são recusados.
`AI_SIMULATED=true` só é permitido com URL loopback e o resultado é identificado
como simulado. Os testes usam transporte HTTP controlado/saída sintética, não
um LLM real. Provider de produção e qualidade de recomendações continuam com
validação externa pendente; testes locais não substituem essa etapa.

Execute `backlog-service init` explicitamente para criar tabelas de recomendações
e eventos antes do novo runtime. O comando é idempotente; startup não migra.
