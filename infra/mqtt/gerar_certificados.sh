#!/usr/bin/env bash
# PKI mínima do broker MQTT: CA própria, certificado do servidor e um por dispositivo.
#
#   bash infra/mqtt/gerar_certificados.sh mqtt.specradar.local totem-sp-001 specradar-ingestor
#
# Chaves ECDSA P-256 (curtas e rápidas para hardware embarcado). A chave da CA deve sair
# desta máquina para um cofre offline depois da emissão. Certificados de dispositivo valem
# 1 ano: rotação anual planejada, revogação por CRL no broker se um totem for roubado.
set -euo pipefail

SERVIDOR="${1:?informe o nome DNS do broker}"
shift
DIR="$(cd "$(dirname "$0")" && pwd)/certs"
mkdir -p "$DIR" && chmod 700 "$DIR" && cd "$DIR"
umask 077

if [[ ! -e ca.key ]]; then
  openssl ecparam -name prime256v1 -genkey -noout -out ca.key
  openssl req -x509 -new -key ca.key -sha256 -days 1825 -subj "/CN=SpecRadar IoT CA" -out ca.crt
fi

emitir() { # cn uso(extensão)
  openssl ecparam -name prime256v1 -genkey -noout -out "$1.key"
  openssl req -new -key "$1.key" -subj "/CN=$1" -out "$1.csr"
  openssl x509 -req -in "$1.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
    -days 365 -sha256 -extfile <(printf '%s' "$2") -out "$1.crt"
  rm -f "$1.csr"
  echo "emitido: $1"
}

emitir servidor "subjectAltName=DNS:${SERVIDOR}
extendedKeyUsage=serverAuth"
for cliente in "$@"; do
  emitir "$cliente" "extendedKeyUsage=clientAuth"
done

# O broker roda como uid 1883 e recebe só estes três arquivos (montados um a um no compose):
# lê pelo bit "outros". O diretório certs/ segue 0700 no host; ca.key e as chaves dos
# totens ficam 0600 e nunca são montadas no broker.
chmod 444 ca.crt servidor.crt servidor.key
