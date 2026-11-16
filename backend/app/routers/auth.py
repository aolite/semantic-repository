"""Login OAuth2 (password) y datos del usuario autenticado."""

from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app import audit, login_guard
from app.deps import CurrentUser, DbDep, SettingsDep
from app.models import AuditAction, User
from app.schemas import ErrorResponse, Token, UserRead
from app.security import create_access_token, has_control_chars, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/token",
    response_model=Token,
    summary="Login con usuario y contraseña; devuelve un JWT con el rol",
    description=(
        "Tras LOGIN_MAX_FAILURES fallos en LOGIN_WINDOW_MINUTES para el mismo (usuario, IP), "
        "ese par queda bloqueado LOGIN_LOCKOUT_MINUTES: 429 con Retry-After, aunque la "
        "contraseña sea correcta. Un login correcto pone el contador a cero."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Credenciales no válidas"},
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorResponse,
            "description": "Demasiados intentos fallidos; ver Retry-After",
        },
    },
)
def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbDep,
    settings: SettingsDep,
) -> Token:
    ip = request.client.host if request.client else "desconocida"
    # Lo que se guarda en auditoría: sin caracteres de control y truncado a 64 (decisión 18).
    attempted = login_guard.sanitize_username(form.username) or None

    def too_many(seconds: int) -> NoReturn:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos: espera antes de volver a intentarlo",
            headers={"Retry-After": str(seconds)},
        )

    def reject(reason: str, user: User | None = None) -> NoReturn:
        locked = login_guard.register_failure(db, settings, form.username, ip)
        audit.record(
            db,
            AuditAction.LOGIN_FAILURE,
            target=user,
            target_username=None if user else attempted,
            details={"reason": reason},
        )
        if locked:
            audit.record(
                db,
                AuditAction.LOGIN_LOCKED,
                target=user,
                target_username=None if user else attempted,
                details={
                    "failures": settings.login_max_failures,
                    "minutes": settings.login_lockout_minutes,
                },
            )
        db.commit()
        # Mismo mensaje en todos los casos para no revelar qué cuentas existen.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    remaining = login_guard.locked_for(db, form.username, ip)
    if remaining is not None:
        verify_password(form.password, None)  # mismo tiempo que un login normal
        audit.record(
            db,
            AuditAction.LOGIN_FAILURE,
            target_username=attempted,
            details={"reason": "locked"},
        )
        db.commit()
        too_many(remaining)

    if has_control_chars(form.username):
        # NUL y otros caracteres de control: PostgreSQL los rechaza y no pueden formar
        # parte de un nombre válido. Se descarta sin consultar la cuenta. Se gasta el mismo
        # tiempo que en un login normal.
        verify_password(form.password, None)
        reject("invalid_username")

    user = db.scalars(select(User).where(User.username == form.username)).one_or_none()
    password_ok = verify_password(form.password, user.password_hash if user else None)

    if user is None:
        reject("unknown_user")
    if not password_ok:
        reject("bad_password", user=user)
    if not user.is_active:
        reject("inactive_user", user=user)

    token, expires_in = create_access_token(
        settings, user_id=user.id, username=user.username, role=user.role
    )
    login_guard.reset(db, form.username, ip)
    audit.record(db, AuditAction.LOGIN_SUCCESS, actor=user, target=user)
    db.commit()
    return Token(access_token=token, expires_in=expires_in, role=user.role)


@router.get("/me", response_model=UserRead, summary="Usuario autenticado")
def me(user: CurrentUser) -> User:
    return user
