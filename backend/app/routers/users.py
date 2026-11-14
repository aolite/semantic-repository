"""Gestión de cuentas. Solo para el rol ``admin``."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app import users as user_service
from app.deps import DbDep, require_role
from app.models import Role, User
from app.schemas import UserCreate, UserRead, UserUpdate

router = APIRouter(
    prefix="/users",
    tags=["users"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "No autenticado"},
        status.HTTP_403_FORBIDDEN: {"description": "Requiere rol admin"},
    },
)

AdminUser = Annotated[User, Depends(require_role(Role.ADMIN))]


@router.get("", response_model=list[UserRead], summary="Lista las cuentas")
def list_users(db: DbDep, _admin: AdminUser) -> list[User]:
    return list(db.scalars(select(User).order_by(User.username)))


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Da de alta una cuenta",
    responses={status.HTTP_409_CONFLICT: {"description": "El nombre de usuario ya existe"}},
)
def create_user(payload: UserCreate, db: DbDep, admin: AdminUser) -> User:
    try:
        return user_service.create_user(
            db,
            username=payload.username,
            password=payload.password,
            role=payload.role,
            actor=admin,
        )
    except user_service.UsernameTakenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="El nombre de usuario ya existe"
        ) from exc


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Cambia el rol o el estado activo de una cuenta",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "La cuenta no existe"},
        status.HTTP_409_CONFLICT: {
            "description": "Un admin no puede quitarse el rol ni desactivarse a sí mismo"
        },
    },
)
def update_user(user_id: uuid.UUID, payload: UserUpdate, db: DbDep, admin: AdminUser) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La cuenta no existe")
    if user.id == admin.id and (
        (payload.role is not None and payload.role != Role.ADMIN) or payload.is_active is False
    ):
        # Evita que la unidad se quede sin ningún admin por error.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Un admin no puede quitarse el rol ni desactivarse a sí mismo",
        )
    return user_service.update_user(
        db, user, actor=admin, role=payload.role, is_active=payload.is_active
    )
