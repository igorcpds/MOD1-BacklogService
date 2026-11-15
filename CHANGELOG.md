# Changelog

## 0.5.0 — 2026-11-15

Publicada em produção. [Commit, deploy e evidências](docs/final-delivery.md).
Entradas anteriores preservam o estado histórico de suas próprias datas.

- Atualiza opentelemetry-api para 1.45.2 no lock, corrigindo GHSA-mf5v-w3w3-f6cg.
- Captura transacional de eventos confirmados em fila externa persistente, com o UUID do histórico/evento e schema exclusivo.
- Worker optativo com consulta de estado, lotes limitados, prazo total de envio, leases e recuperação conservadora de resultados incertos.
- Chave somente no backend, sem encaminhar Bearer; ativação e migração explícitas. Publicação por pipeline incremental; ativação externa segue os limites documentados.
- Contrato, catálogo de eventos e operação em [notificações do Módulo 6](docs/module6-notifications.md).

### Gemini

- Adaptador Gemini REST na infraestrutura, selecionado explicitamente por `AI_PROVIDER=gemini`. O provedor HTTP estruturado continua padrão; sem configuração, geração fica desabilitada.
- Geração de backlog inicial com JSON estruturado tipado, contexto autorizado de até 64 KiB, resposta de até 256 KiB e metadados `provider=gemini`, modelo configurado e `simulated=false`.
- Validação estrita da saída Gemini conforme o schema anunciado, incluindo campos obrigatórios, tipos, enums, limites e rejeição de propriedades extras. Estimativas e bloqueios fora desse contrato retornam 503 sem persistência; o provedor HTTP genérico mantém seu contrato existente.
- Validação de endpoint oficial HTTPS ou HTTP loopback para testes, chave somente no backend e erros sanitizados. Sem redirects, retries, ferramentas ou fallback de modelo.
- Propostas sem sugestões podem ser consultadas e rejeitadas; aprovação retorna 409 sem criar itens ou alterar a proposta. Aprovação de histórias preserva transação, idempotência e revalidação de contexto.
- Candidato MINOR pré-1.0 para nova integração e evolução aditiva do contrato de propostas. Chamadas reais do adaptador foram verificadas; disponibilidade, quota e qualidade devem ser observadas por cenário. Veja [configuração e validação](docs/gemini.md).

## 0.4.0 — preparação de release, 2026-11-01

### Added

- Itens tipados, épicos e tarefas com hierarquia, histórias guiadas, MoSCoW, estimativas e responsáveis validados em Projetos.
- Histórico transacional, dependências sem ciclos, bloqueios, quadro e reordenação com controle de versão.
- Recomendações com contexto autorizado e aprovação humana transacional/idempotente. IA real permanece desabilitada; testes sintéticos não validam provedor externo.
- Adaptador proposto de eventos de revisão com autenticação e idempotência, desabilitado por padrão. Contrato do produtor externo continua pendente; não há compatibilidade real presumida.

### Changed

- Arquitetura multicamadas, schema exclusivo, sessão online na Identidade, autorização Projetos `/access/v2` por padrão e leases antes de cada escrita.
- Ciclo de vida de Projetos bloqueia mutações; resumo de todo conteúdo próprio participa da exclusão segura, incluindo recomendações e eventos.
- `/stories` preservado; novas escritas avançam versões e registram histórico. Compatibilidade v1 é opt-in explícito, sem fallback automático. Requer Projetos 0.5.0 e Identidade 0.4.0 com sessão online.
- Migração aditiva explícita por `init`, sem DDL no startup e sem apagar dados. Veja [contrato atual](docs/integration.md) e [migração/rollback](docs/backlog-items.md).
- Evolução MINOR pré-1.0 por novas funcionalidades e mudanças de contrato. A preparação não comprova publicação, deploy ou integração externa.

## Unreleased — 0.3.0

- Autorização canônica por `/projects/{id}/access`, com IDs, papéis e permissões coerentes.
- Permissões distintas para consultar, criar, refinar e atualizar somente status; negado antes de consultar histórias.
- Revogação/expiração verificadas em cada operação; 403 separado de 401/404/503.
- Requer Projetos 0.4.0, sem fallback para contrato antigo de proprietário; sem alteração de schema.

Versão candidata SemVer: `0.3.0`, definida em `pyproject.toml`. Sem tag/release nesta etapa.

## Unreleased — 0.2.0

- PATCH de título, descrição e critérios de aceite, preservando imutáveis e timestamp em no-op.
- Busca literal por título/descrição ou UUID, filtros de status/prioridade antes de total/paginação.
- Busca Unicode no SQLite local e PostgreSQL; `%` e `_` tratados como texto literal.
- Acesso continua confirmado na API de projetos em cada operação com o mesmo Bearer.
- Nenhuma alteração de schema; verificações locais, sem publicação.

## Unreleased — 0.1.0

- Dockerfile sem privilégios, checks de container e workflow manual Azure/OIDC por digest, com documentação Neon e rollback.

- Histórias persistentes, descrição, critérios de aceite, prioridades e progresso.
- Criação, consulta, paginação e atualização de prioridade/status.
- JWT RS256/JWKS e confirmação de acesso pela API de projetos a cada operação.
- Schema próprio, CLI de preparação, TLS verificado e conta runtime limitada no Neon.
- Health, CORS, erros sanitizados e respostas protegidas sem cache.
- Testes de domínio, segurança, HTTP, distribuição e PostgreSQL opt-in.
- Instalação reproduzível e evidências do fluxo integrado.
- Normalização de espaços Unicode no título alinhada ao formulário do frontend.
