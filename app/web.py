"""Plantillas, sesión, CSRF y dependencias de autenticación/roles."""
import hmac
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Role, User

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

LABELS = {
    "pending": "Pendiente de revisión", "approved": "Aprobado", "rejected": "Rechazado",
    "suspended": "Suspendido", "confirmed": "Confirmada", "cancelled": "Cancelada",
    "pending_payment": "Pendiente de pago", "unpaid": "Sin pagar", "paid": "Pagada",
    "refunded": "Reembolsada", "open": "Abierta", "resolved": "Resuelta", "client": "Cliente", "owner": "Dueño", "admin": "Admin",
}
templates.env.filters["label"] = lambda v: LABELS.get(getattr(v, "value", v), str(v))
templates.env.filters["cop"] = lambda v: "$" + f"{v:,.0f}".replace(",", ".")

AMENITY_ICONS = {
    "wifi": "📶", "internet": "📶", "café": "☕", "cafe": "☕", "sala": "🗣️", "reunion": "🗣️",
    "reunión": "🗣️", "parqueadero": "🚗", "parking": "🚗", "aire": "❄️", "terraza": "🌿",
    "impresora": "🖨️", "proyector": "📽️", "pantalla": "🖥️", "monitor": "🖥️", "locker": "🔐",
    "24": "🕒", "cocina": "🍽️", "mascota": "🐾", "ducha": "🚿", "bicicleta": "🚲", "silla": "🪑",
    "tablero": "📝", "recepción": "🛎️", "recepcion": "🛎️", "seguridad": "🛡️", "luz": "☀️",
}


def amenity_list(raw: str) -> list[tuple[str, str]]:
    out = []
    for item in (a.strip() for a in (raw or "").split(",")):
        if item:
            low = item.lower()
            icon = next((i for k, i in AMENITY_ICONS.items() if k in low), "✔️")
            out.append((icon, item[:1].upper() + item[1:]))
    return out


def initials(name: str) -> str:
    parts = [p for p in (name or "?").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


templates.env.filters["amenities"] = amenity_list
templates.env.filters["initials"] = initials
templates.env.filters["hour"] = lambda h: f"{int(h):02d}:00"
templates.env.globals["MONTHS"] = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
templates.env.filters["fecha"] = lambda d: f"{d.day} {templates.env.globals['MONTHS'][d.month - 1]} {d.year}"

HOME_BY_ROLE ={Role.client: "/", Role.owner: "/owner", Role.admin: "/admin"}


def now_local() -> datetime:
    return datetime.now(ZoneInfo(settings.timezone))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """SQLite devuelve fechas sin zona; PostgreSQL con zona. Todo se guarda en UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def flash(request: Request, message: str, kind: str = "info") -> None:
    request.session.setdefault("flashes", []).append([kind, message])


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


async def verify_csrf(request: Request) -> None:
    """Dependencia global: toda petición que modifica datos debe traer el token de la sesión."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    form = await request.form()
    sent = str(form.get("csrf", ""))
    expected = request.session.get("csrf")
    if not expected or not hmac.compare_digest(sent, expected):
        raise HTTPException(403, "Sesión expirada o token inválido. Recarga la página.")


def render(request: Request, name: str, status: int = 200, **ctx: Any):
    context = {
        "user": getattr(request.state, "user", None),
        "flashes": request.session.pop("flashes", []),
        "csrf": csrf_token(request),
        **ctx,
    }
    return templates.TemplateResponse(request, name, context, status_code=status)


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user = None
    if uid := request.session.get("uid"):
        user = db.get(User, uid)
        if user is None or not user.is_active:
            request.session.clear()
            user = None
    request.state.user = user
    return user


def require(*roles: Role):
    def dependency(user: User | None = Depends(current_user)) -> User:
        if user is None:
            raise HTTPException(401)
        if user.role not in roles:
            raise HTTPException(403, "No tienes permiso para esta acción.")
        return user

    return dependency


require_client = require(Role.client)
require_owner = require(Role.owner)
require_admin = require(Role.admin)
require_party = require(Role.client, Role.owner)  # participantes de una reserva
