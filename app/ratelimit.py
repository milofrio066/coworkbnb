"""Límite de intentos de login: 5 fallos por usuario o 20 por IP en 15 minutos."""
from datetime import timedelta
from math import ceil

from sqlalchemy import delete, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.models import LoginFailure
from app.web import as_utc, utcnow

WINDOW = timedelta(minutes=15)
MAX_PER_USERNAME = 5
MAX_PER_IP = 20


def _wait(db: Session, column: InstrumentedAttribute, value: str, limit: int) -> int:
    """Segundos que faltan para poder reintentar (0 si no hay bloqueo)."""
    now = utcnow()
    times = list(db.scalars(
        select(LoginFailure.created_at)
        .where(column == value, LoginFailure.created_at > now - WINDOW)
        .order_by(LoginFailure.created_at)
    ))
    if len(times) < limit:
        return 0
    release = as_utc(times[len(times) - limit]) + WINDOW  # el fallo que debe vencer para bajar del límite
    return max(1, ceil((release - now).total_seconds()))


def retry_after(db: Session, username: str, ip: str) -> int:
    return max(
        _wait(db, LoginFailure.username, username, MAX_PER_USERNAME),
        _wait(db, LoginFailure.ip, ip, MAX_PER_IP),
    )


def record_failure(db: Session, username: str, ip: str) -> None:
    db.add(LoginFailure(username=username, ip=ip[:45]))
    db.execute(delete(LoginFailure).where(LoginFailure.created_at < utcnow() - timedelta(days=1)))
    db.commit()


def clear_failures(db: Session, username: str) -> None:
    db.execute(delete(LoginFailure).where(LoginFailure.username == username))
    db.commit()
