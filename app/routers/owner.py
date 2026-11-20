from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Booking, BookingStatus, Space, SpacePhoto, SpaceStatus, User
from app.routers.bookings import user_disputes
from app.storage import delete_photos, save_uploads
from app.web import flash, render, require_owner

router = APIRouter(prefix="/owner")
FIELDS = ("title", "description", "city", "address", "price_per_hour", "capacity", "amenities")


def _clean(raw: dict[str, str]) -> tuple[dict[str, object], list[str]]:
    r = {k: v.strip() for k, v in raw.items()}
    errors: list[str] = []
    if not 5 <= len(r["title"]) <= 120:
        errors.append("El título debe tener entre 5 y 120 caracteres.")
    if not 20 <= len(r["description"]) <= 5000:
        errors.append("La descripción debe tener entre 20 y 5000 caracteres.")
    if not 2 <= len(r["city"]) <= 80:
        errors.append("Indica la ciudad.")
    if not 5 <= len(r["address"]) <= 200:
        errors.append("Indica la dirección.")
    if not (r["price_per_hour"].isdigit() and 0 < int(r["price_per_hour"]) <= 10_000_000):
        errors.append("Precio por hora: número entero en pesos, sin puntos ni comas.")
    if not (r["capacity"].isdigit() and 0 < int(r["capacity"]) <= 500):
        errors.append("Capacidad: número de personas entre 1 y 500.")
    if len(r["amenities"]) > 300:
        errors.append("Servicios: máximo 300 caracteres.")
    if errors:
        return {}, errors
    return {**r, "price_per_hour": Decimal(r["price_per_hour"]), "capacity": int(r["capacity"])}, []


def _own_space(db: Session, space_id: int, user: User) -> Space:
    space = db.get(Space, space_id)
    if space is None or space.owner_id != user.id:
        raise HTTPException(404, "Espacio no encontrado.")
    return space


@router.get("")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(require_owner)):
    spaces = db.scalars(
        select(Space).where(Space.owner_id == user.id)
        .options(selectinload(Space.photos)).order_by(Space.id.desc())
    ).all()
    bookings = db.scalars(
        select(Booking).join(Space)
        .where(Space.owner_id == user.id, Booking.status != BookingStatus.pending_payment)
        .options(selectinload(Booking.space), selectinload(Booking.client))
        .order_by(Booking.day.desc(), Booking.start_hour.desc()).limit(50)
    ).all()
    return render(request, "owner.html", spaces=spaces, bookings=bookings,
                  disputes=user_disputes(db, user))


@router.get("/spaces/new")
def new_form(request: Request, user: User = Depends(require_owner)):
    return render(request, "space_form.html", space=None, f={}, errors=[])


@router.post("/spaces")
def create(
    request: Request,
    title: str = Form(""), description: str = Form(""), city: str = Form(""),
    address: str = Form(""), price_per_hour: str = Form(""), capacity: str = Form(""),
    amenities: str = Form(""),
    photos: list[UploadFile] | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
):
    raw = dict(title=title, description=description, city=city, address=address,
               price_per_hour=price_per_hour, capacity=capacity, amenities=amenities)
    clean, errors = _clean(raw)
    names: list[str] = []
    if not errors:
        if not any(p.filename for p in photos or []):
            errors.append("Sube al menos una foto del espacio.")
        else:
            names, errors = save_uploads(photos, already=0)
    if errors:
        return render(request, "space_form.html", status=422, space=None, f=raw, errors=errors)
    space = Space(owner_id=user.id, **clean)
    space.photos = [SpacePhoto(filename=n) for n in names]
    db.add(space)
    db.commit()
    flash(request, "Espacio enviado. Aparecerá publicado cuando el administrador lo apruebe.", "success")
    return RedirectResponse("/owner", 303)


@router.get("/spaces/{space_id}/edit")
def edit_form(space_id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require_owner)):
    s = _own_space(db, space_id, user)
    f = {k: str(getattr(s, k)) for k in FIELDS}
    f["price_per_hour"] = str(int(s.price_per_hour))
    return render(request, "space_form.html", space=s, f=f, errors=[])


@router.post("/spaces/{space_id}/edit")
def edit(
    space_id: int,
    request: Request,
    title: str = Form(""), description: str = Form(""), city: str = Form(""),
    address: str = Form(""), price_per_hour: str = Form(""), capacity: str = Form(""),
    amenities: str = Form(""),
    photos: list[UploadFile] | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_owner),
):
    s = _own_space(db, space_id, user)
    raw = dict(title=title, description=description, city=city, address=address,
               price_per_hour=price_per_hour, capacity=capacity, amenities=amenities)
    clean, errors = _clean(raw)
    names: list[str] = []
    if not errors:
        names, errors = save_uploads(photos, already=len(s.photos))
    if errors:
        return render(request, "space_form.html", status=422, space=s, f=raw, errors=errors)
    sensitive_changed = any(getattr(s, k) != clean[k] for k in ("title", "description", "city", "address"))
    for k, v in clean.items():
        setattr(s, k, v)
    s.photos.extend(SpacePhoto(filename=n) for n in names)
    # Cambios de contenido o corrección tras rechazo vuelven a revisión del admin
    if s.status == SpaceStatus.rejected or (s.status == SpaceStatus.approved and (sensitive_changed or names)):
        s.status = SpaceStatus.pending
        s.admin_note = None
    db.commit()
    flash(request, "Cambios guardados.", "success")
    return RedirectResponse("/owner", 303)


@router.post("/photos/{photo_id}/delete")
def delete_photo(photo_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_owner)):
    p = db.get(SpacePhoto, photo_id)
    space = _own_space(db, p.space_id, user) if p else None
    if p is None or space is None:
        raise HTTPException(404, "Foto no encontrada.")
    if len(space.photos) <= 1:
        flash(request, "El espacio debe conservar al menos una foto.", "error")
    else:
        name = p.filename
        db.delete(p)
        db.commit()
        delete_photos([name])
    return RedirectResponse(f"/owner/spaces/{space.id}/edit", 303)


@router.post("/spaces/{space_id}/delete")
def delete_space(space_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require_owner)):
    s = _own_space(db, space_id, user)
    if db.scalar(select(func.count()).select_from(Booking).where(Booking.space_id == s.id)):
        flash(request, "Este espacio tiene reservas asociadas; pide al administrador desactivarlo.", "error")
    else:
        names = [p.filename for p in s.photos]
        db.delete(s)
        db.commit()
        delete_photos(names)
        flash(request, "Espacio eliminado.", "success")
    return RedirectResponse("/owner", 303)
