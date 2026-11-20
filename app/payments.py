"""Pasarela SIMULADA: no cobra nada. Solo valida el formato y devuelve una referencia falsa.

Tarjetas de prueba:  4242 4242 4242 4242 -> aprobada
                     4000 0000 0000 0002 -> rechazada
                     4000 0000 0000 9995 -> fondos insuficientes
No se guarda ningún dato de tarjeta, solo la referencia del pago.
"""
import re
import secrets
from dataclasses import dataclass
from datetime import date, timedelta

from app.models import Booking, BookingStatus, PaymentStatus

HOLD = timedelta(minutes=15)  # tiempo que se retiene el horario mientras se paga
DECLINED = {
    "4000000000000002": "Tarjeta rechazada por el banco.",
    "4000000000009995": "Fondos insuficientes.",
}


@dataclass(frozen=True)
class PaymentResult:
    ok: bool
    message: str = ""
    reference: str | None = None


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number]
    total = sum(digits[-1::-2]) + sum(sum(divmod(d * 2, 10)) for d in digits[-2::-2])
    return total % 10 == 0


def charge(card_number: str, expiry: str, cvv: str, today: date) -> PaymentResult:
    number = re.sub(r"[\s-]", "", card_number)
    if not (number.isdigit() and 13 <= len(number) <= 19 and luhn_ok(number)):
        return PaymentResult(False, "Número de tarjeta inválido.")
    m = re.fullmatch(r"(\d{2})/(\d{2})", expiry.strip())
    if not m or not 1 <= int(m[1]) <= 12:
        return PaymentResult(False, "Fecha de vencimiento inválida (usa MM/AA).")
    if (2000 + int(m[2]), int(m[1])) < (today.year, today.month):
        return PaymentResult(False, "La tarjeta está vencida.")
    if not re.fullmatch(r"\d{3,4}", cvv.strip()):
        return PaymentResult(False, "CVV inválido.")
    if number in DECLINED:
        return PaymentResult(False, DECLINED[number])
    return PaymentResult(True, reference="SIM-" + secrets.token_hex(5).upper())


def cancel_booking(b: Booking) -> None:
    """Cancela la reserva y, si estaba pagada, simula el reembolso."""
    b.status = BookingStatus.cancelled
    if b.payment_status == PaymentStatus.paid:
        b.payment_status = PaymentStatus.refunded
