# SpecRadar — Ford Challenge · Sprint 3 de Cybersecurity (DevSecOps)

**FIAP · 3ESPX · 2026 — Desafio 01 Ford**

| Integrante | RM |
|---|---|
| Arnaldo Filho | 555780 |
| Carlos Eduardo | 99849 |
| Vinicius Gardim | 556013 |
| Leonardo Correia | 550413 |
| Fabricio Carlos | 555017 |

📄 **Documento da entrega:** [`docs/SPRINT3_CYBERSECURITY.md`](docs/SPRINT3_CYBERSECURITY.md)
(único, separado pelas quatro atividades da Sprint).

---

## O projeto

O **SpecRadar** é a solução do grupo para o Desafio 01 da Ford: um pipeline **auditável** de
inteligência competitiva automotiva. O usuário informa marca, modelo e versão de um veículo, e
o sistema faz quatro coisas:

1. **coleta** as fichas técnicas nos sites dos fabricantes, respeitando robots.txt e 1 req/s
   por domínio;
2. **extrai** as especificações com regex e LLM;
3. **só publica um valor quando encontra o trecho literal dele na fonte salva** (grounding).
   Se não encontra, o campo fica `não verificado`, e nunca com um número inventado;
4. entrega uma **ficha padronizada**, a mesma para qualquer veículo, em que cada campo traz
   status (verificado, divergente, não disponível...), proveniência (URL, trecho, data) e
   confiança.

Sobre as fichas funcionam as telas de **Radar** (mudanças nos concorrentes), **Matriz de
paridade** (onde a Ford ganha, empata ou perde), **Showroom** (argumentário do vendedor, que
sempre mostra onde o concorrente vence) e **Simulador**.

| Camada | Tecnologia |
|---|---|
| API | Python 3.12, FastAPI, SQLModel/Alembic, JWT (PyJWT) + argon2id, RBAC por ação |
| Pipeline / ML | coleta httpx/Playwright, extração com LLM + Instructor, eval contra gabarito |
| Interface | web app responsivo React + Vite + TypeScript + Tailwind, servido em `/app` |
| Dados | Postgres 16 (produção) / SQLite (demo) |

## A Sprint 3: segurança como parte do ciclo

A Sprint leva a segurança do projeto para um modelo **DevSecOps**: segurança aplicada no
commit, no build, no deploy e na operação, e não só descrita em documento. O código da
solução fica **intocado** em `fordChallenge/`. Todo o trabalho de segurança está na raiz e se
aplica sobre ela **por composição**.

| Atividade (peso) | O que foi entregue | Onde |
|---|---|---|
| **1. Pipeline DevSecOps** (3,0) | GitHub Actions com 9 etapas: Gitleaks, Semgrep, pip-audit/npm audit, testes, Hadolint/Trivy config, Trivy image + SBOM, OWASP ZAP, Cosign e deploy com aprovação | [`.github/`](.github/), doc §1 |
| **2. Segurança em código e infra** (2,5) | rate limit sem bypass (vulnerabilidade real corrigida), trava de produção, anti-SSRF, AES-256-GCM, backup cifrado, RBAC, MQTT/TLS, Dockerfile e compose endurecidos | [`seguranca/`](seguranca/), [`infra/`](infra/), doc §2 |
| **3. Observabilidade e resposta** (2,0) | eventos de segurança, `/metrics`, Prometheus + Loki + Grafana + Alertmanager, 17 alertas, plano de resposta a incidentes com playbooks | [`observabilidade/`](observabilidade/), doc §3 |
| **4. Compliance e segurança contínua** (2,5) | STRIDE final, OWASP ASVS / API Top 10 / Mobile Top 10, LGPD, rotinas contínuas, checklist | doc §4 |

**Achados reais da primeira execução do pipeline:** 16 CVEs no lock Python (PyJWT, urllib3),
5 em dependências npm e 5 achados de SAST. Um deles foi explorado e corrigido: o bypass do rate
limit por JWT forjado. Os demais foram triados, com detalhes no doc §1.3.

## Estrutura do repositório

```
.
├── docs/SPRINT3_CYBERSECURITY.md   ← documento da entrega (4 atividades)
├── evidencias/                     ← 15 saídas reais (scanners, testes, stack no ar, logs, métricas)
│   └── prints/                     um print de cada evidência, com o mesmo nome
├── seguranca/                      ← camada de segurança aplicada sobre a solução
│   ├── app_segura.py               API endurecida (trava de produção, rate limit, eventos, /metrics)
│   ├── ssrf.py                     bloqueio de SSRF no coletor do pipeline
│   ├── cripto_local.py             AES-256-GCM para dados em repouso
│   ├── backup.py                   backup cifrado, verificação e restauração
│   ├── auditoria_permissoes.py     rotina mensal de auditoria de RBAC
│   ├── criar_admin.py              primeiro admin com senha vinda de secret
│   ├── metricas.py                 métricas no formato Prometheus
│   ├── segredos.py                 segredos via arquivo (Docker secrets)
│   └── worker_seguro.py            worker do pipeline com anti-SSRF
├── tests/                          ← 47 testes da camada de segurança
├── infra/                          ← IaC: Dockerfile, compose, Caddy (TLS), MQTT (mTLS)
├── observabilidade/                ← Prometheus, alertas, Loki, Alloy, Grafana, Alertmanager
├── .github/                        ← pipeline DevSecOps + Dependabot
├── .semgrep/ .gitleaks.toml .zap/  ← regras e exceções revisadas dos scanners
├── .pre-commit-config.yaml         ← verificações antes do commit
└── fordChallenge/                  ← a solução SpecRadar (código do produto, não alterado)
```

## Como rodar

**Pré-requisitos:** [uv](https://docs.astral.sh/uv/) e Python 3.12. Para subir a stack
completa, também Docker e Node 22.

```bash
# dependências da solução (cria fordChallenge/.venv)
uv sync --project fordChallenge

# testes da camada de segurança
uv run --project fordChallenge pytest

# API endurecida local (modo demonstração: SQLite, sem internet, sem LLM)
uv run --project fordChallenge uvicorn seguranca.app_segura:app --port 8000
```

Para a stack de produção com observabilidade:

```bash
bash infra/gerar_segredos.sh                                          # segredos em infra/segredos/ (gitignored)
docker compose -f infra/docker-compose.yml up -d --build              # Caddy + API + worker + Postgres
docker compose -f infra/docker-compose.yml exec api python -m seguranca.criar_admin --email <admin>
docker compose -f observabilidade/docker-compose.observabilidade.yml up -d
# https://localhost (app) · http://127.0.0.1:3000 (Grafana)
```

Ferramentas das rotinas contínuas:

```bash
python -m seguranca.backup criar --banco "$DATABASE_URL" --destino backups/ --manter 14
python -m seguranca.backup verificar backups/<arquivo>.srbak
python -m seguranca.auditoria_permissoes --saida auditoria-2026-10.md
python -m seguranca.cripto_local cifrar <arquivo>
```

Para instruções da solução em si (telas, pipeline, eval), consulte
[`fordChallenge/README.md`](fordChallenge/README.md).
