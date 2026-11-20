from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, enum.Enum):
    client = "client"
    owner = "owner"
    admin = "admin"


class SpaceStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"


class BookingStatus(str, enum.Enum):
    pending_payment = "pending_payment"  # bloquea el horario 15 min mientras se paga
    confirmed = "confirmed"
    cancelled = "cancelled"


class PaymentStatus(str, enum.Enum):
    unpaid = "unpaid"
    paid = "paid"
    refunded = "refunded"


class DisputeStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


def _enum(e: type[enum.Enum]) -> Enum:
    # VARCHAR en vez de tipo ENUM nativo: más fácil de migrar
    return Enum(e, native_enum=False, length=20)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # se guarda en minúsculas
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(_enum(Role))
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(30))
    document_id: Mapped[str | None] = mapped_column(String(30))  # cédula / NIT
    business_name: Mapped[str | None] = mapped_column(String(120))  # solo dueños
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = _now()

    spaces: Mapped[list[Space]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )


class Space(Base):
    __tablename__ = "spaces"
    __table_args__ = (
        Index("ix_spaces_status_city", "status", "city"),
        CheckConstraint("price_per_hour > 0", name="ck_space_price"),
        CheckConstraint("capacity > 0", name="ck_space_capacity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(200))
    price_per_hour: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    capacity: Mapped[int]
    amenities: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[SpaceStatus] = mapped_column(_enum(SpaceStatus), default=SpaceStatus.pending)
    admin_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    owner: Mapped[User] = relationship(back_populates="spaces")
    photos: Mapped[list[SpacePhoto]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="SpacePhoto.id"
    )
    bookings: Mapped[list[Booking]] = relationship(
        back_populates="space", cascade="all, delete-orphan", passive_deletes=True
    )


class SpacePhoto(Base):
    __tablename__ = "space_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(100))


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_space_day", "space_id", "day"),
        CheckConstraint(
            "start_hour >= 0 AND end_hour <= 24 AND start_hour < end_hour", name="ck_booking_hours"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    start_hour: Mapped[int]
    end_hour: Mapped[int]
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[BookingStatus] = mapped_column(_enum(BookingStatus), default=BookingStatus.pending_payment)
    payment_status: Mapped[PaymentStatus] = mapped_column(_enum(PaymentStatus), default=PaymentStatus.unpaid)
    payment_ref: Mapped[str | None] = mapped_column(String(40))  # referencia simulada; nunca datos de tarjeta
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    review: Mapped[Review | None] = relationship(
        back_populates="booking", cascade="all, delete-orphan", passive_deletes=True
    )
    space: Mapped[Space] = relationship(back_populates="bookings")
    client: Mapped[User] = relationship()
    disputes: Mapped[list[Dispute]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", passive_deletes=True
    )


class Dispute(Base):
    __tablename__ = "disputes"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), index=True)
    opened_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[DisputeStatus] = mapped_column(_enum(DisputeStatus), default=DisputeStatus.open)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(String(30))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()

    booking: Mapped[Booking] = relationship(back_populates="disputes")
    opened_by: Mapped[User] = relationship()


class AuditLog(Base):
    """Registro de acciones del admin. Sin FKs ni datos personales: sobrevive a borrados legales."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_username: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(50))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class Review(Base):
    """Una reseña por reserva pagada y finalizada; el dueño puede responder una vez."""

    __tablename__ = "reviews"
    __table_args__ = (CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), unique=True)
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[int]
    comment: Mapped[str] = mapped_column(Text, default="")
    owner_reply: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()

    booking: Mapped[Booking] = relationship(back_populates="review")
    space: Mapped[Space] = relationship()
    author: Mapped[User] = relationship()


class LoginFailure(Base):
    """Intentos de login fallidos (en BD para que el límite funcione con varios procesos)."""

    __tablename__ = "login_failures"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), index=True)
    ip: Mapped[str] = mapped_column(String(45), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
