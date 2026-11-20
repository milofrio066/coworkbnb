from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Booking, BookingStatus, Review, Role, Space, SpaceStatus, User
from app.web import current_user, now_local, render

router = APIRouter()

# Categorías rápidas del catálogo (filtran por los servicios que declara el dueño)
CATEGORIES = [
    ("", "✨", "Todos"),
    ("sala", "🗣️", "Salas de reunión"),
    ("café", "☕", "Con café"),
    ("terraza", "🌿", "Terraza"),
    ("parqueadero", "🚗", "Parqueadero"),
    ("24", "🕒", "24 horas"),
    ("proyector", "📽️", "Proyector"),
    ("mascota", "🐾", "Pet friendly"),
]
SORTS = {
    "recent": ("Más recientes", Space.id.desc()),
    "price_asc": ("Precio: menor a mayor", Space.price_per_hour.asc()),
    "price_desc": ("Precio: mayor a menor", Space.price_per_hour.desc()),
    "capacity": ("Mayor capacidad", Space.capacity.desc()),
}


def _num(value: str) -> int | None:
    return int(value) if value.strip().isdigit() else None


@router.get("/")
def home(
    request: Request,
    city: str = "",
    min_capacity: str = "",
    max_price: str = "",
    amenity: str = "",
    sort: str = "recent",
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    q = select(Space).where(Space.status == SpaceStatus.approved)
    if city.strip():
        q = q.where(Space.city.ilike(f"%{city.strip()}%"))
    if (cap := _num(min_capacity)) is not None:
        q = q.where(Space.capacity >= cap)
    if (price := _num(max_price)) is not None:
        q = q.where(Space.price_per_hour <= price)
    if amenity.strip():
        q = q.where(Space.amenities.ilike(f"%{amenity.strip()[:40]}%"))
    order = SORTS.get(sort, SORTS["recent"])[1]
    spaces = db.scalars(q.options(selectinload(Space.photos)).order_by(order, Space.id.desc()).limit(60)).all()
    rows = db.execute(
        select(Review.space_id, func.avg(Review.rating), func.count())
        .where(Review.space_id.in_([s.id for s in spaces])).group_by(Review.space_id)
    ).all()
    ratings = {sid: (float(avg), n) for sid, avg, n in rows}
    approved = Space.status == SpaceStatus.approved
    totals = {
        "spaces": db.scalar(select(func.count()).select_from(Space).where(approved)) or 0,
        "cities": db.scalar(select(func.count(func.distinct(func.lower(Space.city)))).where(approved)) or 0,
        "reviews": db.scalar(select(func.count()).select_from(Review)) or 0,
    }
    f = {"city": city, "min_capacity": min_capacity, "max_price": max_price, "amenity": amenity, "sort": sort}
    filtered = any(v.strip() for k, v in f.items() if k != "sort")
    return render(request, "home.html", spaces=spaces, f=f, ratings=ratings, categories=CATEGORIES,
                  sorts=SORTS, totals=totals, filtered=filtered)


def _visible_space(db: Session, space_id: int, user: User | None) -> Space:
    space = db.get(Space, space_id)
    can_see = space is not None and (
        space.status == SpaceStatus.approved
        or (user is not None and (user.role == Role.admin or user.id == space.owner_id))
    )
    if not can_see:
        raise HTTPException(404, "Espacio no encontrado.")
    return space


@router.get("/spaces/{space_id}")
def detail(
    space_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User | None = Depends(current_user),
):
    space = _visible_space(db, space_id, user)
    reviews = db.scalars(
        select(Review).where(Review.space_id == space.id)
        .options(selectinload(Review.author)).order_by(Review.id.desc()).limit(50)
    ).all()
    avg, count = db.execute(
        select(func.avg(Review.rating), func.count()).where(Review.space_id == space.id)
    ).one()
    host_spaces = db.scalar(select(func.count()).select_from(Space).where(
        Space.owner_id == space.owner_id, Space.status == SpaceStatus.approved)) or 0
    return render(request, "space_detail.html", space=space, reviews=reviews,
                  avg=float(avg) if avg is not None else None, count=count,
                  today=now_local().date().isoformat(), host_spaces=host_spaces)


@router.get("/spaces/{space_id}/availability")
def availability(space_id: int, day: str, db: Session = Depends(get_db),
                 user: User | None = Depends(current_user)):
    """Horas ocupadas de un día (confirmadas o retenidas). No expone quién reservó."""
    space = _visible_space(db, space_id, user)
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(400, "Fecha inválida.") from None
    from app.routers.bookings import expire_holds  # evita import circular
    expire_holds(db)
    db.commit()
    taken: set[int] = set()
    for start, end in db.execute(select(Booking.start_hour, Booking.end_hour).where(
        Booking.space_id == space.id, Booking.day == d,
        Booking.status.in_([BookingStatus.confirmed, BookingStatus.pending_payment]),
    )):
        taken.update(range(start, end))
    now = now_local()
    past = list(range(0, now.hour + 1)) if d == now.date() else (list(range(24)) if d < now.date() else [])
    return {"day": d.isoformat(), "taken": sorted(taken), "past": past}
