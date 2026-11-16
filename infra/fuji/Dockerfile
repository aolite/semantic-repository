# F-UJI para el repositorio semántico IT&OT.
# Parte de la imagen oficial del proyecto (pangaea-data-publisher/fuji, tag 4.0.1) fijada por
# digest. La imagen oficial 4.0.1 (y `latest`) no arranca: F-UJI 4 inicia Chromium con
# Playwright al arrancar (fuji_server/helper/browser_manager.py) y la imagen no lo incluye
# (error "Executable doesn't exist ... chrome-headless-shell"). Aquí solo se instala ese
# navegador, con la versión de Playwright que ya trae la imagen. No se cambia nada más.
# Al construir se descarga el navegador del CDN de Playwright; en ejecución no se baja nada.
# Al actualizar F-UJI hay que cambiar el digest y revisar si la imagen oficial ya lo arregla.
FROM ghcr.io/pangaea-data-publisher/fuji@sha256:2108f2e2f52fed4cc0f58f22d47644c5d015c5c66f3886e2440e216c533e6a9a

# Solo el "headless shell" de Chromium (es el que usa launch(headless=True)) y sus
# dependencias del sistema (--with-deps usa apt).
RUN playwright install --with-deps chromium-headless-shell \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
