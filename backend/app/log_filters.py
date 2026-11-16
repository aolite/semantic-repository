"""Filtros de logging para uvicorn (``app/log_config.json``, ``--log-config``).

``RedactTokenFilter`` oculta el valor de ``token=`` en la URL que escribe el log de acceso.
Los enlaces de descarga firmados (``/dataset/…/fichero?token=…``) son credenciales de un
solo uso: no deben quedar en los logs del contenedor aunque ya hayan caducado.
"""

import logging
import re

_TOKEN = re.compile(r"([?&]token=)[^&#\s\"]*", re.IGNORECASE)
REDACTED = "[oculto]"


def redact(text: str) -> str:
    return _TOKEN.sub(rf"\g<1>{REDACTED}", text)


class RedactTokenFilter(logging.Filter):
    """Sustituye el valor de ``token=`` en los argumentos y el mensaje del registro."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: redact(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True
