"""Login OAuth2 (password) y datos del usuario autenticado."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app import audit
from app.deps import CurrentUser, DbDep, SettingsDep
from app.models import AuditAction, User
from app.schemas import Token, UserRead
from app.security import create_access_token, has_control_chars, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Longitud máxima del nombre de usuario que se copia a la auditoría en un login fallido.
_AUDIT_USERNAME_MAX = 64


@router.post(
    "/token",
    response_model=Token,
    summary="Login con usuario y contraseña; devuelve un JWT con el rol",
    responses={status.HTTP_401_UNAUTHORIZED: {"description": "Credenciales no válidas"}},
)
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbDep,
    settings: SettingsDep,
) -> Token:
    def reject(reason: str, user: User | None = None, attempted: str | None = None) -> NoReturn:
        audit.record(
            db,
            AuditAction.LOGIN_FAILURE,
            target=user,
            target_username=attempted,
            details={"reason": reason},
        )
        db.commit()
        # Mismo mensaje en todos los casos para no revelar qué cuentas existen.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if has_control_chars(form.username):
        # NUL y otros caracteres de control: PostgreSQL los rechaza y no pueden formar
        # parte de un nombre válido. Se descarta sin consultar la BD y sin guardar el
        # valor bruto en auditoría. Se gasta el mismo tiempo que en un login normal.
        verify_password(form.password, None)
        reject("invalid_username")

    user = db.scalars(select(User).where(User.username == form.username)).one_or_none()
    password_ok = verify_password(form.password, user.password_hash if user else None)

    if user is None:
        reject("unknown_user", attempted=form.username[:_AUDIT_USERNAME_MAX])
    if not password_ok:
        reject("bad_password", user=user)
    if not user.is_active:
        reject("inactive_user", user=user)

    token, expires_in = create_access_token(
        settings, user_id=user.id, username=user.username, role=user.role
    )
    audit.record(db, AuditAction.LOGIN_SUCCESS, actor=user, target=user)
    db.commit()
    return Token(access_token=token, expires_in=expires_in, role=user.role)


@router.get("/me", response_model=UserRead, summary="Usuario autenticado")
def me(user: CurrentUser) -> User:
    return user
