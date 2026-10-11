# Validação do backlog MVP — 11/10/2026

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
