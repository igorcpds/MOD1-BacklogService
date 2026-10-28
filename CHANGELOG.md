# Changelog

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
