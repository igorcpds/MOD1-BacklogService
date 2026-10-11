# MOD1 Backlog Service

MVP `0.1.0` de histórias por projeto: registrar necessidades e critérios de aceite,
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

A CLI cria apenas o schema configurado e a tabela de histórias, sem apagar dados.
Ela não gerencia roles. Configure as permissões conforme
[database-neon.md](docs/database-neon.md), depois use a conta runtime na API.
Startup não cria nem migra tabelas.

Para testar sem credenciais Neon, use `DATABASE_URL=sqlite:///./backlog.db` no `.env`
e execute `init`. É uma alternativa de desenvolvimento; testes usam bancos temporários.

## Iniciar

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
reencontre a entrega. Outra conta não acessa as histórias da primeira.
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

Proprietário único por projeto; equipes/RBAC dependem do serviço de projetos.
Sem tarefas, sprints, estimativas, exclusão ou edição do texto das histórias.
PATCH modifica prioridade/status; mesmos valores preservam `updated_at`.
Não há controle otimista: última escrita em um mesmo campo prevalece.
Logout/desativação não revoga imediatamente JWT já emitido nos consumidores.
Docker/deploy não foram validados. [CHANGELOG.md](CHANGELOG.md) registra a versão candidata.
