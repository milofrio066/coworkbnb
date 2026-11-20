import io
import re
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.database import SessionLocal
from app.main import app
from app.models import Booking, BookingStatus, PaymentStatus, Space, User
from app.web import now_local

CSRF_RE = re.compile(r'name="csrf" value="([^"]+)"')
GOOD_CARD = {"card_number": "4242 4242 4242 4242", "expiry": "12/40", "cvv": "123"}
SPACE = dict(
    title="Sala Centro", description="Un espacio luminoso con buena conexión y café.",
    city="Pereira", address="Calle 19 #8-30", price_per_hour="20000", capacity="6", amenities="wifi",
)


class Client(TestClient):
    """TestClient que agrega solo el token CSRF a cada POST."""

    def token(self) -> str:
        return CSRF_RE.search(self.get("/login").text).group(1)

    def submit(self, url: str, data: dict | None = None, files=None):
        return self.post(url, data={**(data or {}), "csrf": self.token()}, files=files)


def register(c: Client, role: str, username: str, **extra):
    data = dict(
        role=role, username=username, email=f"{username}@example.com", password="password123",
        full_name=f"{username.title()} Perez", phone="3001234567", document_id="123456789",
    )
    if role == "owner":
        data["business_name"] = "Mi Negocio"
    return c.submit("/register", {**data, **extra})


def login(c: Client, username: str, password: str = "password123"):
    return c.submit("/login", {"username": username, "password": password})


def make_user(role: str, username: str) -> Client:
    c = Client(app)
    register(c, role, username)
    login(c, username)
    return c


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "PNG")
    return buf.getvalue()


def publish(owner: Client) -> int:
    owner.submit("/owner/spaces", SPACE, files=[("photos", ("a.png", png_bytes(), "image/png"))])
    with SessionLocal() as db:
        return db.scalar(select(func.max(Space.id)))


def future(days: int = 3):
    return now_local().date() + timedelta(days=days)


def reserve(c: Client, space_id: int, day, start: int = 9, end: int = 11):
    return c.submit(f"/spaces/{space_id}/book",
                    {"day": day.isoformat(), "start_hour": start, "end_hour": end})


def last_booking_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.max(Booking.id)))


def pay(c: Client, booking_id: int, card: dict | None = None):
    return c.submit(f"/bookings/{booking_id}/pay", card or GOOD_CARD)


def paid_booking(c: Client, space_id: int, day=None, start: int = 9, end: int = 11) -> int:
    reserve(c, space_id, day or future(), start, end)
    bid = last_booking_id()
    pay(c, bid)
    return bid


def past_paid_booking(space_id: int, username: str = "cliente") -> int:
    """Reserva ya pagada y terminada (ayer), creada directo en la BD."""
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        b = Booking(
            space_id=space_id, client_id=user.id, day=now_local().date() - timedelta(days=1),
            start_hour=9, end_hour=11, total=Decimal("40000"), status=BookingStatus.confirmed,
            payment_status=PaymentStatus.paid, payment_ref="SIM-TEST",
        )
        db.add(b)
        db.commit()
        return b.id
