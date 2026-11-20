from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Booking, BookingStatus, Dispute, DisputeStatus, PaymentStatus, Space, SpaceStatus, User,
)
from app.payments import HOLD, cancel_booking, charge
from app.routers.reviews import reviewable_ids
from app.web import as_utc, flash, now_local, render, require_client, require_party, utcnow

router = APIRouter()


def user_disputes(db: Session, user: User) -> list[Dispute]:
    return list(db.scalars(
        select(Dispute).where(Dispute.opened_by_id == user.id)
        .options(selectinload(Dispute.booking).selectinload(Booking.space))
        .order_by(Dispute.id.desc())
    ))


def expire_holds(db: Session) -> None:
    """Libera los horarios retenidos que no se pagaron a tiempo."""
    db.execute(update(Booking).where(
        Booking.status == BookingStatus.pending_payment, Booking.created_at < utcnow() - HOLD,
    ).values(status=BookingStatus.cancelled))
    db.flush()


@router.get("/my/bookings")
def my_bookings(request: Request, db: Session = Depends(get_db), user: User = Depends(require_client)):
    expire_holds(db)
    db.commit()
    rows = list(db.scalars(
        select(Booking).where(Booking.client_id == user.id).options(selectinload(Booking.space))
        .order_by(Booking.day.desc(), Booking.start_hour.desc())
    ))
    return render(
        request, "my_bookings.html", bookings=rows, disputes=user_disputes(db, user),
        today=now_local().date(), reviewable=reviewable_ids(db, rows, user.id),
    )


@router.post("/spaces/{space_id}/book")
def book(
    space_id: int,
    request: Request,
    day: str = Form(...),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_client),
):
    """Retiene el horario (pendiente de pago); la reserva se confirma al pagar."""
    back = RedirectResponse(f"/spaces/{space_id}", 303)
    # Bloquea la fila del espacio: dos reservas simultáneas no pueden cruzarse (PostgreSQL)
    space = db.scalar(select(Space).where(Space.id == space_id).with_for_update())
    if space is None or space.status != SpaceStatus.approved:
        raise HTTPException(404, "Espacio no disponible.")
    try:
        d = date.fromisoformat(day)
    except ValueError:
        flash(request, "Fecha inválida.", "error")
        return back
    now = now_local()
    if not 0 <= start_hour < end_hour <= 24:
        flash(request, "Rango de horas inválido.", "error")
        return back
    if d < now.date() or (d == now.date() and start_hour <= now.hour):
        flash(request, "Elige un horario futuro.", "error")
        return back
    expire_holds(db)
    clash = db.scalar(
        select(Booking.id).where(
            Booking.space_id == space.id, Booking.day == d,
            Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending_payment]),
            Booking.start_hour < end_hour, Booking.end_hour > start_hour,
        ).limit(1)
    )
    if clash:
        db.rollback()
        flash(request, "Ese horario ya está reservado. Prueba con otro.", "error")
        return back
    b = Booking(
        space_id=space.id, client_id=user.id, day=d, start_hour=start_hour, end_hour=end_hour,
        total=space.price_per_hour * (end_hour - start_hour),
    )
    db.add(b)
    db.commit()
    return RedirectResponse(f"/bookings/{b.id}/pay", 303)


def _my_pending(db: Session, booking_id: int, user: User) -> Booking | None:
    expire_holds(db)
    b = db.get(Booking, booking_id)
    if b is None or b.client_id != user.id:
        raise HTTPException(404, "Reserva no encontrada.")
    return b if b.status == BookingStatus.pending_payment else None


@router.get("/bookings/{booking_id}/pay")
def pay_page(booking_id: int, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_client)):
    b = _my_pending(db, booking_id, user)
    db.commit()
    if b is None:
        flash(request, "Esta reserva ya no está pendiente de pago (puede haber expirado).", "error")
        return RedirectResponse("/my/bookings", 303)
    left = max(0, int((as_utc(b.created_at) + HOLD - utcnow()).total_seconds() // 60) + 1)
    return render(request, "pay.html", booking=b, minutes_left=left)


@router.post("/bookings/{booking_id}/pay")
def pay(booking_id: int, request: Request, card_number: str = Form(""), expiry: str = Form(""),
        cvv: str = Form(""), db: Session = Depends(get_db), user: User = Depends(require_client)):
    b = _my_pending(db, booking_id, user)
    if b is None:
        db.commit()
        flash(request, "La reserva expiró o ya fue procesada.", "error")
        return RedirectResponse("/my/bookings", 303)
    result = charge(card_number, expiry, cvv, now_local().date())  # pago SIMULADO
    if not result.ok:
        flash(request, result.message, "error")
        return RedirectResponse(f"/bookings/{b.id}/pay", 303)
    b.status, b.payment_status = BookingStatus.confirmed, PaymentStatus.paid
    b.payment_ref, b.paid_at = result.reference, utcnow()
    db.commit()
    flash(request, f"¡Pago aprobado! Reserva confirmada. Referencia {result.reference} (pago simulado).", "success")
    return RedirectResponse("/my/bookings", 303)


@router.post("/bookings/{booking_id}/cancel")
def cancel(booking_id: int, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require_client)):
    b = db.get(Booking, booking_id)
    if b is None or b.client_id != user.id:
        raise HTTPException(404, "Reserva no encontrada.")
    if b.status == BookingStatus.pending_payment or (
        b.status == BookingStatus.confirmed and b.day > now_local().date()
    ):
        paid = b.payment_status == PaymentStatus.paid
        cancel_booking(b)
        db.commit()
        flash(request, "Reserva cancelada." + (" Reembolso simulado procesado." if paid else ""), "success")
    else:
        flash(request, "Solo puedes cancelar reservas pendientes o confirmadas hasta el día anterior.", "error")
    return RedirectResponse("/my/bookings", 303)


def _party_booking(db: Session, booking_id: int, user: User) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None or b.status == BookingStatus.pending_payment or user.id not in (b.client_id, b.space.owner_id):
        raise HTTPException(404, "Reserva no encontrada.")
    return b


@router.get("/bookings/{booking_id}/dispute")
def dispute_form(booking_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_party)):
    return render(request, "dispute_form.html", booking=_party_booking(db, booking_id, user))


@router.post("/bookings/{booking_id}/dispute")
def open_dispute(booking_id: int, request: Request, reason: str = Form(""),
                 db: Session = Depends(get_db), user: User = Depends(require_party)):
    b = _party_booking(db, booking_id, user)
    reason = reason.strip()
    already = db.scalar(select(Dispute.id).where(
        Dispute.booking_id == b.id, Dispute.opened_by_id == user.id,
        Dispute.status == DisputeStatus.open,
    ).limit(1))
    if not 10 <= len(reason) <= 2000:
        flash(request, "Describe el problema (entre 10 y 2000 caracteres).", "error")
        return RedirectResponse(f"/bookings/{b.id}/dispute", 303)
    if already:
        flash(request, "Ya tienes una disputa abierta para esta reserva.", "error")
    else:
        db.add(Dispute(booking_id=b.id, opened_by_id=user.id, reason=reason))
        db.commit()
        flash(request, "Disputa enviada. El administrador la revisará.", "success")
    return RedirectResponse("/owner" if user.role.value == "owner" else "/my/bookings", 303)
