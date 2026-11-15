#!/bin/bash
# Arranque de Fuseki para el repositorio semántico IT&OT.
# Genera /fuseki-base/shiro.ini desde la plantilla montada (infra/fuseki/shiro.ini): pone la
# contraseña de "admin" (FUSEKI_ADMIN_PASSWORD) y la de "backend" (FUSEKI_BACKEND_PASSWORD).
# Después lanza el entrypoint original de la imagen. Las contraseñas no se escriben en
# ningún fichero del repositorio.
set -euo pipefail

: "${FUSEKI_ADMIN_PASSWORD:?FUSEKI_ADMIN_PASSWORD no está definida (ver .env.example)}"
: "${FUSEKI_BACKEND_PASSWORD:?FUSEKI_BACKEND_PASSWORD no está definida (ver .env.example)}"

# Shiro separa usuario, contraseña y roles con "=" y ",": no se admiten en las contraseñas.
for var in FUSEKI_ADMIN_PASSWORD FUSEKI_BACKEND_PASSWORD; do
  case "${!var}" in
    *,* | *=* | *\\* | *\#* | *\;*)
      echo "$var no puede contener , = \\ # ni ;" >&2
      exit 1
      ;;
  esac
done

# ENVIRON de awk no interpreta escapes ni caracteres especiales (a diferencia de sed).
# Los roles (admin, writer) van en la línea del usuario, tras la contraseña.
awk '
  $0 == "admin=placeholder"   { print "admin="   ENVIRON["FUSEKI_ADMIN_PASSWORD"]   ",admin,writer"; next }
  $0 == "backend=placeholder" { print "backend=" ENVIRON["FUSEKI_BACKEND_PASSWORD"] ",writer"; next }
  { print }
' /shiro.ini.template > /fuseki-base/shiro.ini

# El entrypoint de la imagen reescribiría la línea de admin con sed (y le quitaría los
# roles) si ADMIN_PASSWORD estuviera definida: ya está aplicada, así que no se le pasa.
unset ADMIN_PASSWORD

exec /docker-entrypoint.sh "$@"
