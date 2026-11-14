# Imagen de desarrollo del frontend: servidor de Vite con recarga en caliente.
# Versión de Node fijada; actualizarla a mano junto con el CI.
FROM node:26.13.0-alpine

WORKDIR /app

# Dependencias primero para aprovechar la caché de capas.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Usuario sin privilegios incluido en la imagen oficial.
RUN chown -R node:node /app
USER node

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
