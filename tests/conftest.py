import pytest

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app, seed_admin
from tests.helpers import Client, login, make_user, publish


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    for f in settings.upload_dir.iterdir():  # fotos de pruebas anteriores
        f.unlink()
    with SessionLocal() as db:
        seed_admin(db)


@pytest.fixture
def anon() -> Client:
    return Client(app)


@pytest.fixture
def admin() -> Client:
    c = Client(app)
    login(c, "admin", "admin-pass-123")
    return c


@pytest.fixture
def owner() -> Client:
    return make_user("owner", "dueno")


@pytest.fixture
def cliente() -> Client:
    return make_user("client", "cliente")


@pytest.fixture
def approved_space(owner, admin) -> int:
    sid = publish(owner)
    admin.submit(f"/admin/spaces/{sid}/status", {"status": "approved", "note": ""})
    return sid
