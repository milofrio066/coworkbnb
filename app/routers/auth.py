import re
from math import ceil

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ratelimit
from app.config import settings
from app.database import get_db
from app.models import Role, User
from app.security import hash_password, verify_password
from app.web import HOME_BY_ROLE, current_user, flash, render

router = APIRouter()

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_LEN = {"full_name": 120, "phone": 30, "document_id": 30, "business_name": 120}


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse(HOME_BY_ROLE[user.role], 303)
    return render(request, "login.html", demo=settings.demo_mode)


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    uname = username.strip().lower()[:30]
    ip = request.client.host if request.client else "unknown"
    # El bloqueo se evalúa antes de mirar la clave: así no sirve para adivinarla
    if wait := ratelimit.retry_after(db, uname, ip):
        flash(request, f"Demasiados intentos fallidos. Intenta de nuevo en {ceil(wait / 60)} minuto(s).", "error")
        return render(request, "login.html", status=429, demo=settings.demo_mode)
    user = db.scalar(select(User).where(User.username == uname))
    if user is None or not verify_password(password, user.password_hash):
        ratelimit.record_failure(db, uname, ip)
        flash(request, "Usuario o contraseña incorrectos.", "error")
        return RedirectResponse("/login", 303)
    ratelimit.clear_failures(db, uname)
    if not user.is_active:
        flash(request, "Tu cuenta está suspendida. Contacta al administrador.", "error")
        return RedirectResponse("/login", 303)
    request.session.clear()  # nueva sesión al autenticar
    request.session["uid"] = user.id
    return RedirectResponse(HOME_BY_ROLE[user.role], 303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", 303)


@router.get("/register")
def register_page(request: Request, role: str = "client", user: User | None = Depends(current_user)):
    return render(request, "register.html", form={"role": role}, errors=[])


def _validate(d: dict[str, str], db: Session) -> list[str]:
    errors: list[str] = []
    if d["role"] not in ("client", "owner"):
        errors.append("Elige un tipo de cuenta válido.")
    if not USERNAME_RE.match(d["username"]):
        errors.append("Usuario: 3-30 caracteres, solo minúsculas, números o guion bajo.")
    if not EMAIL_RE.match(d["email"]) or len(d["email"]) > 254:
        errors.append("Correo electrónico inválido.")
    if not 8 <= len(d["password"]) or len(d["password"].encode()) > 72:
        errors.append("La contraseña debe tener entre 8 y 72 caracteres.")
    if len(d["full_name"]) < 3:
        errors.append("Escribe tu nombre completo.")
    if len(d["phone"]) < 7:
        errors.append("Escribe un teléfono válido.")
    if len(d["document_id"]) < 5:
        errors.append("Escribe tu documento de identidad o NIT.")
    if d["role"] == "owner" and len(d["business_name"]) < 2:
        errors.append("Los dueños deben indicar el nombre del negocio o marca.")
    if any(len(d[k]) > m for k, m in MAX_LEN.items()):
        errors.append("Alguno de los campos es demasiado largo.")
    if not errors and db.scalar(
        select(User.id).where(or_(User.username == d["username"], User.email == d["email"])).limit(1)
    ):
        errors.append("El usuario o el correo ya están registrados.")
    return errors


@router.post("/register")
def register(
    request: Request,
    role: str = Form(""),
    username: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    full_name: str = Form(""),
    phone: str = Form(""),
    document_id: str = Form(""),
    business_name: str = Form(""),
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    d = {
        "role": role, "username": username.strip().lower(), "email": email.strip().lower(),
        "password": password, "full_name": full_name.strip(), "phone": phone.strip(),
        "document_id": document_id.strip(), "business_name": business_name.strip(),
    }
    errors = _validate(d, db)
    if not errors:
        db.add(User(
            username=d["username"], email=d["email"], password_hash=hash_password(password),
            role=Role(d["role"]), full_name=d["full_name"], phone=d["phone"],
            document_id=d["document_id"],
            business_name=d["business_name"] if d["role"] == "owner" else None,
        ))
        try:
            db.commit()
        except IntegrityError:  # carrera entre dos registros iguales
            db.rollback()
            errors.append("El usuario o el correo ya están registrados.")
    if errors:
        form = {k: v for k, v in d.items() if k != "password"}
        return render(request, "register.html", status=422, form=form, errors=errors)
    flash(request, "Cuenta creada. Ya puedes iniciar sesión.", "success")
    return RedirectResponse("/login", 303)
