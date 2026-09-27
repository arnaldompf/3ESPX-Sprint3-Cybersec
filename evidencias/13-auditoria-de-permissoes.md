# Auditoria de permissões — 2026-10-01

## 1. Matriz de permissões vigente (lida do código)

| Ação | vendedor | analista | gestor | admin |
|---|---|---|---|---|
| `consultar_fichas` | ✓ | ✓ | ✓ | ✓ |
| `criar_sessao_showroom` | ✓ | — | ✓ | ✓ |
| `criar_extracoes` | — | ✓ | ✓ | ✓ |
| `ver_alertas` | — | ✓ | ✓ | ✓ |
| `ver_evidencias_brutas` | — | ✓ | ✓ | ✓ |
| `ver_insights` | próprios | ✓ | ✓ | ✓ |
| `aprovar_argumentos` | — | — | ✓ | ✓ |
| `gerir_referencia_interna` | — | — | ✓ | ✓ |
| `gerir_equivalencias` | — | — | ✓ | ✓ |
| `publicar` | — | — | ✓ | ✓ |
| `gerir_usuarios` | — | — | — | ✓ |
| `gerir_fontes` | — | — | — | ✓ |

## 2. Contas por papel

| Papel | Ativas | Inativas |
|---|---|---|
| vendedor | 1 | 0 |
| analista | 2 | 0 |
| gestor | 1 | 0 |
| admin | 1 | 0 |

Administradores ativos: **1** — OK

## 3. Contas ativas sem login há mais de 90 dias

| E-mail | Papel | Último login | Decisão |
|---|---|---|---|
| analista.antigo@specradar.example.com | analista | 2026-05-10 | ☐ manter ☐ desativar |

## 4. Contas ativas que nunca logaram (criadas há mais de 90 dias)

Nenhuma.

## 5. Identidades de papel sem senha (modo demonstração)

| E-mail | Papel | Último login | Decisão |
|---|---|---|---|
| analista@specradar.example.com | analista | nunca | ☐ manter ☐ desativar |
| gestor@specradar.example.com | gestor | nunca | ☐ manter ☐ desativar |

---
Revisado por: ____________________  Data: ___/___/______
