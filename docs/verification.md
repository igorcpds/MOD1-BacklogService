# Validação do backlog

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
