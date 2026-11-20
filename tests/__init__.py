"""Pruebas sobre PostgreSQL, en una BD aparte (por defecto `cowork_test`). Debe ir antes de importar `app`."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="coworkbnb-test-"))
TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://cowork:cowork@localhost:5432/cowork_test")
if not TEST_DB.rsplit("/", 1)[-1].endswith("_test"):  # las pruebas borran todas las tablas
    raise RuntimeError("TEST_DATABASE_URL debe apuntar a una BD cuyo nombre termine en _test")
os.environ.update(
    DATABASE_URL=TEST_DB,
    UPLOAD_DIR=str(_tmp / "uploads"),
    SECRET_KEY="clave-de-pruebas",
    ADMIN_USERNAME="admin",
    ADMIN_PASSWORD="admin-pass-123",
    BCRYPT_ROUNDS="4",  # más rápido en pruebas
)
