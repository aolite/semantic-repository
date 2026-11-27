#!/usr/bin/env bash
# Restaura una copia hecha con backup.sh: PostgreSQL, Fuseki y distribuciones.
#
#   infra/scripts/restore.sh --yes <carpeta-de-la-copia>
#
# DESTRUCTIVO: sustituye por completo los datos actuales de las tres partes. Sin --yes no hace
# nada. Pasos: comprueba las sumas SHA-256, para el backend (y el proxy, para que nadie escriba
# ni lea datos a medias), restaura PostgreSQL (pg_restore --clean), vacía Fuseki (DROP ALL) y
# carga el N-Quads, vacía y restaura el volumen de distribuciones, y vuelve a arrancar el
# backend y el proxy. Los servicios postgres y fuseki tienen que estar en marcha.
#
# Variables de entorno: COMPOSE_FILE y COMPOSE_PROJECT_NAME, como en backup.sh. Para restaurar
# en una pila local sin proxy, funciona igual (los servicios que no existan se ignoran).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml:docker-compose.prod.yml}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }
dc() { docker compose "$@"; }

[ "${1:-}" = "--yes" ] || fail "uso: $0 --yes <carpeta-de-la-copia> (sustituye los datos actuales)"
SRC="${2:-}"
[ -n "$SRC" ] && [ -d "$SRC" ] || fail "indica la carpeta de la copia (la que creó backup.sh)"
SRC="$(cd "$SRC" && pwd)"
for f in postgres.dump fuseki.nq.gz distributions.tar.gz SHA256SUMS; do
  [ -s "$SRC/$f" ] || fail "falta $SRC/$f"
done

log "Comprobando sumas SHA-256"
(
  cd "$SRC"
  if command -v sha256sum > /dev/null; then sha256sum -c --quiet SHA256SUMS; else shasum -a 256 -c --quiet SHA256SUMS; fi
) || fail "las sumas no coinciden: la copia está dañada"

for svc in postgres fuseki; do
  [ -n "$(dc ps --status running --quiet "$svc")" ] || fail "el servicio $svc no está en marcha"
done

# Servicios que escriben o sirven datos: se paran durante la restauración y se arrancan al
# final, también si algo falla.
STOPPED=""
for svc in caddy backend; do
  if [ -n "$(dc ps --status running --quiet "$svc" 2> /dev/null)" ]; then
    STOPPED="$svc $STOPPED"
  fi
done
restart() {
  if [ -n "$STOPPED" ]; then
    log "Arrancando de nuevo: $STOPPED"
    # shellcheck disable=SC2086
    dc start $STOPPED > /dev/null || true
  fi
}
trap restart EXIT
if [ -n "$STOPPED" ]; then
  log "Parando: $STOPPED"
  # shellcheck disable=SC2086
  dc stop $STOPPED > /dev/null
fi

# --- PostgreSQL ---------------------------------------------------------------------------
log "PostgreSQL: pg_restore"
dc exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner --exit-on-error' \
  < "$SRC/postgres.dump"

# --- Fuseki -------------------------------------------------------------------------------
log "Fuseki: DROP ALL y carga del N-Quads"
# El fichero entra por stdin (docker cp lo dejaría como root y Fuseki no podría leerlo).
dc exec -T fuseki bash -c '
  set -euo pipefail
  auth="Authorization: Basic $(printf "admin:%s" "$FUSEKI_ADMIN_PASSWORD" | base64 -w0)"
  ds="${FUSEKI_DATASET:-itot}"
  trap "rm -f /tmp/restore.nq" EXIT
  zcat > /tmp/restore.nq
  wget -q -O /dev/null --header="$auth" --post-data="update=DROP ALL" "http://localhost:3030/$ds/update"
  wget -q -O /dev/null --header="$auth" --header="Content-Type: application/n-quads" \
    --post-file=/tmp/restore.nq "http://localhost:3030/$ds/data"
' < "$SRC/fuseki.nq.gz"

# --- Distribuciones -----------------------------------------------------------------------
# `run` en lugar de `exec`: el backend está parado. Monta el mismo volumen; el entrypoint de
# la imagen ejecuta el comando que se le pasa.
log "Distribuciones: vaciar y restaurar el volumen"
dc run --rm --no-deps -T backend sh -c \
  'find /data/distributions -mindepth 1 -delete && tar -C /data/distributions -xzf -' \
  < "$SRC/distributions.tar.gz"

log "Restauración completa desde $SRC"
