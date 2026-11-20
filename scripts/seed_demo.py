"""Carga datos de demostración: anfitriones, clientes, espacios con fotos, reservas, reseñas y una disputa.

Uso (desde la raíz del proyecto, con el venv activo):
    python -m scripts.seed_demo          # agrega los datos si no existen
    python -m scripts.seed_demo --reset  # BORRA TODA la base y la vuelve a llenar

Todas las cuentas de demo usan la clave `demo12345`. Las fotos son ilustraciones generadas (no fotos reales).
"""
import random
import sys
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import select

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import seed_admin
from app.models import (
    Booking, BookingStatus, Dispute, PaymentStatus, Review, Role, Space, SpacePhoto, SpaceStatus, User,
)
from app.security import hash_password
from app.web import now_local

PASSWORD = "demo12345"

OWNERS = [
    ("andes_hub", "Camila Restrepo", "Andes Hub", "3104567890", "901234567"),
    ("caribe_work", "Andrés Pertuz", "Caribe Work", "3159876543", "900765432"),
    ("cafe_estudio", "Julián Ospina", "Café Estudio", "3201112233", "1088123456"),
]
CLIENTS = [
    ("laura", "Laura Gómez", "3001234567", "1020304050"),
    ("mateo", "Mateo Rincón", "3012223344", "1030405060"),
    ("valentina", "Valentina Cruz", "3023334455", "1040506070"),
]
# (dueño, título, ciudad, dirección, precio, capacidad, servicios, paleta, descripción)
SPACES = [
    ("andes_hub", "Oficina luminosa con terraza en El Poblado", "Medellín", "Cra. 43A #9-21, El Poblado", 35000, 6,
     "wifi 500 Mb, café de especialidad, terraza, sala de reuniones, aire acondicionado, parqueadero",
     "sage", "Oficina privada en un tercer piso con ventanales de piso a techo y terraza con plantas. "
     "Ideal para equipos pequeños que necesitan concentración y reuniones con clientes.\n\n"
     "Incluye pantalla de 55\", tablero de vidrio y café ilimitado."),
    ("andes_hub", "Escritorio flexible en Laureles", "Medellín", "Circular 73 #39-10, Laureles", 12000, 1,
     "wifi, café, locker, impresora, silla ergonómica",
     "sand", "Escritorio en zona abierta, tranquila y con mucha luz natural. Perfecto para freelancers "
     "y nómadas digitales que quieren salir de casa sin gastar de más."),
    ("andes_hub", "Sala de juntas ejecutiva Milla de Oro", "Medellín", "Cl. 7 Sur #42-70, piso 12", 90000, 14,
     "wifi, proyector, pantalla 75\", sala de reuniones, café, recepción, parqueadero",
     "navy", "Sala de juntas con vista a la ciudad para presentaciones, workshops y reuniones de directorio. "
     "Videoconferencia con cámara 4K y micrófonos de techo."),
    ("caribe_work", "Cowork frente al mar en Bocagrande", "Cartagena", "Av. San Martín #6-40, Bocagrande", 28000, 8,
     "wifi, aire acondicionado, terraza, café, ducha, 24 horas",
     "sea", "Trabaja con brisa del mar. Espacio abierto con mesas compartidas, terraza con vista a la bahía "
     "y acceso 24 horas para quienes trabajan con otros husos horarios."),
    ("caribe_work", "Estudio privado en el Centro Histórico", "Cartagena", "Cl. de la Factoría #36-57", 40000, 4,
     "wifi, aire acondicionado, café, tablero, pet friendly mascotas",
     "terracotta", "Estudio en una casa colonial restaurada, paredes de piedra y techos altos. "
     "Silencioso, fresco y con mucho carácter. Se permiten mascotas."),
    ("caribe_work", "Puesto fijo en Chapinero Alto", "Bogotá", "Cra. 7 #63-44, Chapinero", 15000, 1,
     "wifi, café, locker, impresora, cocina, bicicletero bicicleta",
     "sand", "Puesto de trabajo en una comunidad de diseñadores y desarrolladores. Cocina equipada, "
     "eventos semanales y parqueadero de bicicletas."),
    ("caribe_work", "Loft creativo en Usaquén", "Bogotá", "Cl. 119 #6-24, Usaquén", 45000, 10,
     "wifi, proyector, sala de reuniones, café, terraza, parqueadero",
     "sage", "Loft de doble altura para sesiones creativas, talleres o equipos de hasta 10 personas. "
     "Mobiliario modular que se adapta a tu dinámica."),
    ("cafe_estudio", "Rincón de trabajo en café de especialidad", "Pereira", "Cl. 19 #8-30, Centro", 10000, 2,
     "wifi, café de especialidad, enchufes en cada mesa",
     "terracotta", "Mesa reservada en el segundo piso de nuestro café, lejos del ruido de la barra. "
     "Incluye una bebida de la casa por cada 2 horas reservadas."),
    ("cafe_estudio", "Sala de reuniones en Granada", "Cali", "Av. 9N #15-38, Granada", 30000, 6,
     "wifi, pantalla, sala de reuniones, aire acondicionado, café",
     "navy", "Sala privada para reuniones de trabajo, entrevistas o clases. Aire acondicionado, "
     "pantalla para presentar y café de cortesía."),
]
PENDING_SPACE = ("cafe_estudio", "Terraza verde para equipos en Manizales", "Manizales", "Cra. 23 #63-15, Cable", 22000, 12,
                 "wifi, terraza, café, parqueadero", "sage",
                 "Terraza cubierta rodeada de jardín, ideal para jornadas de planeación y offsites.")
REVIEWS = [
    (5, "Excelente conexión y el café es buenísimo. Volveré la próxima semana."),
    (5, "Súper tranquilo, ideal para concentrarse. La anfitriona muy atenta."),
    (4, "Muy buen espacio, solo faltaron más enchufes cerca de la ventana."),
    (5, "Las fotos se quedan cortas, la luz natural es increíble."),
    (4, "Buena relación calidad-precio. Fácil de llegar."),
    (5, "Hicimos un workshop de 6 horas y todo funcionó perfecto."),
]

PALETTES = {
    "sage": [(214, 226, 214), (180, 200, 184), (96, 128, 104), (58, 82, 66)],
    "sand": [(240, 228, 210), (222, 200, 170), (168, 132, 96), (96, 72, 52)],
    "navy": [(218, 224, 236), (176, 188, 210), (60, 76, 110), (30, 40, 64)],
    "sea": [(214, 236, 238), (170, 214, 220), (40, 132, 150), (20, 78, 94)],
    "terracotta": [(244, 224, 212), (222, 176, 150), (176, 96, 66), (100, 52, 38)],
}


def _room(palette: str, variant: int, rng: random.Random) -> Image.Image:
    """Ilustración de un espacio de trabajo: pared, ventana, piso, escritorio, plantas y lámparas."""
    w, h = 1200, 900
    wall, wall2, accent, dark = PALETTES[palette]
    img = Image.new("RGB", (w, h), wall)
    d = ImageDraw.Draw(img)
    floor_y = int(h * rng.uniform(.62, .7))
    for y in range(floor_y):  # degradado de pared
        t = y / floor_y
        d.line([(0, y), (w, y)], fill=tuple(int(wall[i] * (1 - t * .25) + wall2[i] * t * .25) for i in range(3)))
    wood = (196, 160, 120) if palette != "navy" else (140, 120, 104)
    d.rectangle([0, floor_y, w, h], fill=wood)
    for x in range(-200, w + 200, 110):  # tablones
        d.line([(x, floor_y), (x - 180, h)], fill=tuple(c - 18 for c in wood), width=3)
    # ventanas con cielo
    nwin = 1 + variant % 3
    ww = int(w * .62 / nwin)
    for i in range(nwin):
        x0 = int(w * .08) + i * (ww + 30)
        y0, y1 = int(h * .1), floor_y - int(h * .16)
        sky = Image.new("RGB", (ww, y1 - y0))
        sd = ImageDraw.Draw(sky)
        for yy in range(y1 - y0):
            t = yy / (y1 - y0)
            sd.line([(0, yy), (ww, yy)], fill=(int(150 + 90 * t), int(196 + 46 * t), int(236 + 14 * t)))
        for _ in range(3):  # edificios o montañas
            bx = rng.randint(-40, ww - 40)
            bh = rng.randint(60, 220)
            sd.rectangle([bx, (y1 - y0) - bh, bx + rng.randint(50, 130), y1 - y0], fill=(140, 160, 176))
        img.paste(sky, (x0, y0))
        d.rectangle([x0, y0, x0 + ww, y1], outline=(250, 250, 248), width=14)
        d.line([(x0 + ww // 2, y0), (x0 + ww // 2, y1)], fill=(250, 250, 248), width=8)
    # cuadro / estante
    sx = int(w * .74)
    d.rectangle([sx, int(h * .14), sx + 220, int(h * .14) + 12], fill=dark)
    for i in range(5):
        bw = rng.randint(18, 32)
        d.rectangle([sx + 14 + i * 40, int(h * .14) - rng.randint(50, 80), sx + 14 + i * 40 + bw, int(h * .14)],
                    fill=rng.choice([accent, dark, (230, 180, 70), (200, 90, 70)]))
    # escritorio
    dy = floor_y + int(h * .06)
    d.rounded_rectangle([int(w * .12), dy - 24, int(w * .84), dy], radius=6, fill=(250, 246, 240))
    d.rectangle([int(w * .14), dy, int(w * .14) + 14, h - 40], fill=dark)
    d.rectangle([int(w * .82) - 14, dy, int(w * .82), h - 40], fill=dark)
    # laptops / monitores
    for i in range(1 + variant % 3):
        mx = int(w * .2) + i * 230
        d.rounded_rectangle([mx, dy - 160, mx + 190, dy - 44], radius=8, fill=(36, 40, 44))
        d.rectangle([mx + 10, dy - 150, mx + 180, dy - 54], fill=tuple(min(255, c + 40) for c in accent))
        d.rectangle([mx + 85, dy - 44, mx + 105, dy - 24], fill=(60, 64, 70))
        # taza
        d.rounded_rectangle([mx + 200, dy - 64, mx + 228, dy - 24], radius=5, fill=(255, 255, 255))
    # sillas
    for i in range(1 + variant % 3):
        cx = int(w * .24) + i * 230
        d.rounded_rectangle([cx, dy + 30, cx + 120, dy + 120], radius=26, fill=accent)
        d.rectangle([cx + 54, dy + 120, cx + 66, max(dy + 130, h - 30)], fill=dark)
    # plantas
    for px in (int(w * .04), int(w * .9)):
        pot_y = floor_y + 40
        d.rounded_rectangle([px, pot_y, px + 90, pot_y + 110], radius=12, fill=(232, 222, 206))
        for _ in range(9):
            lx, ly = px + 45 + rng.randint(-70, 70), pot_y - rng.randint(20, 220)
            d.ellipse([lx - 34, ly - 16, lx + 34, ly + 16], fill=(70 + rng.randint(0, 40), 130 + rng.randint(0, 40), 80))
    # lámparas colgantes
    for lx in range(int(w * .25), int(w * .8), 260):
        d.line([(lx, 0), (lx, int(h * .12))], fill=dark, width=3)
        d.pieslice([lx - 46, int(h * .12) - 30, lx + 46, int(h * .12) + 40], 180, 360, fill=dark)
        d.ellipse([lx - 12, int(h * .12) + 2, lx + 12, int(h * .12) + 20], fill=(255, 236, 170))
    # luz suave
    glow = Image.new("RGB", (w, h), (255, 248, 230))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse([-200, -300, w * .9, h * .8], fill=46)
    img = Image.composite(glow, img, mask.filter(ImageFilter.GaussianBlur(120)))
    return img


def _photos(palette: str, n: int, rng: random.Random) -> list[str]:
    names = []
    for v in range(n):
        name = f"{uuid4().hex}.jpg"
        _room(palette, v + rng.randint(0, 2), rng).save(settings.upload_dir / name, "JPEG", quality=84)
        names.append(name)
    return names


def run(reset: bool = False) -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    if reset:
        Base.metadata.drop_all(engine)
        for f in settings.upload_dir.glob("*.jpg"):
            f.unlink()
    Base.metadata.create_all(engine)
    rng = random.Random(7)
    pw = hash_password(PASSWORD)
    with SessionLocal() as db:
        seed_admin(db)
        if db.scalar(select(User.id).where(User.username == "andes_hub")):
            print("Los datos de demo ya existen. Usa --reset para recrearlos.")
            return
        owners = {}
        for u, name, biz, phone, doc in OWNERS:
            owners[u] = User(username=u, email=f"{u}@demo.cowork.co", password_hash=pw, role=Role.owner,
                             full_name=name, phone=phone, document_id=doc, business_name=biz)
        clients = [User(username=u, email=f"{u}@demo.cowork.co", password_hash=pw, role=Role.client,
                        full_name=name, phone=phone, document_id=doc) for u, name, phone, doc in CLIENTS]
        db.add_all([*owners.values(), *clients])
        db.flush()

        spaces = []
        for i, (o, title, city, addr, price, cap, amen, pal, desc) in enumerate([*SPACES, PENDING_SPACE]):
            s = Space(owner_id=owners[o].id, title=title, description=desc, city=city, address=addr,
                      price_per_hour=Decimal(price), capacity=cap, amenities=amen,
                      status=SpaceStatus.pending if i == len(SPACES) else SpaceStatus.approved)
            s.photos = [SpacePhoto(filename=n) for n in _photos(pal, rng.randint(3, 5), rng)]
            db.add(s)
            spaces.append(s)
        db.flush()

        today = now_local().date()
        approved = spaces[:len(SPACES)]
        # Reservas pasadas, pagadas y reseñadas
        k = 0
        for s in approved[:7]:
            for _ in range(rng.randint(1, 3)):
                c = clients[k % len(clients)]
                start = rng.choice([8, 9, 10, 14])
                hours = rng.choice([2, 3, 4])
                b = Booking(space_id=s.id, client_id=c.id, day=today - timedelta(days=rng.randint(2, 40)),
                            start_hour=start, end_hour=start + hours, total=s.price_per_hour * hours,
                            status=BookingStatus.confirmed, payment_status=PaymentStatus.paid,
                            payment_ref=f"SIM-DEMO{k:03d}")
                db.add(b)
                db.flush()
                rating, comment = REVIEWS[k % len(REVIEWS)]
                r = Review(booking_id=b.id, space_id=s.id, author_id=c.id, rating=rating, comment=comment)
                if k % 3 == 0:
                    r.owner_reply = "¡Gracias por venir! Te esperamos de nuevo."
                db.add(r)
                k += 1
        laura = clients[0]
        # Laura: una reserva terminada sin reseñar, dos próximas y una disputa
        b_past = Booking(space_id=approved[3].id, client_id=laura.id, day=today - timedelta(days=1),
                         start_hour=9, end_hour=12, total=approved[3].price_per_hour * 3,
                         status=BookingStatus.confirmed, payment_status=PaymentStatus.paid, payment_ref="SIM-DEMOL01")
        b_next = Booking(space_id=approved[0].id, client_id=laura.id, day=today + timedelta(days=3),
                         start_hour=9, end_hour=13, total=approved[0].price_per_hour * 4,
                         status=BookingStatus.confirmed, payment_status=PaymentStatus.paid, payment_ref="SIM-DEMOL02")
        b_next2 = Booking(space_id=approved[1].id, client_id=laura.id, day=today + timedelta(days=7),
                          start_hour=14, end_hour=18, total=approved[1].price_per_hour * 4,
                          status=BookingStatus.confirmed, payment_status=PaymentStatus.paid, payment_ref="SIM-DEMOL03")
        # Otras reservas para que el calendario muestre horas ocupadas
        busy = Booking(space_id=approved[0].id, client_id=clients[1].id, day=today + timedelta(days=1),
                       start_hour=10, end_hour=12, total=approved[0].price_per_hour * 2,
                       status=BookingStatus.confirmed, payment_status=PaymentStatus.paid, payment_ref="SIM-DEMOM01")
        busy2 = Booking(space_id=approved[0].id, client_id=clients[2].id, day=today + timedelta(days=1),
                        start_hour=15, end_hour=17, total=approved[0].price_per_hour * 2,
                        status=BookingStatus.confirmed, payment_status=PaymentStatus.paid, payment_ref="SIM-DEMOV01")
        db.add_all([b_past, b_next, b_next2, busy, busy2])
        db.flush()
        db.add(Dispute(booking_id=b_past.id, opened_by_id=laura.id,
                       reason="El aire acondicionado no funcionó durante la reserva y hacía mucho calor. "
                              "Solicito un reembolso parcial."))
        db.commit()
    print(f"Datos de demo creados. Clave de todas las cuentas: {PASSWORD}")
    print("  Cliente:   laura, mateo, valentina")
    print("  Anfitrión: andes_hub, caribe_work, cafe_estudio")
    print(f"  Admin:     {settings.admin_username} (clave del .env)")


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
