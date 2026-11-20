from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Booking, BookingStatus, PaymentStatus, Review, User
from app.web import flash, now_local, render, require_client, require_owner

router = APIRouter()


def is_finished(b: Booking, now: datetime) -> bool:
    return b.day < now.date() or (b.day == now.date() and b.end_hour <= now.hour)


def reviewable_ids(db: Session, bookings: list[Booking], user_id: int) -> set[int]:
    now = now_local()
    reviewed = set(db.scalars(select(Review.booking_id).where(Review.author_id == user_id)))
    return {
        b.id for b in bookings
        if b.status == BookingStatus.confirmed and b.payment_status == PaymentStatus.paid
        and is_finished(b, now) and b.id not in reviewed
    }


def _own_booking(db: Session, booking_id: int, user: User) -> Booking:
    b = db.get(Booking, booking_id)
    if b is None or b.client_id != user.id:
        raise HTTPException(404, "Reserva no encontrada.")
    return b


def _problem(db: Session, b: Booking) -> str | None:
    if b.status != BookingStatus.confirmed or b.payment_status != PaymentStatus.paid:
        return "Solo puedes reseñar reservas pagadas que se realizaron."
    if not is_finished(b, now_local()):
        return "Podrás reseñar cuando termine tu reserva."
    if db.scalar(select(Review.id).where(Review.booking_id == b.id)):
        return "Ya reseñaste esta reserva."
    return None


@router.get("/bookings/{booking_id}/review")
def review_form(booking_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require_client)):
    b = _own_booking(db, booking_id, user)
    if problem := _problem(db, b):
        flash(request, problem, "error")
        return RedirectResponse("/my/bookings", 303)
    return render(request, "review_form.html", booking=b)


@router.post("/bookings/{booking_id}/review")
def create_review(booking_id: int, request: Request, rating: int = Form(...),
                  comment: str = Form(""), db: Session = Depends(get_db),
                  user: User = Depends(require_client)):
    b = _own_booking(db, booking_id, user)
    if problem := _problem(db, b):
        flash(request, problem, "error")
        return RedirectResponse("/my/bookings", 303)
    comment = comment.strip()
    if not 1 <= rating <= 5 or len(comment) > 1000:
        flash(request, "La calificación debe ser entre 1 y 5 y el comentario de máximo 1000 caracteres.", "error")
        return RedirectResponse(f"/bookings/{b.id}/review", 303)
    db.add(Review(booking_id=b.id, space_id=b.space_id, author_id=user.id, rating=rating, comment=comment))
    db.commit()
    flash(request, "¡Gracias por tu reseña!", "success")
    return RedirectResponse(f"/spaces/{b.space_id}", 303)


@router.post("/reviews/{review_id}/reply")
def reply(review_id: int, request: Request, text: str = Form(""), db: Session = Depends(get_db),
          user: User = Depends(require_owner)):
    """El dueño responde una sola vez a las reseñas de sus espacios."""
    r = db.get(Review, review_id)
    if r is None or r.space.owner_id != user.id:
        raise HTTPException(404, "Reseña no encontrada.")
    text = text.strip()
    if r.owner_reply:
        flash(request, "Ya respondiste esta reseña.", "error")
    elif not 2 <= len(text) <= 1000:
        flash(request, "La respuesta debe tener entre 2 y 1000 caracteres.", "error")
    else:
        r.owner_reply = text
        db.commit()
        flash(request, "Respuesta publicada.", "success")
    return RedirectResponse(f"/spaces/{r.space_id}", 303)
