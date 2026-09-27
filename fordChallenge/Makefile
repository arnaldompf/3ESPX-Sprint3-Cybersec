# SpecRadar — Makefile.
#
# Todo alvo delega para scripts/task.py (Python puro), que e o executor canonico:
# no Windows desta maquina o GNU make nao existe (DECISOES_NOITE.md D-06), e manter
# a logica em um unico lugar evita que Makefile e Windows divirjam.
#
#   make up | down | migrate | api | worker | test | lint | fmt | eval | seed | qa | golden
#   make verify WP=07
#   make verify-quick
#
# Sem make instalado, use exatamente o mesmo alvo:
#   python scripts/task.py verify WP=07

PY ?= python
TASK = $(PY) scripts/task.py

.PHONY: help up down migrate api worker test lint fmt eval seed verify verify-quick web-test web-smoke qa golden sync

help:
	@$(TASK) help

up:
	@$(TASK) up

down:
	@$(TASK) down

migrate:
	@$(TASK) migrate

api:
	@$(TASK) api

worker:
	@$(TASK) worker

test:
	@$(TASK) test

lint:
	@$(TASK) lint

fmt:
	@$(TASK) fmt

eval:
	@$(TASK) eval

seed:
	@$(TASK) seed

sync:
	@$(TASK) sync

verify:
	@$(TASK) verify WP=$(WP)

verify-quick:
	@$(TASK) verify-quick

# Os testes de tela em Vitest + `tsc --noEmit`. Ja entra no verify-quick desde 12/09/2026
# (antes disso, 312 testes verdes que nenhum portao executava).
web-test:
	@$(TASK) web-test

# As 8 rotas nos 4 papeis, num Chromium de verdade (D-188). Ja entra no verify-quick;
# este alvo existe para rodar so ele quando se mexe na tela.
web-smoke:
	@$(TASK) web-smoke

# A regressao de tela do ensaio de QA (11/09/2026): um teste por defeito medido.
# Tambem ja entra no verify-quick.
qa:
	@$(TASK) qa

# O ensaio de palco: as 12 cenas gravadas em reports/demo/golden_path.webm.
# **Nao** entra no verify-quick: leva dois minutos e grava video.
golden:
	@$(TASK) golden
