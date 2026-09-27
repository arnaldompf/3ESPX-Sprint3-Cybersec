# SpecRadar — Ford Challenge (Desafio 01)

Pipeline auditável de inteligência competitiva automotiva: você pede marca + modelo + versão
(e, se quiser, atributos livres), e ele devolve uma ficha padronizada — sempre os mesmos
campos, na mesma ordem — onde cada valor carrega **status** (verificado / não verificado /
não disponível / não encontrado / divergente), **proveniência** (URL, trecho verbatim, data,
tier) e confiança. Nenhum valor entra na ficha sem uma citação literal encontrada no texto
salvo da fonte; quando não bate, o campo fica `não verificado` — nunca um número inventado.
Toda informação exibida na tela carrega uma etiqueta — **FATO** (observado, com evidência) ·
**INFERÊNCIA** (regra explícita e clicável) · **SIMULAÇÃO** (hipótese ou dado de demonstração).

---

## Subir em 5 comandos

```bash
uv sync                          # 1. dependências Python (cria .venv)
cd web && npm ci && cd ..        # 2. dependências do web app (o `up` também faz isso sozinho, se faltar)
bash scripts/demo/up.sh          # 3. banco de demo, migrações, seed, API + worker de pé
# abra http://127.0.0.1:8000/app # 4. sem login — cai direto na Consulta
bash scripts/demo/down.sh        # 5. para tudo quando terminar
```

No Windows sem Git Bash, troque o passo 3 por
`powershell -ExecutionPolicy Bypass -File scripts\demo\up.ps1` (e o 5 por `down.ps1`).
Passo a passo com pré-requisitos, tempo de cada etapa e onde ficam os logs:
**`docs/COMECE_AQUI.md`**.

O comando `up` sobe em **modo replay**: nenhuma chamada sai para a internet — os dados vêm de
cópias datadas dos sites-fonte, salvas em `tests/fixtures/snapshots/` (coleta original de
setembro/2026). É assim que a demo e o CI rodam sempre: determinístico, sem depender de o
site do fabricante estar de pé nem de chave de LLM.

## As telas

Nove destinos na navegação — Consulta, **Pesquisa** (diga o carro; o sistema identifica, pesquisa
com fontes e grava a ficha no catálogo), Radar, Matriz, Benchmark, Saúde, Showroom, Insights,
Simulador — mais a Ficha técnica de cada veículo, aberta a partir da Consulta ou da Pesquisa.

| | |
|---|---|
| ![Consulta](docs/img/01-consulta.png) **Consulta** — pedir um veículo pelo nome; a lista mostra o que já tem ficha e a saúde do conhecimento. | ![Ficha técnica](docs/img/02-ficha.png) **Ficha técnica** — os campos do veículo, cada um com status e evidência numa gaveta lateral. |
| ![Radar](docs/img/03-radar.png) **Radar** — fila de mudanças por prioridade, com a cadeia "por quê?" de cada alerta. | ![Matriz](docs/img/04-matriz.png) **Matriz de paridade** — onde ganhamos, empatamos, perdemos ou não sabemos, campo a campo. |
| ![Showroom](docs/img/05-showroom.png) **Showroom** — perfil do cliente e argumentário verificado, com onde o concorrente vence. | ![Saúde do conhecimento](docs/img/06-saude.png) **Saúde do conhecimento** — cobertura e divergências por montadora, com denominador. |
| ![Insights](docs/img/07-insights.png) **Insights** — win/loss das sessões de showroom. | ![Simulador](docs/img/08-simulador.png) **Simulador** — "e se o concorrente baixar o preço?", rotulado SIMULAÇÃO. |

Sem login (`AUTH_ENABLED=false`): o papel de quem usa é um seletor na barra lateral, e é ele
quem decide o que a tela mostra — nunca a ausência de senha.

## Os números do eval (medidos em 12/09/2026, replay)

| Métrica | Valor | Meta |
|---|---:|---|
| `field_accuracy` | **0,954** (104/109) | ≥ 0,90 |
| `status_fidelity` | **0,964** (134/139) | ≥ 0,90 |
| `hallucination_rate` | **0** (0/28) | 0 |
| `grounding_rate` | **1,000** (107/107) | 1,0 |
| `coverage` | **1,000** (148/148) | 1,0 |
| `resolver_accuracy` | **1,000** (6/6) | 1,0 |
| `slide_divergences_found` | **4/4** | 4/4 |
| custo por veículo | **R$ 0,00** (fast-path por regex; provedor de LLM real sem saldo — ver `MANHA.md`) | — |

Testes: **1.821** em Python, **298** de tela (Vitest) e **40** de regressão de QA num Chromium
de verdade. `python scripts/task.py verify-quick` fecha com `lint=ok testes=ok tela=ok qa=ok`.
Números derivados de `reports/eval.md` / `specs/STATUS.md`; **eval roda em replay** sobre os
snapshots datados — não é medição contra o site ao vivo do dia em que você ler isto.

## Mapa do repositório

| Pasta/arquivo | O que é |
|---|---|
| `CLAUDE.md` | Constituição do projeto: stack fixa, regras invioláveis, comandos, disciplina de tokens |
| `docs/00–13` | Visão, edital, arquitetura, schema, API, pipeline, mobile, ML, DevSecOps, eval, roadmap, setup; **`docs/13` vale sobre `docs/12`, que vale sobre `docs/00`/`docs/10`** |
| `docs/COMECE_AQUI.md` | Passo a passo para quem acabou de clonar |
| `docs/PARA_O_ARNALDO.md` | Tarefas que não colidem com a demo, uma por spec |
| `docs/img/` | Os 8 prints de tela deste README |
| `specs/` | WP-00…WP-40 com critérios de aceite e comando de verificação + `STATUS.md` |
| `maestro/` | Playbooks de Auto Run; **`maestro/05_sprint_15set.md` é a ordem vigente** |
| `schema/` | JSON Schema do formato de saída padronizado |
| `gabarito/` | Verdade-terra do eval (6 veículos, dezenas de atributos) + evidências brutas |
| `api/` `pipeline/` `web/` `ml/` `airflow/` `infra/` | código |
| `scripts/` | `task.py` (executor), `verify/WP-XX.sh`, `demo/` (`up.sh`/`down.sh`/`up.ps1`/`down.ps1`), `hooks/` |
| `DECISOES_NOITE.md` · `MANHA.md` | decisões autônomas registradas e resumo de cada rodada para o humano |

## Comandos de desenvolvimento

| Comando | O que faz |
|---|---|
| `python scripts/task.py test` | pytest com `REPLAY_MODE=1 LLM_FAKE=1` |
| `python scripts/task.py lint` / `fmt` | ruff check / ruff format |
| `python scripts/task.py eval` | gabarito → `reports/eval.json` + `reports/eval.md` |
| `python scripts/task.py verify WP=07` | roda `scripts/verify/WP-07.sh` |
| `python scripts/task.py verify-quick` | lint + testes + tela + QA (< 2 min) |
| `python scripts/task.py migrate` | `alembic upgrade head` |

Com `make` instalado (Linux/CI), os mesmos alvos funcionam como `make test`, `make verify
WP=07`, etc. — ver `DECISOES_NOITE.md` D-06 sobre por que este ambiente usa `task.py`.

## Regras invioláveis (resumo — texto completo em `CLAUDE.md` e `docs/12` §3)
1. Nenhum valor sem evidência: todo campo não-nulo tem trecho verbatim localizado no texto salvo da fonte.
2. Dois vazios: `nao_disponivel` (a fonte oficial afirma ausência) ≠ `nao_encontrado` (nenhuma fonte cita).
3. Divergência é exposta com todos os valores; o sistema não escolhe em silêncio.
4. O sistema nunca esconde onde o concorrente vence.
5. O score é "aderência ao perfil informado", decomposto — nunca "qual carro é melhor".
6. Nada inferido de outro mercado, ano-modelo ou versão; nada completado pelo modelo de linguagem.
7. Sem dado pessoal do cliente final; sem estatística inventada; segredos só em `.env`.
8. Scraping educado: robots.txt, ≤ 1 req/s por domínio, UA identificado. Fonte bloqueada vira status, não truque.

## Datas
Apresentação da solução: **15/09/2026** (portões em `docs/13` §6). Sprint 3: **27/09/2026**.
Sprint 4 (vídeo ≤ 6 min): **11/10/2026**.
