# Backlog na Azure

O backlog roda em Container Apps Consumption, separado de identidade e projetos, mantendo persistência no Neon. Use o [passo a passo completo](https://github.com/Ckenz0/MOD1-IdentityService/blob/main/docs/deploy-azure.md) para a infraestrutura compartilhada e a ordem de implantação.

## Parâmetros deste serviço

| Configuração | Valor |
| --- | --- |
| Imagem | REGISTRY.azurecr.io/backlog@sha256:DIGEST |
| Processo | backlog_service.app:create_app, factory, 0.0.0.0:8002 |
| Recursos iniciais | 0,25 vCPU/0,5 GiB; zero a uma réplica; validar capacidade real |
| Schema Neon | backlog |
| Segredo versionado | backlog-database-url |
| JWT_ISSUER | URL HTTPS estável da identidade |
| JWT_AUDIENCE | engenharia-software-api |
| JWKS_URL | URL da identidade + /.well-known/jwks.json |
| PROJECTS_API_BASE_URL | URL HTTPS estável de projetos |
| CORS_ORIGINS | Array JSON com a origem HTTPS estável do frontend |

O runtime recebe USAGE e SELECT/INSERT/UPDATE em suas tabelas, sem acesso aos schemas dos outros serviços. Prepare tabelas/permissões administrativamente conforme [database-neon.md](database-neon.md), sem executar DDL no startup. O DSN usa `verify-full` e `sslrootcert=/etc/ssl/certs/ca-certificates.crt`. O Dockerfile já exige o bundle de CAs na imagem.

## Publicação

1. Entregue a branch do MVP/deploy pelo fluxo normal de revisão e integração em main.
2. Em Settings → Environments → demo, configure `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_RESOURCE_GROUP`, `ACR_NAME` e `AZURE_CONTAINER_APP=PREFIX-backlog`.
3. Configure OIDC do repositório para esse Environment. A identidade de CI usa AcrPush e atualização do app; a identidade runtime usa AcrPull e leitura somente de backlog-database-url.
4. Rode Publish API to Azure em main com `deploy_revision` desmarcado para a primeira imagem. O job executa lint, tipos, testes, auditoria de dependências, build e smoke com banco sintético antes do push.
5. Passe o digest ao `apps.bicep` de identidade, junto aos segredos versionados e demais imagens.
6. Depois da primeira implantação, cada push/merge em `main` executa as verificações e atualiza automaticamente o app existente. A execução manual continua disponível, com `deploy_revision=true` por padrão; desmarque somente para publicar uma imagem sem atualizar o app. O workflow espera a revisão nova ficar pronta. Registre e mantenha o digest da infraestrutura sincronizado com o novo release.

## CI/CD da atividade P8

O [workflow de PRs](https://github.com/igorcpds/MOD1-BacklogService/actions/workflows/container-check.yml) executa as verificações sem credenciais Azure. O [workflow de publicação](https://github.com/igorcpds/MOD1-BacklogService/actions/workflows/azure-deploy.yml) executa lint → testes → auditoria de dependências → build/smoke → publicação no ACR e deploy no Azure automaticamente em cada push/merge em `main`. Para comprovar a automação, abra uma execução bem-sucedida cujo evento seja `push`.

O [Dependabot](../.github/dependabot.yml) verifica semanalmente dependências Python (`uv`, incluindo `uv.lock`) e GitHub Actions e abre PRs sujeitos ao CI, sem merge automático. O `pip-audit` também verifica as dependências fixadas no lock, incluindo desenvolvimento, usando export com hashes. Vulnerabilidades conhecidas ou falhas na coleta interrompem o workflow antes da publicação. Referências: [uv com Dependabot](https://docs.astral.sh/uv/guides/integration/dependabot/) e [pip-audit](https://github.com/pypa/pip-audit).

O backlog continua confirmando acesso ao projeto pela API de projetos com o Bearer recebido. Falhas de banco/JWKS/projetos retornam indisponibilidade, sem conceder acesso por omissão. O frontend prepara dependências que estavam suspensas por GET; POST/PATCH não são repetidos automaticamente.

Valide histórias, critérios, prioridade/status, isolamento entre duas contas, persistência após reinício e retomada depois de zero réplicas. Não execute o teste PostgreSQL destrutivo contra Neon; ele continua reservado a loopback descartável. Documente somente evidências sanitizadas e os metadados públicos da revisão. Docker/deploy só estão validados quando os jobs e o smoke real do ambiente passarem.
