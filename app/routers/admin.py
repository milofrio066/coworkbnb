from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    AuditLog, Booking, Dispute, DisputeStatus, Review, Role, Space, SpacePhoto,
    SpaceStatus, User,
)
from app.payments import cancel_booking
from app.storage import delete_photos
from app.web import flash, render, require_admin

router = APIRouter(prefix="/admin")


def _back() -> RedirectResponse:
    return RedirectResponse("/admin", 303)


def _audit(db: Session, admin: User, action: str, detail: str) -> None:
    db.add(AuditLog(admin_username=admin.username, action=action, detail=detail))


def _count(db: Session, model: type, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


@router.get("")
def dashboard(request: Request, q: str = "", db: Session = Depends(get_db),
              admin: User = Depends(require_admin)):
    pending = db.scalars(select(Space).where(Space.status == SpaceStatus.pending)
                         .options(selectinload(Space.photos)).order_by(Space.id)).all()
    others = db.scalars(select(Space).where(Space.status != SpaceStatus.pending)
                        .options(selectinload(Space.photos)).order_by(Space.id.desc()).limit(100)).all()
    disputes = db.scalars(select(Dispute).where(Dispute.status == DisputeStatus.open)
                          .order_by(Dispute.id)).all()
    uq = select(User)
    if q.strip():
        pat = f"%{q.strip()}%"
        uq = uq.where(or_(User.username.ilike(pat), User.full_name.ilike(pat), User.email.ilike(pat)))
    users = db.scalars(uq.order_by(User.id.desc()).limit(100)).all()
    stats = {
        "Clientes": _count(db, User, User.role == Role.client),
        "Dueños": _count(db, User, User.role == Role.owner),
        "Espacios": _count(db, Space),
        "Por aprobar": len(pending),
        "Reservas": _count(db, Booking),
        "Disputas abiertas": len(disputes),
    }
    audit = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(30)).all()
    reviews = db.scalars(select(Review).order_by(Review.id.desc()).limit(20)).all()
    return render(request, "admin.html", stats=stats, pending=pending, others=others,
                  disputes=disputes, users=users, q=q, audit=audit, reviews=reviews)


@router.post("/spaces/{space_id}/status")
def set_status(space_id: int, request: Request, status: str = Form(...), note: str = Form(""),
               db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    space = db.get(Space, space_id)
    if space is None:
        raise HTTPException(404, "Espacio no encontrado.")
    try:
        new = SpaceStatus(status)
    except ValueError:
        raise HTTPException(400, "Estado inválido.") from None
    if new == SpaceStatus.pending:
        raise HTTPException(400, "Estado inválido.")
    space.status, space.admin_note = new, note.strip()[:500] or None
    _audit(db, admin, "space_status", f"space={space.id} -> {new.value}")
    db.commit()
    flash(request, f"Espacio #{space.id}: {new.value}.", "success")
    return _back()


@router.post("/spaces/{space_id}/delete")
def delete_space(space_id: int, request: Request, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    space = db.get(Space, space_id)
    if space is None:
        raise HTTPException(404, "Espacio no encontrado.")
    names = [p.filename for p in space.photos]
    _audit(db, admin, "space_delete", f"space={space.id}")
    db.delete(space)
    db.commit()
    delete_photos(names)
    flash(request, "Espacio eliminado con sus fotos, reservas y disputas.", "success")
    return _back()


@router.post("/photos/{photo_id}/delete")
def delete_photo(photo_id: int, request: Request, db: Session = Depends(get_db),
                 admin: User = Depends(require_admin)):
    photo = db.get(SpacePhoto, photo_id)
    if photo is None:
        raise HTTPException(404, "Foto no encontrada.")
    name = photo.filename
    _audit(db, admin, "photo_delete", f"photo={photo.id} space={photo.space_id}")
    db.delete(photo)
    db.commit()
    delete_photos([name])
    flash(request, "Foto eliminada.", "success")
    return _back()


def _target_user(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None or target.role == Role.admin:
        raise HTTPException(404, "Usuario no encontrado.")
    return target


@router.post("/users/{user_id}/toggle")
def toggle_user(user_id: int, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    target = _target_user(db, user_id)
    target.is_active = not target.is_active
    _audit(db, admin, "user_toggle", f"user={target.id} active={target.is_active}")
    db.commit()
    flash(request, "Usuario activado." if target.is_active else "Usuario suspendido.", "success")
    return _back()


@router.post("/users/{user_id}/delete")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    """Supresión de datos personales: borra cuenta, espacios, fotos, reservas y disputas."""
    target = _target_user(db, user_id)
    files = list(db.scalars(select(SpacePhoto.filename).join(Space).where(Space.owner_id == target.id)))
    _audit(db, admin, "user_delete", f"user={target.id} role={target.role.value}")  # sin datos personales
    db.delete(target)
    db.commit()
    delete_photos(files)
    flash(request, "Usuario y toda su información eliminados.", "success")
    return _back()


@router.post("/bookings/{booking_id}/delete")
def delete_booking(booking_id: int, request: Request, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    b = db.get(Booking, booking_id)
    if b is None:
        raise HTTPException(404, "Reserva no encontrada.")
    _audit(db, admin, "booking_delete", f"booking={b.id}")
    db.delete(b)
    db.commit()
    flash(request, "Reserva eliminada.", "success")
    return _back()


@router.post("/disputes/{dispute_id}/resolve")
def resolve(dispute_id: int, request: Request, resolution: str = Form(""), cancel: str = Form(""),
            db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    d = db.get(Dispute, dispute_id)
    if d is None or d.status != DisputeStatus.open:
        raise HTTPException(404, "Disputa no encontrada.")
    if len(resolution.strip()) < 5:
        flash(request, "Escribe la resolución para las partes.", "error")
        return _back()
    d.status, d.resolution = DisputeStatus.resolved, resolution.strip()[:2000]
    d.resolved_by, d.resolved_at = admin.username, datetime.now(timezone.utc)
    if cancel:
        cancel_booking(d.booking)  # reembolso simulado si estaba pagada
    _audit(db, admin, "dispute_resolve", f"dispute={d.id} booking={d.booking_id} cancelled={bool(cancel)}")
    db.commit()
    flash(request, "Disputa resuelta.", "success")
    return _back()


@router.post("/reviews/{review_id}/delete")
def delete_review(review_id: int, request: Request, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    r = db.get(Review, review_id)
    if r is None:
        raise HTTPException(404, "Reseña no encontrada.")
    _audit(db, admin, "review_delete", f"review={r.id} space={r.space_id}")
    db.delete(r)
    db.commit()
    flash(request, "Reseña eliminada.", "success")
    return _back()
