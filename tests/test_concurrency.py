from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import Booking
from tests.helpers import future, make_user, reserve


def test_simultaneous_reservations_never_overlap(approved_space):
    """Con PostgreSQL, el FOR UPDATE sobre el espacio deja pasar solo una de las reservas."""
    clients = [make_user("client", f"cliente{i}") for i in range(6)]
    day = future()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda c: reserve(c, approved_space, day, 9, 11), clients))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Booking)) == 1
