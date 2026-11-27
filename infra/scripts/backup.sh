#!/usr/bin/env bash
# Copia de seguridad del repositorio semántico IT&OT: PostgreSQL, Fuseki y distribuciones.
# Pensado para cron. Se puede lanzar las veces que haga falta: cada ejecución crea una carpeta
# nueva con la fecha UTC y nunca modifica las anteriores; si falla, no deja una copia a medias
# y sale con código distinto de 0.
#
#   infra/scripts/backup.sh
#
# Contenido de BACKUP_DIR/<fecha>/:
#   postgres.dump          pg_dump en formato custom (usuarios y auditoría)
#   fuseki.nq.gz           volcado N-Quads de todos los grafos (API de administración de Fuseki,
#                          usuario admin)
#   distributions.tar.gz   volumen de distribuciones
#   SHA256SUMS             sumas de comprobación de los tres ficheros
#
# Variables de entorno (todas opcionales):
#   BACKUP_DIR             carpeta de destino (por defecto $HOME/itot-backups)
#   BACKUP_RETENTION_DAYS  días que se conservan las copias (por defecto 14). Siempre queda la
#                          copia más reciente, aunque sea más antigua
#   COMPOSE_FILE           ficheros de Compose separados por ":" (por defecto, el local más el
#                          de producción)
#   COMPOSE_PROJECT_NAME   proyecto de Compose (por defecto el que decida Compose: `itot`)
#
# Las credenciales (usuario de PostgreSQL, contraseña de admin de Fuseki) se leen del entorno de
# los propios contenedores: el script no lee .env ni guarda ningún secreto.
# Ejemplo de cron (diario a las 03:30, con el registro en un fichero):
#   30 3 * * * cd /srv/semantic-repository && infra/scripts/backup.sh >> /var/log/itot-backup.log 2>&1
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

BACKUP_DIR="${BACKUP_DIR:-$HOME/itot-backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml:docker-compose.prod.yml}"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

case "$RETENTION_DAYS" in
  '' | *[!0-9]*) fail "BACKUP_RETENTION_DAYS debe ser un número entero de días" ;;
esac

dc() { docker compose "$@"; }

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Un solo backup a la vez (mkdir es atómico y vale en Linux y macOS).
LOCK="$BACKUP_DIR/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  fail "hay otra copia en curso (si no es así, borra $LOCK)"
fi

STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
TMP="$BACKUP_DIR/.partial-$STAMP"
FINAL="$BACKUP_DIR/$STAMP"
cleanup() {
  rm -rf "$TMP"
  rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT
mkdir -p "$TMP"
umask 077

for svc in postgres fuseki backend; do
  [ -n "$(dc ps --status running --quiet "$svc")" ] || fail "el servicio $svc no está en marcha"
done

# --- PostgreSQL ---------------------------------------------------------------------------
log "PostgreSQL: pg_dump"
dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "$TMP/postgres.dump"
[ -s "$TMP/postgres.dump" ] || fail "pg_dump no ha generado datos"

# --- Fuseki -------------------------------------------------------------------------------
# POST /$/backup/itot: Fuseki escribe en /fuseki-base/backups un N-Quads comprimido con todos los
# grafos (tarea asíncrona). Se espera a que termine, se copia fuera y se borra del contenedor.
log "Fuseki: volcado N-Quads de todos los grafos"
FUSEKI_FILE="$(dc exec -T fuseki bash -c '
  set -euo pipefail
  auth="Authorization: Basic $(printf "admin:%s" "$FUSEKI_ADMIN_PASSWORD" | base64 -w0)"
  resp=$(wget -q -O- --header="$auth" --post-data="" "http://localhost:3030/\$/backup/${FUSEKI_DATASET:-itot}")
  id=$(printf "%s" "$resp" | sed -n "s/.*\"taskId\" *: *\"\{0,1\}\([0-9]*\).*/\1/p")
  [ -n "$id" ] || { echo "respuesta inesperada de Fuseki: $resp" >&2; exit 1; }
  for _ in $(seq 1 600); do
    status=$(wget -q -O- --header="$auth" "http://localhost:3030/\$/tasks/$id" || true)
    if printf "%s" "$status" | grep -q "\"finished\""; then break; fi
    sleep 1
  done
  printf "%s" "$status" | grep -q "\"finished\"" || { echo "la copia de Fuseki no terminó a tiempo" >&2; exit 1; }
  printf "%s" "$status" | grep -Eq "\"success\" *: *true" || { echo "la tarea de copia de Fuseki falló: $status" >&2; exit 1; }
  ls -t /fuseki-base/backups/*.nq.gz | head -n 1
')"
FUSEKI_FILE="$(printf '%s' "$FUSEKI_FILE" | tr -d '\r')"
[ -n "$FUSEKI_FILE" ] || fail "Fuseki no ha generado el fichero de copia"
dc cp "fuseki:$FUSEKI_FILE" "$TMP/fuseki.nq.gz" > /dev/null
dc exec -T fuseki rm -f "$FUSEKI_FILE"
gzip -t "$TMP/fuseki.nq.gz" || fail "el volcado de Fuseki está corrupto"

# --- Distribuciones -----------------------------------------------------------------------
log "Distribuciones: tar del volumen"
dc exec -T backend tar -C /data/distributions -czf - . > "$TMP/distributions.tar.gz"
gzip -t "$TMP/distributions.tar.gz" || fail "el tar de distribuciones está corrupto"

# --- Sumas y publicación ------------------------------------------------------------------
(
  cd "$TMP"
  if command -v sha256sum > /dev/null; then
    sha256sum postgres.dump fuseki.nq.gz distributions.tar.gz > SHA256SUMS
  else
    shasum -a 256 postgres.dump fuseki.nq.gz distributions.tar.gz > SHA256SUMS
  fi
)
mv "$TMP" "$FINAL"
log "Copia completa: $FINAL"

# --- Retención ----------------------------------------------------------------------------
# Borra las copias con más de BACKUP_RETENTION_DAYS días, salvo la más reciente.
newest="$STAMP"
find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20??-??-??T??????Z' -mtime +"$RETENTION_DAYS" \
  | while read -r old; do
      [ "$(basename "$old")" = "$newest" ] && continue
      log "Retención: borro $(basename "$old")"
      rm -rf "$old"
    done
log "Hecho"
