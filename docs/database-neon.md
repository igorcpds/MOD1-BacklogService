# Banco do backlog

Schema `backlog`, tabela `backlog.stories`, conta `mod1_backlog_runtime`.
Projeto/autor são referências lógicas, validadas pelas APIs; sem FK entre módulos.

## Preparação administrativa

Use conexão direta administrativa com TLS `verify-full` e CA confiável;
execute `python -m backlog_service.cli init` para o schema `backlog`.
Crie uma senha forte própria para runtime por mecanismo privado e configure:

```sql
CREATE ROLE mod1_backlog_runtime LOGIN NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOINHERIT NOBYPASSRLS;
REVOKE ALL ON SCHEMA backlog FROM PUBLIC;
REVOKE ALL ON TABLE backlog.stories FROM PUBLIC;
GRANT USAGE ON SCHEMA backlog TO mod1_backlog_runtime;
GRANT SELECT, INSERT, UPDATE ON backlog.stories TO mod1_backlog_runtime;
```

Confira objetos e roles existentes antes de executar. Não substitua credenciais,
owners ou dados desconhecidos. Não conceda CREATE/DELETE, propriedade do schema,
membership ou acesso aos schemas de identidade/projetos. Use runtime no `.env`
da API; schema/tabela já devem existir. A CLI não gerencia roles nem migra estruturas.

Conectado como runtime, confira:

```sql
SELECT has_schema_privilege(current_user, 'backlog', 'USAGE'),
       has_schema_privilege(current_user, 'backlog', 'CREATE'),
       has_table_privilege(current_user, 'backlog.stories', 'SELECT'),
       has_table_privilege(current_user, 'backlog.stories', 'INSERT'),
       has_table_privilege(current_user, 'backlog.stories', 'UPDATE'),
       has_table_privilege(current_user, 'backlog.stories', 'DELETE');
```

Esperado: `true, false, true, true, true, false`. Confira ausência de USAGE em
`mod1_identity`/`projects` e atributos superuser/createdb/createrole/bypassrls.
Acessos concedidos por PUBLIC/membership também precisam ser considerados.

Na instância de desenvolvimento, TLS/permissões e gravação foram conferidos.
Credenciais, scripts e IDs das provas permanecem locais. O teste destrutivo
PostgreSQL opt-in é reservado a loopback; o smoke no Neon não exclui dados/schemas.
