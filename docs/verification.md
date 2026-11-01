# Validação do backlog

## Itens, recomendações e proposta de revisão — 31/10/2026, somente local

- `uv run pytest -q --tb=short` com PostgreSQL descartável loopback, schemas aleatórios
  e guarda contra remoto: **262 testes passaram, nenhum skip**, em 58,42 s.
- `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `uv run mypy` (24 módulos), `uv lock --check` e `uv build`: aprovados.
- RED/GREEN: tipos/campos novos, migração de tabela antiga, validação online de
  Identidade/access-v2, proposta/aprovação e provedor desabilitado, ingresso de
  revisão ausente, replay alterando quadro, responsável indisponível bloqueando
  status e leitura concorrente de quadro expondo versão incoerente.
- SQLite e PostgreSQL usam dados/atores sintéticos. PostgreSQL adicional cobre
  migração idempotente de história antiga, DAG, reorder, aprovação de proposta e
  replay concorrente do mesmo evento. SQLite cobre conflitos concorrentes de
  versão/reorder/aprovação, rollback de recibo e autorização antes de SQL.
- HTTP controlado verifica mesmo Bearer, consulta online sem cache positivo,
  leases antes da escrita/liberação após commit ou rollback, perda de elegibilidade
  do responsável e metadados true/false/null sem dados de perfil.
- Ingresso proposto exige chave dedicada + Bearer atual + escopo por projeto;
  sem configuração/mapeamento retorna 503. Eventos antigos/conflitantes retornam
  409 e replay idêntico não duplica versão, histórico, recibo ou efeito no quadro.
- Verificados UTF-8 da documentação, `git diff --check`, exclusão de artefatos
  privados dos arquivos rastreados e dos pacotes wheel/sdist.
- Permanece um aviso preexistente de depreciação Starlette/HTTPX.

Não houve chamadas a LLM real, SMTP, produtor de revisão ou produção. Integração
externa de IA/revisão permanece pendente; testes HTTP controlados não a comprovam.
Validação entre os quatro serviços e frontend é uma etapa separada da integração.
As alterações novas desta rodada aguardam revisão local antes de commit; o commit
anterior de itens é `3d80553a84898229ca6ac1d16e7f494bf4c3a3f1`, com coautoria Igor.

## Arquitetura multicamadas — 30/10/2026, somente local

- Baseline com Python 3.12.15 e SQLite sintético: **193 testes passaram, 1 skip**
  de PostgreSQL descartável não configurado; Ruff check/formato, mypy e build aprovados.
- RED antes da refatoração: teste de dependências detectou imports de SQLAlchemy,
  modelo ORM, repositório e mecanismos de integração/segurança em `routes.py`.
  A versão final percorre AST, inclusive imports locais, relativos e por pacote.
- GREEN: **205 testes passaram, 1 skip**, em 44,59 s. O aviso já existente de
  depreciação HTTPX/Starlette continua; nenhum novo aviso foi observado.
- Novos testes de aplicação observam SQL real para negar criação, listagem,
  detalhe e PATCH antes de acesso ao banco. Cobrem status isolado do desenvolvedor
  e rejeição de status combinado com texto. Remover temporariamente os checks de
  permissão provocou **7 falhas esperadas**; restaurá-los recuperou o GREEN.
- Testes HTTP adicionais exercitam timeout e contrato inválido de Projetos em
  todas as operações, com 503 sanitizado e nenhum SQL. A cobertura existente
  mantém 401/403/404, Bearer, revogação, downgrade, JWT/JWKS, CORS e readiness.
- Ruff check/formato, mypy, lock e wheel/sdist aprovados. A documentação de
  [arquitetura](architecture.md) acompanha o pacote fonte; artefatos privados
  continuam ignorados e excluídos dos pacotes.
- A interface Python interna de `StoriesService` recebe `ProjectContext` em vez
  de UUIDs soltos para que a autorização também ocorra fora das rotas. Os testes
  internos foram adaptados; endpoints, payloads, status e schema permanecem iguais.

Não foram executados PostgreSQL, Docker, deploy ou integração entre quatro
repositórios nesta rodada isolada do Backlog. Nenhum banco remoto foi acessado;
nenhum push, merge ou mudança de configuração publicada foi realizado. SQLite
não substitui a conferência de locale/Unicode e transações no PostgreSQL.

## Colaboração/perfil 0.3.0 — 28/10/2026, somente local

- Suíte completa com PostgreSQL 16.15 descartável em loopback, UTF-8/ICU und:
  **194 testes passaram, nenhum skip**, em 55,32 s.
- Ruff check/formato, mypy, lock e wheel/sdist verificados no candidato.
- Frontend 0.4.0: **96 testes passaram sem skips**, com três APIs reais e bancos/chaves
  temporários. Teste ampliado de duas contas também passou: convite, perfil,
  Desenvolvedor/status, promoção a PO e remoção/reutilização negada do código.
- Revisão própria de isolamento, contratos, expiração e concorrência. A revisão
  independente deste lote ficou indisponível por limite de uso dos auxiliares;
  a revisão independente histórica abaixo cobre somente o lote anterior.
- PostgreSQL encerrado e dados temporários removidos. Sem main/push/deploy/tag,
  sem acesso ao Neon ou alteração de grants/configuração remota.

## Conferência integrada concluída — 28/10/2026

- Suíte completa com PostgreSQL 16.15 **ICU/und e UTF-8** descartável em loopback:
  **149 passaram, nenhum skip**, em 51,19 s. Um aviso de depreciação HTTPX já
  existente não representa falha de teste.
- A rodada anterior com locale libc `C` teve **148 aprovados e uma falha** na busca
  ÁRVORE/árvore: esse locale converte somente ASCII. Os testes de acentos foram
  mantidos; a configuração Unicode suportada passou. Esta é uma condição do
  ambiente que deve ser conferida antes de publicar, documentada em
  [database-neon.md](database-neon.md) e [integration.md](integration.md).
- Frontend 0.3.0: **85 testes aprovados sem skips**, incluindo edição, filtros,
  persistência após reinício e isolamento com três APIs reais e SQLite temporário.
- Revisão independente dos backends sem achados críticos/importantes. A interface
  preserva rascunhos se atualizar a lista falhar, com regressão RED→GREEN.
- Banco temporário encerrado/removido. Nenhum acesso ao Neon, grant, deploy ou
  alteração de main. As consultas de diagnóstico de locale documentadas não foram
  executadas contra o ambiente publicado.

## Refinamento 0.2.0 — 28/10/2026, local

Worktree `us-backlog-refinement`, branch `feat/us-backlog-refinement`, Python 3.12.13
no Windows. Instalação `uv sync --locked --python 3.12 --no-install-project` e
`uv sync --locked --no-build-isolation`, sem configuração remota ou mudança de schema.

- Baseline: 118 testes aprovados, 1 skip de PostgreSQL.
- RED: PATCH de texto rejeitado e filtros ausentes confirmados em testes de serviço/HTTP.
- GREEN: 148 testes aprovados, 1 skip de PostgreSQL; aviso de depreciação HTTPX já existente.
- Ruff check/format, mypy e `uv lock --check` aprovados.
- `uv build --no-build-isolation`: wheel/sdist `0.2.0` construídos.
- Cobertos textos literais/Unicode, limites, imutáveis, no-op, UUID, busca literal,
  filtros AND antes de total/paginação e negação de acesso antes do banco.
- Cada chamada protegida continua confirmando GET Projects com o mesmo Bearer.

O teste PostgreSQL foi ampliado para texto, busca e filtros, mas ainda depende de
`TEST_DATABASE_URL` loopback descartável. Integração do frontend, revisão independente
e execução PostgreSQL são conferências separadas. Nenhum deploy, push, tag ou release.

## Histórico do MVP 0.1.0 — 11/10/2026

Versão candidata `0.1.0`; frontend integrado `0.2.0`. Resultados observados no Windows,
Python 3.12.15. Este recorte pode ser demonstrado localmente.

| Verificação | Resultado |
| --- | --- |
| Backend: pytest | 118 aprovados, 1 skip PostgreSQL local opt-in |
| Ruff, formatação, mypy, lock | Aprovados |
| Wheel/sdist reais | Construídos; arquivos privados excluídos em regressão |
| Frontend com três backends temporários | 63 testes aprovados, sem skips |
| Cadastro → projeto → histórias → prioridade/status | API real e navegador aprovados |
| Reinício do backlog | Dados recuperados na integração SQLite e no Neon |
| Outra conta/projeto errado | 404; todas as rotas protegidas; sem token: 401 |
| Neon | TLS verify-full, schema próprio e runtime limitado confirmados |
| Desktop claro / celular escuro | Capturas sintéticas; teclado, literal HTML, Unicode e largura 390 verificados |

O teste PostgreSQL destrutivo não executou: `TEST_DATABASE_URL` loopback não estava
configurado e o daemon Docker estava indisponível. Isso não impede o smoke separado
no Neon, que confirmou criação/atualização/leitura e persistência após reinício sem
excluir registros/schemas. Não há comprovação de Docker, deploy ou pipeline.

As fixtures de integração usam bancos SQLite, RSA e contas temporárias, em portas
livres; não usam o `.env` do desenvolvedor. A suíte sanitiza erros e verifica negação
antes do acesso ao banco, cache JWKS/rotação/falhas, paginação, timestamp de no-op,
campos imutáveis, limites de texto e exclusão de arquivos privados dos pacotes.
Há um aviso de depreciação do adaptador HTTPX no TestClient; não é falha de teste.

Instalação reproduzida em quatro árvores novas contendo somente arquivos públicos,
sem `.env`, chaves, bancos, instruções locais ou planos. Identidade/projetos/backlog
instalaram seus pacotes em ambientes Python 3.12 novos; o backlog repetiu análise
estática, 118 testes aprovados/um skip e build wheel/sdist nesse ambiente.

A revisão final corrigiu a diferença entre os espaços Unicode aceitos pelo
backend e pelo formulário. O frontend também preserva a confirmação de criação
ou atualização quando a consulta seguinte retorna 401 e encerra a sessão.
Esses casos têm testes de regressão; histórias antigas com espaços adicionais
continuam legíveis, sem alteração dos registros existentes.

## Reproduzir

Siga [README.md](../README.md) e execute os comandos de verificação.
No frontend, configure os três caminhos de backend conforme o README dele e rode
`python -m unittest discover -s tests -v`. Sem os caminhos, há skips explícitos.
Capturas e roteiro estão no [frontend](https://github.com/Ckenz0/MOD1-WebFrontend).

## Roteiro de apresentação

Crie uma conta → projeto → duas histórias com critérios de aceite → dê prioridade
alta à entrega principal → marque em andamento/concluída → reinicie o backlog →
reencontre o progresso → tente outra conta. Mostre o ganho: necessidades verificáveis,
prioridades claras e progresso persistente, com acesso restrito.

Equipes/RBAC, tarefas/sprints, estimativas e edição/exclusão de textos não fazem parte
deste MVP. JWT já emitido pode continuar válido até expirar após desativação/logout.
Readiness comprova só a tabela própria. Essas limitações acompanham a demonstração.

## Integração coordenada das camadas — 30/10/2026

- Revisão independente das mudanças de Identidade, Projetos, Backlog e Frontend
  não encontrou regressão funcional ou de segurança nos caminhos inspecionados.
  A lacuna de testes sem DOM do frontend foi corrigida com Worker e verificação
  negativa das fronteiras; a suíte final de navegador passou 124 testes sem skips.
- A suíte usa os três backends reais refatorados, SQLite/RSA temporários e os
  caminhos AUTH_BACKEND_PATH, PROJECTS_BACKEND_PATH e BACKLOG_BACKEND_PATH.
  Inclui login, perfil, projetos, backlog, convite, promoção de papel e remoção.
- O teste HTTP específico Projetos→Backlog passou com BACKLOG_SERVICE_PATH
  configurado. Não se presume teste de PostgreSQL a partir desse resultado.
- O ambiente local persistente foi reiniciado com os mesmos bancos e chave:
  readiness 200 nas três APIs, CORS 127.0.0.1:5173, login da conta de teste
  preservada e consulta de projetos 200 pelo navegador, sem erro JavaScript.
- Nenhum banco remoto, grant, configuração Azure, deploy ou dado de produção
  foi alterado. A integração PostgreSQL opt-in continua pendente nesta etapa.
- Componentes e limites das camadas estão em [architecture.md](architecture.md).
