from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import AuditLog, Booking, BookingStatus, Dispute, PaymentStatus, Review, Space, User
from tests.helpers import SPACE, login, make_user, paid_booking, past_paid_booking, png_bytes, publish


def count(model) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model))


def test_space_is_hidden_until_approved(owner, admin, anon):
    sid = publish(owner)
    assert "Sala Centro" not in anon.get("/").text
    assert anon.get(f"/spaces/{sid}").status_code == 404
    admin.submit(f"/admin/spaces/{sid}/status", {"status": "approved", "note": ""})
    assert "Sala Centro" in anon.get("/").text


def test_space_needs_a_photo(owner):
    r = owner.submit("/owner/spaces", SPACE)
    assert r.status_code == 422 and "foto" in r.text


def test_non_image_upload_rejected(owner):
    r = owner.submit("/owner/spaces", SPACE, files=[("photos", ("x.png", b"no soy imagen", "image/png"))])
    assert r.status_code == 422 and "no es una imagen" in r.text
    assert count(Space) == 0 and not list(settings.upload_dir.iterdir())


def test_invalid_price_rejected(owner):
    r = owner.submit("/owner/spaces", {**SPACE, "price_per_hour": "20.000"},
                     files=[("photos", ("a.png", png_bytes(), "image/png"))])
    assert r.status_code == 422 and "Precio" in r.text


def test_editing_approved_space_goes_back_to_review(owner, approved_space, anon):
    owner.submit(f"/owner/spaces/{approved_space}/edit", {**SPACE, "title": "Nuevo título aprobado?"})
    assert anon.get(f"/spaces/{approved_space}").status_code == 404


def test_other_owner_cannot_edit_space(approved_space):
    intruso = make_user("owner", "otro_dueno")
    assert intruso.get(f"/owner/spaces/{approved_space}/edit").status_code == 404


def test_suspended_user_cannot_login(admin, anon):
    from tests.helpers import register
    register(anon, "client", "ana")
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == "ana"))
    admin.submit(f"/admin/users/{uid}/toggle")
    assert "suspendida" in login(anon, "ana").text


def test_admin_deletes_user_and_all_their_data(admin, cliente, owner, approved_space):
    bid = past_paid_booking(approved_space)
    cliente.submit(f"/bookings/{bid}/review", {"rating": "4", "comment": "Muy bien, volveré"})
    with SessionLocal() as db:
        owner_id = db.scalar(select(User.id).where(User.username == "dueno"))
    assert list(settings.upload_dir.iterdir())
    admin.submit(f"/admin/users/{owner_id}/delete")
    assert (count(User), count(Space), count(Booking), count(Review)) == (2, 0, 0, 0)  # admin + cliente
    assert not list(settings.upload_dir.iterdir())  # fotos borradas del disco
    with SessionLocal() as db:
        log = db.scalar(select(AuditLog).where(AuditLog.action == "user_delete"))
    assert "dueno" not in log.detail  # la auditoría no guarda datos personales


def test_admin_cannot_delete_admins(admin):
    with SessionLocal() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "admin"))
    assert admin.submit(f"/admin/users/{admin_id}/delete").status_code == 404


def test_dispute_resolution_cancels_and_refunds(admin, cliente, owner, approved_space):
    bid = paid_booking(cliente, approved_space)
    r = cliente.submit(f"/bookings/{bid}/dispute", {"reason": "El espacio no tenía wifi como decía"})
    assert "Disputa enviada" in r.text
    assert "wifi" in admin.get("/admin").text
    with SessionLocal() as db:
        did = db.scalar(select(Dispute.id))
    admin.submit(f"/admin/disputes/{did}/resolve", {"resolution": "Se reembolsa el pago", "cancel": "1"})
    with SessionLocal() as db:
        b = db.get(Booking, bid)
        assert (b.status, b.payment_status) == (BookingStatus.cancelled, PaymentStatus.refunded)
    assert "Se reembolsa el pago" in cliente.get("/my/bookings").text


def test_owner_can_open_dispute_but_strangers_cannot(owner, cliente, approved_space):
    bid = paid_booking(cliente, approved_space)
    assert owner.get(f"/bookings/{bid}/dispute").status_code == 200
    assert make_user("client", "cliente2").get(f"/bookings/{bid}/dispute").status_code == 404


def test_admin_dashboard_renders_with_data(admin, cliente, approved_space):
    bid = past_paid_booking(approved_space)
    cliente.submit(f"/bookings/{bid}/review", {"rating": "5", "comment": "Todo perfecto"})
    cliente.submit(f"/bookings/{bid}/dispute", {"reason": "Cobro duplicado en mi cuenta"})
    r = admin.get("/admin")
    assert r.status_code == 200 and "Todo perfecto" in r.text and "Cobro duplicado" in r.text
