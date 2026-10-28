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

Na instância de desenvolvimento, TLS/permissões e gravação foram conferidos
no MVP anterior. Credenciais, scripts e IDs das provas permanecem locais.
O teste destrutivo PostgreSQL opt-in é reservado a loopback; o smoke no Neon
não exclui dados/schemas.

## Busca Unicode

A busca usa `lower` nas colunas e conversão Unicode `str.lower` do Python no
termo recebido. Configure PostgreSQL UTF-8 com locale/collation compatível com
essa conversão para os idiomas usados. `UTF8` com libc `C`/`POSIX` ainda limita
a conversão de caixa a ASCII: `ÁRVORE` não passa a `árvore`, causando ausência
de resultados para esse termo. Locales com regras próprias de idioma, como
turco, também podem divergir do termo normalizado pelo Python.

Para conferir a configuração atual e um caso de português, estas consultas são
somente leitura e não acessam dados de histórias:

```sql
SELECT current_database() AS database_name,
       current_setting('server_encoding') AS server_encoding,
       current_setting('lc_collate') AS lc_collate,
       current_setting('lc_ctype') AS lc_ctype;

SELECT to_jsonb(d)->>'datlocprovider' AS locale_provider,
       COALESCE(to_jsonb(d)->>'datlocale',
                to_jsonb(d)->>'daticulocale') AS provider_locale
FROM pg_catalog.pg_database AS d
WHERE d.datname = current_database();

SELECT lower('ÁRVORE') AS normalized,
       lower('ÁRVORE') = 'árvore' AS portuguese_lower_ok;
```

Espere `UTF8`, `normalized = árvore` e `portuguese_lower_ok = true`.
O probe cobre esse caso de português; valide também os idiomas da aplicação.
No catálogo, `i` identifica ICU e `c` identifica libc. Em um banco ICU,
`lc_ctype` sozinho não descreve o comportamento do provedor; confira também
`locale_provider`/`provider_locale`. As chaves JSON acomodam a mudança de nome
do campo de locale entre versões do PostgreSQL.

Para testes em cluster local novo e descartável, ICU `und` é uma referência
quando o PostgreSQL foi compilado com suporte ICU. Não altere um banco existente
automaticamente para satisfazer o teste. A API não aplica `COLLATE` fixo,
não migra collations e não executa DDL no startup. O runtime precisa apenas
das permissões já descritas. Nenhuma configuração do Neon foi consultada ou
alterada para esta verificação local.

Referências: [locale e conversão de caixa no PostgreSQL 16](https://www.postgresql.org/docs/16/locale.html),
[collations e provedores](https://www.postgresql.org/docs/16/collation.html) e
[`lower`](https://www.postgresql.org/docs/16/functions-string.html).
Campos do catálogo: [PostgreSQL 16](https://www.postgresql.org/docs/16/catalog-pg-database.html)
e [PostgreSQL 17](https://www.postgresql.org/docs/17/catalog-pg-database.html).
