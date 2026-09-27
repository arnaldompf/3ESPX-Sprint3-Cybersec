#!/usr/bin/env bash
# Gera os segredos de produção em infra/segredos/ (gitignored), um arquivo por segredo.
# Rodar uma vez por ambiente. Não sobrescreve o que já existe.
#
# Permissões: o DIRETÓRIO é 0700 (nenhum outro usuário do host entra nele) e os arquivos são
# 0444. Os secrets do Compose são montados com a permissão do host, e os contêineres rodam
# com uid próprio (API 10001, Grafana 472, Prometheus 65534): com 0400 do usuário do host,
# nenhum deles conseguiria ler o próprio segredo. A proteção no host fica no diretório.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)/segredos"
mkdir -p "$DIR"
chmod 700 "$DIR"

gerar() { # nome conteudo
  local arquivo="$DIR/$1"
  if [[ -e "$arquivo" ]]; then
    echo "mantido: $1"
    return
  fi
  printf '%s' "$2" > "$arquivo"
  chmod 444 "$arquivo"
  echo "gerado:  $1"
}

aleatorio() { openssl rand -base64 "$1" | tr -d '\n'; }

SENHA_DB="$(openssl rand -hex 24)"
gerar db_password "$SENHA_DB"
if [[ ! -e "$DIR/database_url" ]]; then
  SENHA_DB="$(cat "$DIR/db_password")"
  gerar database_url "postgresql+psycopg://specradar:${SENHA_DB}@db:5432/specradar"
fi
gerar jwt_secret "$(aleatorio 48)"
gerar metrics_token "$(aleatorio 32)"
gerar log_pseudonimo_key "$(aleatorio 32)"
gerar data_key "$(openssl rand 32 | base64 | tr '+/' '-_' | tr -d '\n')"
gerar llm_api_key "${LLM_API_KEY:-preencha-com-a-chave-do-provedor}"
gerar grafana_admin "$(aleatorio 24)"
# Senha do primeiro admin da API (python -m seguranca.criar_admin).
gerar admin_password "$(aleatorio 24)"
# Webhooks de alerta (Teams/Slack/PagerDuty). Placeholder até o canal ser definido.
gerar webhook_plantao "${WEBHOOK_PLANTAO:-http://127.0.0.1:9/sem-canal-configurado}"
gerar webhook_time "${WEBHOOK_TIME:-http://127.0.0.1:9/sem-canal-configurado}"
