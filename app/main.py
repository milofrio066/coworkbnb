from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Role, User
from app.routers import admin, auth, bookings, owner, reviews, spaces
from app.security import hash_password
from app.web import render, verify_csrf

settings.upload_dir.mkdir(parents=True, exist_ok=True)


def seed_admin(db: Session) -> None:
    if db.scalar(select(User.id).where(User.role == Role.admin).limit(1)) is None:
        db.add(User(
            username=settings.admin_username.lower(), email=settings.admin_email.lower(),
            password_hash=hash_password(settings.admin_password), role=Role.admin,
            full_name="Administrador",
        ))
        db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)  # MVP; para producción migrar a Alembic
    with SessionLocal() as db:
        seed_admin(db)
    yield


app = FastAPI(title="CoworkBnb", lifespan=lifespan, dependencies=[Depends(verify_csrf)])
app.add_middleware(
    SessionMiddleware, secret_key=settings.secret_key, same_site="lax",
    https_only=settings.https_only, max_age=60 * 60 * 24 * 7,
)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir)), name="uploads")
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
for r in (auth, spaces, owner, bookings, reviews, admin):
    app.include_router(r.router)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return RedirectResponse("/login", 303)
    return render(request, "error.html", status=exc.status_code, message=str(exc.detail))


@app.exception_handler(RequestValidationError)
async def invalid_data(request: Request, exc: RequestValidationError):
    return render(request, "error.html", status=422, message="Los datos enviados no son válidos.")
