from datetime import date

import pytest

from app.models import Booking, BookingStatus, PaymentStatus
from app.payments import cancel_booking, charge

TODAY = date(2026, 1, 15)


@pytest.mark.parametrize("number,ok", [
    ("4242424242424242", True), ("4242 4242 4242 4242", True), ("4242-4242-4242-4242", True),
    ("4242424242424241", False), ("abcd", False), ("", False),
])
def test_card_number(number, ok):
    assert charge(number, "12/40", "123", TODAY).ok is ok


def test_approved_returns_reference():
    r = charge("4242424242424242", "12/40", "123", TODAY)
    assert r.ok and r.reference.startswith("SIM-")


@pytest.mark.parametrize("number,msg", [
    ("4000000000000002", "rechazada"), ("4000000000009995", "Fondos insuficientes"),
])
def test_simulated_declines(number, msg):
    r = charge(number, "12/40", "123", TODAY)
    assert not r.ok and msg in r.message


@pytest.mark.parametrize("expiry,cvv,msg", [
    ("01/25", "123", "vencida"), ("13/30", "123", "vencimiento"), ("1230", "123", "vencimiento"),
    ("12/40", "12", "CVV"), ("12/40", "abc", "CVV"),
])
def test_bad_expiry_or_cvv(expiry, cvv, msg):
    r = charge("4242424242424242", expiry, cvv, TODAY)
    assert not r.ok and msg in r.message


def test_cancel_paid_booking_refunds():
    b = Booking(status=BookingStatus.confirmed, payment_status=PaymentStatus.paid)
    cancel_booking(b)
    assert b.status == BookingStatus.cancelled and b.payment_status == PaymentStatus.refunded


def test_cancel_unpaid_booking_stays_unpaid():
    b = Booking(status=BookingStatus.pending_payment, payment_status=PaymentStatus.unpaid)
    cancel_booking(b)
    assert b.status == BookingStatus.cancelled and b.payment_status == PaymentStatus.unpaid
