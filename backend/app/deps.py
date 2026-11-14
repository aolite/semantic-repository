"""Dependencias reutilizables de autenticación y autorización.

- ``get_current_user_optional``: para rutas públicas (rol ``lector``, anónimo). Devuelve
  ``None`` si no hay token, pero un token inválido sigue dando 401.
- ``get_current_user``: exige un token válido de una cuenta activa.
- ``require_role(*roles)``: exige además que el rol de la cuenta esté en ``roles``, teniendo
  en cuenta la única herencia decidida: **admin hereda los permisos de editor**
  (``ROLE_INHERITS``). Ninguna otra herencia está decidida.

El rol se lee siempre de la base de datos, no del token: un cambio de rol o una baja
surten efecto en la siguiente petición, sin esperar a que caduque el JWT.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Role, User
from app.security import InvalidTokenError, decode_access_token
from app.triplestore import FusekiStore, TripleStore
from app.uris import Uris

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def _unauthorized(detail: str = "Credenciales no válidas") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user_optional(
    token: Annotated[str | None, Depends(oauth2_scheme)],
    db: DbDep,
    settings: SettingsDep,
) -> User | None:
    if token is None:
        return None
    try:
        claims = decode_access_token(settings, token)
    except InvalidTokenError as exc:
        raise _unauthorized() from exc
    user = db.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _unauthorized()
    return user


def get_current_user(
    user: Annotated[User | None, Depends(get_current_user_optional)],
) -> User:
    if user is None:
        raise _unauthorized("No autenticado")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]


# Herencia de permisos entre roles: rol -> roles cuyos permisos hereda.
# Decisión del responsable (2026-11-14): el admin hereda los permisos de editor.
# El resto de herencias NO está decidido: miembro no se hereda, y editor no hereda nada.
ROLE_INHERITS: dict[Role, frozenset[Role]] = {
    Role.ADMIN: frozenset({Role.EDITOR}),
}


def effective_roles(role: Role) -> frozenset[Role]:
    """El rol de la cuenta más los que hereda (sin transitividad: no hay cadenas)."""
    return frozenset({role}) | ROLE_INHERITS.get(role, frozenset())


def require_role(*roles: Role) -> Callable[[User], User]:
    """Crea una dependencia que exige uno de los ``roles`` indicados.

    Se aplica ``ROLE_INHERITS``: ``require_role(Role.EDITOR)`` admite también a admin.
    ``require_role(Role.MIEMBRO)`` solo admite a miembro, y ``require_role(Role.ADMIN)``
    no admite a editor.
    Uso: ``user: Annotated[User, Depends(require_role(Role.EDITOR))]``.
    """
    if not roles:
        raise ValueError("require_role necesita al menos un rol")
    allowed = frozenset(roles)

    def dependency(user: CurrentUser) -> User:
        if not (effective_roles(user.role) & allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permisos insuficientes",
            )
        return user

    return dependency


def get_triplestore(settings: SettingsDep) -> TripleStore:
    """Cliente del triplestore. Las pruebas lo sustituyen por ``MemoryStore``."""
    return FusekiStore.from_settings(settings)


def get_uris(settings: SettingsDep) -> Uris:
    return Uris(settings.base_uri)


StoreDep = Annotated[TripleStore, Depends(get_triplestore)]
UrisDep = Annotated[Uris, Depends(get_uris)]
