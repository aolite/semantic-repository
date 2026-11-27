# Frontend de producción: build estático de Vite servido por Caddy. El Dockerfile de
# frontend/ es el de desarrollo (servidor de Vite) y no se toca.
# Contexto: ./frontend. El Caddyfile llega como contexto adicional `infra` (./infra/frontend).
# Vite incrusta VITE_API_BASE_URL y VITE_BASE_URI en el build (no se leen en ejecución),
# por eso llegan como argumentos de build; docker-compose.prod.yml los deriva de
# API_HOST. Versión de Node igual a la de frontend/Dockerfile.
FROM node:26.13.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_BASE_URI
RUN test -n "$VITE_API_BASE_URL" && test -n "$VITE_BASE_URI" && npm run build

FROM caddy:2.11.9-alpine
COPY --from=infra Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
# Sin privilegios: puerto 8080 y sin escribir en el sistema de ficheros.
ENV XDG_DATA_HOME=/tmp XDG_CONFIG_HOME=/tmp
USER 65532:65532
EXPOSE 8080
