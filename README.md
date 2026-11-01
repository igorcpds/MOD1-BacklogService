# MOD1 Backlog Service

## Backlog expandido — 0.4.0 preparado para release

Exige Projetos 0.5.0 e Identidade 0.4.0: cada operação valida a sessão online e
consulta `/projects/{id}/access/v2` com o mesmo Bearer. Papéis personalizados e
concessões por equipes participam das permissões. Mutações respeitam o ciclo de
vida e usam leases duráveis. 403 mantém a sessão; revogação e expiração afetam
novas verificações. Migração explícita é necessária antes do novo runtime.
[Contrato de integração](docs/integration.md).

Organização do serviço, dependências e fluxos de autorização:
[arquitetura multicamadas](docs/architecture.md).

Serviço `0.4.0` de histórias por projeto: registrar necessidades e critérios de aceite,
priorizar entregas e acompanhar o progresso. O usuário entra pelo serviço de
identidade e acessa apenas projetos autorizados pelo serviço de projetos.

## Preparar

Requer Python 3.12 e [uv](https://docs.astral.sh/uv/). Na raiz deste checkout:

```powershell
uv sync --locked --python 3.12 --no-install-project
uv sync --locked --no-build-isolation
Copy-Item .env.example .env
```

Em Linux/macOS, use os mesmos comandos `uv` e `cp .env.example .env`.
As ferramentas de build são instaladas primeiro; esse procedimento também funciona
em Windows onde intérpretes temporários do cache são bloqueados.

Configure `.env` com a conexão **runtime** do seu Neon e os endereços das APIs.
PostgreSQL remoto exige `sslmode=verify-full` e `sslrootcert` apontando para um
arquivo de CA confiável. Obtenha o caminho com `.venv/Scripts/python.exe -m certifi`
(Unix: `.venv/bin/python -m certifi`). Prepare schema/tabela com conexão administrativa:

```powershell
.venv/Scripts/python.exe -m backlog_service.cli init
```

A CLI cria/migra apenas o schema configurado e suas tabelas, sem apagar dados.
Ela não gerencia roles. Configure as permissões conforme
[database-neon.md](docs/database-neon.md), depois use a conta runtime na API.
Startup não cria nem migra tabelas.

Para testar sem credenciais Neon, use `DATABASE_URL=sqlite:///./backlog.db` no `.env`
e execute `init`. É uma alternativa de desenvolvimento; testes usam bancos temporários.

## Iniciar

Publicação com Neon e Azure Container Apps: [configuração, imagem e deploy](docs/deploy-azure.md). O workflow de publicação é manual e separado dos checks de PR.

```powershell
.venv/Scripts/python.exe -m uvicorn backlog_service.app:create_app --factory --host 127.0.0.1 --port 8002
```

Em Unix, substitua o executável por `.venv/bin/python`. Prepare também:

| Componente | Repositório | Endereço local |
| --- | --- | --- |
| Identidade/JWKS | [IdentityService](https://github.com/Ckenz0/MOD1-IdentityService) | `http://127.0.0.1:8000` |
| Projetos | [ProjectsServices](https://github.com/briankfreire/MOD1-ProjectsServices) | `http://127.0.0.1:8001` |
| Backlog | Este repositório | `http://127.0.0.1:8002` |
| Interface | [WebFrontend](https://github.com/Ckenz0/MOD1-WebFrontend) | `http://127.0.0.1:5173` |

Todas as APIs precisam permitir a origem exata do frontend em `CORS_ORIGINS`.
Swagger em `http://127.0.0.1:8002/docs`; use o JWT Bearer obtido no login.
Contratos: [integration.md](docs/integration.md).

## Demonstrar valor

Entre → crie/abra um projeto → **Backlog** → descreva uma história e seus critérios
de aceite → defina a prioridade → marque o progresso → reinicie o backlog e
reencontre a entrega. Outra conta só acessa as histórias mediante vínculo ativo e permissão no projeto.
O usuário transforma necessidades em entregas ordenadas e verifica o que concluiu.
Resultados: [verification.md](docs/verification.md).

## Verificar

```powershell
uv lock --check
.venv/Scripts/python.exe -m ruff check src tests
.venv/Scripts/python.exe -m ruff format --check src tests
.venv/Scripts/python.exe -m mypy src/backlog_service
.venv/Scripts/python.exe -m pytest -q
uv build --no-build-isolation
```

O teste PostgreSQL destrutivo exige `TEST_DATABASE_URL` para um banco descartável
em loopback. Sem ele, há um skip explícito; nunca aponte essa variável para Neon.
O teste cria/remove somente um schema sintético aleatório. O smoke no Neon é separado
e não exclui registros ou schemas.

## Limites

Equipes/RBAC e ciclo de vida dependem do serviço de projetos.
Há épicos, tarefas e estimativas; não há sprints ou exclusão de histórias.
PATCH modifica título, descrição, critérios de aceite, prioridade/status;
mesmos valores preservam `updated_at`. Título aparado de 1–120 caracteres,
descrição/critérios de 0–2000; campos extras, null e imutáveis são recusados.
GET stories aceita `q` aparado até 200 caracteres, `status` e `priority` opcionais.
A busca literal ignora maiúsculas/minúsculas em título/descrição e também encontra
UUID exato. `%` e `_` são literais; filtros combinam AND antes de total/paginação.
`/items` e reordenação oferecem controle de versão; o PATCH legado de `/stories`
continua sem `expected_version`. A migração aditiva preserva IDs e dados.
Logout/desativação são observados pela verificação online de sessão, habilitada
por padrão. [CHANGELOG.md](CHANGELOG.md) registra a release preparada; esta
documentação não comprova publicação ou deploy.

## Contratos do backlog expandido

A implementação local mantém `/stories` e acrescenta itens tipados, épicos,
tarefas, histórico, dependências, quadro e reordenação versionada. Identidade
online e autorização Projects access/v2 são exigidas por padrão; mutações usam
leases duráveis de Projetos. Execute `backlog-service init` explicitamente para
migrações aditivas antes do novo runtime; startup não faz DDL.

Contratos e limites: [itens e migração](docs/backlog-items.md),
[recomendações aprovadas por pessoas](docs/recommendations.md) e
[proposta local de eventos de revisão](docs/code-review-proposal.md).
IA real e eventos de revisão permanecem desabilitados. O adaptador de revisão
depende de contrato explícito com o produtor antes de qualquer habilitação.
Provider real de IA e integração do produtor externo permanecem com validação
pendente; transportes sintéticos locais não são evidência de integração externa.
