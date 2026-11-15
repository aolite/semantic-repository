# Usuarios de la API de F-UJI para el repositorio semántico IT&OT.
# Sustituye a fuji_server/config/users.py de la imagen oficial, que trae un usuario y una
# contraseña de ejemplo públicos. Se monta en solo lectura desde docker-compose.yml.
# Las credenciales vienen de FUJI_USERNAME y FUJI_PASSWORD (ver .env.example); sin ellas
# F-UJI no arranca, para no dejar nunca la API con credenciales por defecto.
import os

fuji_users = {os.environ["FUJI_USERNAME"]: os.environ["FUJI_PASSWORD"]}
