# Backlog 0.6.0 — Code Review, 16/11/2026

O Módulo 4 está integrado pela aplicação, com histórico por item e mudança de
status aprovada. A US096 compõe agora as 100 US implementadas do Módulo 1.
[Matriz e limites](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/backlog-status.md).
O segredo Basic fica no servidor; o contrato antigo de eventos continua
desabilitado. [Contrato e operação](module4-client.md).

## Aceite do Módulo 4 — 16/11/2026

A regra aprovada foi implementada e validada: uma análise válida inicia somente
itens a fazer; trabalho em andamento/concluído permanece como está e conclusão
é manual. Os registros são restritos ao projeto/item, persistidos antes do POST
e recuperáveis após reinício. Repetir o UUID com conteúdo igual não chama o
provedor; conteúdo diferente conflita. Falhas, versão ou acesso alterados não
concluem itens nem provocam retry automático. O ingresso legado de eventos
permanece desabilitado e separado da API síncrona real do Módulo 4.

- Backlog: **491 testes aprovados**, incluindo migração aditiva e concorrência
  em PostgreSQL descartável local. Ruff, formato e mypy passaram.
- Frontend: **187 testes executados, 185 aprovados e 2 opt-ins ignorados**,
  usando as três APIs temporárias. Os ignorados são Resend/Gemini reais, já
  validados na entrega anterior e não repetidos por esta alteração.
- O aceite controlado de navegador exercitou sucesso, Basic dedicado, texto
  seguro, replay, reinício e resposta incerta sem alteração do item. A revisão
  independente encontrou e acompanhou as correções de recuperação após 409,
  avisos entre páginas e indisponibilidade JWKS; não restaram achados materiais.
- Uma rodada de aceite com o serviço M4 real passou: análise estática de código
  fictício, **HTTP201**, um POST nessa rodada, transição `todo→in_progress`,
  persistência após reinício e replay sem segundo POST. IA não foi solicitada;
  não se infere que testes do código foram executados. O resultado informou
  `testes_executados=false`. Não houve comentário em PR nem criação/alteração de
  entidade de negócio de produção por esse teste.
- O segredo Basic é exclusivo da API do Backlog. O patch de publicação preserva
  CORS, JWT, Gemini e M6 e não repassa essa senha ao worker de notificações.
  A tabela própria foi preparada de forma aditiva, após backup validado,
  com SELECT/INSERT/UPDATE para runtime e sem acesso a outros schemas.

O histórico global do provedor não é disponibilizado aos usuários do módulo.
Respostas e Markdown são exibidos como texto; novo envio após resultado
desconhecido exige ação explícita e indicação de possível duplicidade.


## Histórico — publicação de 15/11/2026

# Entrega de Backlog — 15/11/2026

A versão `0.5.0` está publicada na Azure. Este registro descreve o estado
verificado nesta data; os documentos com datas anteriores preservam suas
evidências históricas. [README e execução](../README.md).

| Evidência de publicação | Referência |
| --- | --- |
| Versão do pacote/OpenAPI | `0.5.0` |
| Commit de produção | [35898bd2](https://github.com/igorcpds/MOD1-BacklogService/commit/35898bd2a0287ef5efeb202d54601fd031ceabaf) |
| Integração | [PR #16](https://github.com/igorcpds/MOD1-BacklogService/pull/16) |
| Deploy concluído com sucesso | [GitHub Actions 43728744698](https://github.com/igorcpds/MOD1-BacklogService/actions/runs/43728744698) |

Não foi criada tag ou GitHub Release nessa publicação. Versões integradas:
Identidade 0.5.0, Projetos 0.6.0, Backlog 0.5.0 e Frontend 0.6.0.

## Integrações ativas

- Gemini real nas três APIs: `AI_PROVIDER=gemini`, `AI_SIMULATED=false` e
  `GEMINI_MODEL=gemini-3.5-flash-lite`. Os sete tipos dos adaptadores tiveram
  chamadas reais HTTP 200 com contexto sintético autorizado: análise de acessos,
  papéis, revogação, equipes, mapa de habilidades, treinamento e backlog inicial.
  A aprovação permanece humana; transporte validado não garante a qualidade de
  todos os cenários ou disponibilidade futura. [Contrato Gemini](gemini.md).
- CORS publicado nas três APIs para as origens aprovadas de GitHubSync
  (Módulo 2) e MackAI (Módulo 7), preservando frontend M1 e localhost 5173.
  Após os deploys, 36/36 preflights passaram; origens negativas foram bloqueadas
  e a ausência de Bearer continuou retornando 401 com CORS correto.
- Notificações de Backlog e Projetos ao Módulo 6 ativas, com workers separados
  e `source=backlog`. Identidade não emite esses eventos. Há um aceite real
  HTTP 200 de aviso com escopo de projeto, sem inspeção visual da Central.
  [Contrato e operação](module6-notifications.md).

## Evidências de Backlog

- CI final aprovado com testes, lint, tipos, auditoria de dependências e build.
  A suíte local anterior ao ajuste final de segurança teve 420 aprovados e
  2 ignorados; os 2 casos PostgreSQL foram executados separadamente em Docker
  local descartável e passaram.
- Login e leitura autorizada de histórias foram exercitados em produção com
  conta sintética já existente. O mesmo JWT foi recusado após logout nas três
  APIs, preservando a verificação online de sessão e permissões.
- Captura M6 ativa com `source=backlog`. API e `module6-worker` usam a mesma
  imagem; worker Running/ready, sem reinícios observados na verificação de
  publicação, sem ingress e com acesso somente ao schema Backlog.
- A fila persistente própria registra criação, status, bloqueio/desbloqueio e
  responsável de itens confirmados, sem replay histórico. Deduplicação local,
  concorrência, lease expirado, ACK atrasado e retry foram verificados também
  em PostgreSQL local.
- O transporte real compartilhado para o Módulo 6 foi validado por um aviso
  de teste de Projetos com escopo de projeto, aceito com HTTP 200. Essa
  evidência não demonstra um novo evento de negócio do Backlog percorrendo
  o outbox de produção ou apresentação visual na Central.

US-096, de revisão de código, permanece desabilitada. O contrato, o produtor
externo e o mapeamento de eventos ainda precisam ser acordados; não há
identificação confirmada do grupo produtor.
[Proposta e limites](code-review-proposal.md).

## Validação e limites comuns

As seis rotas públicas de saúde das três APIs responderam 200. A chave
JWT/JWKS existente e os dados anteriores foram preservados. O deploy incremental
manteve configurações de CORS, e-mail, MFA e segredos; migrações aditivas foram
executadas explicitamente, sem DDL no startup ou testes destrutivos em banco
remoto. API, aplicação, domínio e infraestrutura mantêm a
[arquitetura multicamadas](architecture.md).

O navegador em produção cobriu login, perfil, projetos e logout, em desktop e
mobile, sem overflow ou erros de página observados. Em ambiente isolado, o Edge também exerceu os sete tipos reais de Gemini,
persistência após reinício, aprovação idempotente de papéis/backlog, rejeição
e expiração de proposta após mudança de contexto. Equipes retornou vazio
válido; seu caminho positivo continua coberto pelos testes controlados.
[Aceite e reprodução de IA](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/local-ai-testing.md).

O aceite do Módulo 6 comprova transporte e confirmação de um aviso autorizado,
não o percurso completo de um novo evento de negócio pelo outbox de produção
nem sua apresentação na Central. Não há replay de histórico, anúncios globais ou
emissão de eventos privados não mapeados. O contrato externo de revisão de código
US-096 permanece pendente e desabilitado.

Comandos reproduzíveis e evidências históricas estão em
[verification.md](verification.md); operação e rollback em
[deploy-azure.md](deploy-azure.md).

## Fechamento da rastreabilidade

O escopo do Módulo 1 tem 99 US implementadas com evidências de teste e
uma dependência externa aberta, US-096. US-101 duplica US-009.
A aprovação de equipes com saída não vazia do Gemini não foi exercitada
nessa rodada: a análise real vazia foi dispensada sem efeitos. Isso não
substitui os testes controlados de aplicação/notificação desse tipo.
[Matriz e limites do aceite](https://github.com/Ckenz0/MOD1-WebFrontend/blob/main/docs/backlog-status.md).
Os commits finais de documentação não alteram a versão nem o contrato
HTTP destes backends. O frontend 0.6.1 acrescenta as correções de permissões
e navegação descritas em seu changelog; `/release.json` identifica o SHA
efetivamente implantado.
