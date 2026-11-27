#!/bin/sh
# Aplica las migraciones pendientes y arranca la API en el puerto 8000.
# Cualquier argumento sustituye al arranque por defecto, por ejemplo:
#   docker compose run --rm -it backend python -m app.cli create-admin --username <nombre>
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Valida la configuración antes de tocar la base de datos (sin JWT_SECRET no arranca).
python -c "from app.config import get_settings; get_settings()"
alembic upgrade head
# --log-config: el formato de uvicorn de siempre, con un filtro que oculta el valor de
# `token=` (enlaces de descarga firmados) en el log de acceso (app/log_filters.py).
# --proxy-headers (explícito, aunque es lo que uvicorn hace por defecto): toma la IP del
# cliente de X-Forwarded-For solo si la conexión llega desde una IP de la variable
# FORWARDED_ALLOW_IPS, que uvicorn lee del entorno (por defecto 127.0.0.1,::1). No se pasa
# --forwarded-allow-ips para que mande esa variable (ver backend/README.md).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --log-config app/log_config.json
