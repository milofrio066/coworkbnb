from sqlalchemy import select

from app.database import SessionLocal
from app.models import Review
from tests.helpers import future, last_booking_id, make_user, paid_booking, past_paid_booking, reserve

REVIEW = {"rating": "5", "comment": "Excelente lugar para trabajar"}


def review_id() -> int:
    with SessionLocal() as db:
        return db.scalar(select(Review.id))


def test_review_after_finished_paid_booking(cliente, approved_space, anon):
    bid = past_paid_booking(approved_space)
    assert "Dejar reseña" in cliente.get("/my/bookings").text
    r = cliente.submit(f"/bookings/{bid}/review", REVIEW)
    assert "Gracias por tu reseña" in r.text and "Excelente lugar" in r.text
    assert "5.0 (1)" in anon.get("/").text  # promedio en el catálogo


def test_cannot_review_twice(cliente, approved_space):
    bid = past_paid_booking(approved_space)
    cliente.submit(f"/bookings/{bid}/review", REVIEW)
    assert "Ya reseñaste" in cliente.submit(f"/bookings/{bid}/review", REVIEW).text


def test_cannot_review_future_booking(cliente, approved_space):
    bid = paid_booking(cliente, approved_space)
    assert "cuando termine" in cliente.submit(f"/bookings/{bid}/review", REVIEW).text


def test_cannot_review_unpaid_booking(cliente, approved_space):
    reserve(cliente, approved_space, future())
    r = cliente.submit(f"/bookings/{last_booking_id()}/review", REVIEW)
    assert "reservas pagadas" in r.text


def test_rating_must_be_1_to_5(cliente, approved_space):
    bid = past_paid_booking(approved_space)
    assert "entre 1 y 5" in cliente.submit(f"/bookings/{bid}/review", {**REVIEW, "rating": "6"}).text
    assert review_id() is None


def test_only_the_booking_client_can_review(cliente, approved_space):
    bid = past_paid_booking(approved_space)
    assert make_user("client", "cliente2").submit(f"/bookings/{bid}/review", REVIEW).status_code == 404


def test_owner_replies_once(cliente, owner, approved_space):
    cliente.submit(f"/bookings/{past_paid_booking(approved_space)}/review", REVIEW)
    rid = review_id()
    assert "Respuesta del anfitrión" in owner.submit(f"/reviews/{rid}/reply", {"text": "¡Gracias por venir!"}).text
    assert "Ya respondiste" in owner.submit(f"/reviews/{rid}/reply", {"text": "Otra vez"}).text


def test_other_owner_cannot_reply(cliente, approved_space):
    cliente.submit(f"/bookings/{past_paid_booking(approved_space)}/review", REVIEW)
    intruso = make_user("owner", "otro_dueno")
    assert intruso.submit(f"/reviews/{review_id()}/reply", {"text": "Hola"}).status_code == 404


def test_admin_deletes_review(cliente, admin, approved_space, anon):
    cliente.submit(f"/bookings/{past_paid_booking(approved_space)}/review", REVIEW)
    admin.submit(f"/admin/reviews/{review_id()}/delete")
    assert "Excelente lugar" not in anon.get(f"/spaces/{approved_space}").text
