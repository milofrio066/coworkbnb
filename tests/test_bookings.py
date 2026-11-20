from datetime import timedelta

from sqlalchemy import func, select, update

from app.database import SessionLocal
from app.models import Booking, BookingStatus, PaymentStatus
from app.web import now_local, utcnow
from tests.helpers import (
    GOOD_CARD, future, last_booking_id, make_user, paid_booking, pay, reserve,
)


def booking(bid: int) -> Booking:
    with SessionLocal() as db:
        return db.get(Booking, bid)


def test_reserve_holds_slot_until_paid(cliente, approved_space):
    r = reserve(cliente, approved_space, future())
    assert r.url.path.endswith("/pay") and "$40.000" in r.text
    b = booking(last_booking_id())
    assert (b.status, b.payment_status) == (BookingStatus.pending_payment, PaymentStatus.unpaid)


def test_payment_confirms_booking(cliente, approved_space):
    bid = paid_booking(cliente, approved_space)
    b = booking(bid)
    assert (b.status, b.payment_status) == (BookingStatus.confirmed, PaymentStatus.paid)
    assert b.payment_ref.startswith("SIM-") and b.paid_at is not None
    assert "Pagada" in cliente.get("/my/bookings").text


def test_declined_card_keeps_booking_pending(cliente, approved_space):
    reserve(cliente, approved_space, future())
    bid = last_booking_id()
    r = pay(cliente, bid, {**GOOD_CARD, "card_number": "4000 0000 0000 0002"})
    assert "rechazada" in r.text
    assert booking(bid).status == BookingStatus.pending_payment


def test_pending_hold_blocks_other_clients(cliente, approved_space):
    reserve(cliente, approved_space, future())
    otro = make_user("client", "cliente2")
    assert "ya está reservado" in reserve(otro, approved_space, future(), 10, 12).text


def test_expired_hold_frees_the_slot(cliente, approved_space):
    reserve(cliente, approved_space, future())
    bid = last_booking_id()
    with SessionLocal() as db:
        db.execute(update(Booking).where(Booking.id == bid).values(created_at=utcnow() - timedelta(minutes=16)))
        db.commit()
    otro = make_user("client", "cliente2")
    assert reserve(otro, approved_space, future(), 10, 12).url.path.endswith("/pay")
    assert booking(bid).status == BookingStatus.cancelled


def test_cannot_pay_expired_booking(cliente, approved_space):
    reserve(cliente, approved_space, future())
    bid = last_booking_id()
    with SessionLocal() as db:
        db.execute(update(Booking).where(Booking.id == bid).values(created_at=utcnow() - timedelta(minutes=20)))
        db.commit()
    assert "expiró" in pay(cliente, bid).text
    assert booking(bid).payment_status == PaymentStatus.unpaid


def test_confirmed_slot_blocks_but_adjacent_hours_are_free(cliente, approved_space):
    paid_booking(cliente, approved_space, future(), 9, 11)
    otro = make_user("client", "cliente2")
    assert "ya está reservado" in reserve(otro, approved_space, future(), 10, 12).text
    assert reserve(otro, approved_space, future(), 11, 13).url.path.endswith("/pay")


def test_past_date_and_bad_range_rejected(cliente, approved_space):
    assert "horario futuro" in reserve(cliente, approved_space, now_local().date() - timedelta(days=1)).text
    assert "Rango de horas" in reserve(cliente, approved_space, future(), 11, 9).text
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Booking)) == 0


def test_owner_cannot_book(owner, approved_space):
    assert reserve(owner, approved_space, future()).status_code == 403


def test_unapproved_space_cannot_be_booked(cliente, owner):
    from tests.helpers import publish
    sid = publish(owner)
    assert reserve(cliente, sid, future()).status_code == 404


def test_other_client_cannot_pay_my_booking(cliente, approved_space):
    reserve(cliente, approved_space, future())
    bid = last_booking_id()
    assert pay(make_user("client", "cliente2"), bid).status_code == 404


def test_cancel_paid_booking_refunds(cliente, approved_space):
    bid = paid_booking(cliente, approved_space)
    assert "Reembolso" in cliente.submit(f"/bookings/{bid}/cancel").text
    b = booking(bid)
    assert (b.status, b.payment_status) == (BookingStatus.cancelled, PaymentStatus.refunded)


def test_cancel_pending_booking(cliente, approved_space):
    reserve(cliente, approved_space, future())
    bid = last_booking_id()
    cliente.submit(f"/bookings/{bid}/cancel")
    assert booking(bid).status == BookingStatus.cancelled


def test_owner_sees_only_paid_bookings(cliente, owner, approved_space):
    reserve(cliente, approved_space, future())
    assert "Cliente Perez" not in owner.get("/owner").text  # pendiente de pago: aún no
    pay(cliente, last_booking_id())
    assert "Cliente Perez" in owner.get("/owner").text
