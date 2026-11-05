# Backlog inicial com Gemini

O candidato local 0.5.0 adiciona Gemini na infraestrutura de Backlog. Apresentação,
aplicação e domínio continuam com as mesmas fronteiras descritas em
[arquitetura](architecture.md). `ProposalProvider` permanece o contrato da aplicação;
`HTTPProposalProvider` continua disponível e é o padrão. O frontend chama a API
de Backlog e nunca recebe a chave Gemini.

## Configuração do backend

Configure privadamente no ambiente do processo, usando `.env.example` como
referência pública. Não inclua chaves em scripts, URLs, commits, logs ou clientes.

| Variável | Padrão | Regra |
| --- | --- | --- |
| `AI_PROVIDER` | `structured-http` | `gemini` seleciona explicitamente Gemini |
| `GEMINI_API_KEY` | ausente | Segredo exclusivo do backend; ausência retorna 503 sem chamada |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Identificador de até 100 caracteres, sem slash/query/escape |
| `GEMINI_TIMEOUT_SECONDS` | `30` | Entre 1 e 30 segundos por operação HTTP |
| `GEMINI_MAX_OUTPUT_TOKENS` | `4096` | Entre 256 e 8192 |
| `GEMINI_API_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta` | Host oficial HTTPS, porta padrão; HTTP loopback permitido para simulação |

`AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY` e `AI_TIMEOUT_SECONDS` mantêm a semântica
do provedor HTTP genérico. Gemini usa apenas suas variáveis próprias e rejeita
`AI_SIMULATED=true`. O retorno público informa `provider=gemini`, o modelo
configurado e `simulated=false`, inclusive em testes controlados dessa integração.
Esse metadado identifica a integração; ele não prova que um teste acessou a nuvem.

## Contrato e limites

O adaptador envia `POST /models/{model}:generateContent`, chave somente em
`x-goog-api-key`, instrução em português em `systemInstruction`, contexto em
`contents` e `generationConfig.responseFormat.text` com
`mimeType=APPLICATION_JSON` e schema de `summary`, `justification`, `evidence` e
histórias tipadas em `suggestions`. Há um candidato por geração. O cliente do
backend desabilita proxies de ambiente; a chamada não usa Bearer do usuário,
redirects, ferramentas, pesquisa, retries ou fallback de modelo.

A resposta passa por modelos estritos exclusivos do Gemini, com os mesmos
campos obrigatórios, tipos, enums e limites do schema anunciado. Campos extras
são rejeitados na proposta e em cada história, inclusive estimativas, bloqueios
e referências que existem no contrato mais amplo de itens. Eles não são
silenciosamente descartados nem persistidos. As regras de domínio são verificadas
em seguida; o contrato do provedor HTTP genérico continua preservado.

O contexto autorizado tem limite de 64 KiB e a resposta tem limite de 256 KiB.
Nomes e descrições são tratados como dados não confiáveis, nunca como instruções.
Evidências só podem citar `project.<campo>` presente ou `items.<UUID>` existente.
IDs e responsáveis inventados são rejeitados. O domínio valida limites e regras
das histórias após a geração. Uma falha de transporte, quota 429, 5xx, bloqueio,
saída truncada, JSON inválido ou chamada de função retorna 503 sanitizado e não
persiste recomendações ou itens. Partes de raciocínio `thought=true` são ignoradas.

Uma proposta pode retornar `suggestions=[]` quando faltam requisitos. Ela pode ser
consultada e rejeitada. Aprovar uma proposta vazia retorna 409 sem gravar itens,
alterar a proposta ou avançar o quadro. Histórias não vazias só são criadas após
aprovação humana explícita, com transação, lease, versão, revalidação do contexto
e idempotência preservados. Nenhuma geração executa ações automaticamente.

## Validação local e limitações

Execute em ambiente isolado, sem configuração de banco remoto:

```powershell
uv sync --locked --group dev
Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
uv run pytest -q -rs
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

`tests/test_gemini_adapter.py` controla o transporte HTTP com dados e chave
sintéticos. Cobre configuração, schema, conteúdo da requisição, metadados,
sucesso, vazio, quota, 5xx, timeout, redirect, truncamento, limite de resposta,
chave ausente e ausência de Bearer. Os testes de recomendações e HTTP verificam
evidências inválidas, ausência de persistência nas falhas, 409 vazio e ausência
de aplicação antes da aprovação. Guardas AST verificam as fronteiras de camada
e `trust_env=False` no cliente da composição.

A execução final desta correção registrou **349 testes aprovados e 2 ignorados**
em 66 segundos. Os dois ignorados exigem PostgreSQL loopback descartável, ausente
nessa execução; SQLite temporário cobriu a persistência. Ruff, formato e mypy
passaram. Permanece um aviso de depreciação de Starlette/httpx no TestClient.
As regressões comprovam 503 sanitizado, nenhuma recomendação ou item gravado e
quadro/histórico preservados quando o Gemini retorna campos fora do contrato.

Esses testes demonstram o comportamento do código contra respostas controladas.
Não houve chamada de nuvem nesta implementação. Permanecem pendentes a validação
com chave e projeto autorizados, disponibilidade do modelo, quota e qualidade
das histórias reais. O plano do projeto Gemini determina faturamento e limites;
o código não promete gratuidade ilimitada nem altera faturamento. Testes
destrutivos PostgreSQL são opcionais e aceitam somente banco loopback descartável.

Referências do contrato: [generateContent](https://ai.google.dev/api/generate-content),
[modelo](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) e
[preços e quotas](https://ai.google.dev/gemini-api/docs/pricing).
