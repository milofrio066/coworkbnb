# Cowork — MVP de alquiler de espacios de coworking (tipo Airbnb)

FastAPI + PostgreSQL + Jinja2, sin contenedores. Las fotos se guardan en la carpeta `uploads/`.
Interfaz propia (`app/static/cowork.css`, fuente Plus Jakarta Sans, verde bosque `#12684f` + mostaza `#f2b33d`):
catálogo con categorías, orden y carrusel de fotos; detalle con galería, visor de fotos, servicios con íconos,
calendario de horas ocupadas (`GET /spaces/{id}/availability?day=AAAA-MM-DD`) y cálculo del total en vivo.

## Demo rápido

```bash
python -m scripts.seed_demo            # crea anfitriones, clientes, 10 espacios con fotos, reservas, reseñas y una disputa
python -m scripts.seed_demo --reset    # BORRA la base y las fotos .jpg de uploads/ y vuelve a cargar el demo
uvicorn app.main:app --reload
```
Cuentas de demo (clave `demo12345`): cliente `laura`, `mateo`, `valentina`; anfitrión `andes_hub`, `caribe_work`,
`cafe_estudio`; admin con el usuario y la clave del `.env`. Con `DEMO_MODE=true` en el `.env` el login muestra estas cuentas.
Las fotos del demo son ilustraciones generadas, no fotos reales.

**PostgreSQL portable (Windows, sin instalar):** en esta copia hay binarios de PostgreSQL 16 en `.tools/pgsql` con los datos
en `.tools/pgdata` (usuario `cowork`/`cowork`, bases `cowork` y `cowork_test`). Para arrancarlo o detenerlo:
`.tools\pgsql\bin\pg_ctl -D .tools\pgdata -l .tools\pg.log start` (o `stop`).

## Requisitos
Python 3.11+ y **PostgreSQL 14+ instalado en tu equipo** (sin Docker).

## 1. Preparar PostgreSQL (una sola vez)

Instala PostgreSQL (Windows/macOS: instalador de postgresql.org; Ubuntu: `sudo apt install postgresql`) y crea el usuario y las bases:

```bash
# Linux / macOS
sudo -u postgres psql -c "CREATE USER cowork WITH PASSWORD 'cowork' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE cowork OWNER cowork;"
sudo -u postgres psql -c "CREATE DATABASE cowork_test OWNER cowork;"   # solo para los tests
```
En Windows abre "SQL Shell (psql)" y ejecuta esas mismas tres sentencias SQL (sin `sudo -u postgres psql -c`).
Cambia la clave `cowork` por una segura y úsala también en `DATABASE_URL`.

## 2. Ejecutar

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env  -> edita SECRET_KEY, ADMIN_PASSWORD y DATABASE_URL
uvicorn app.main:app --reload
```

Abre http://localhost:8000. El admin se crea solo al arrancar con `ADMIN_USERNAME` / `ADMIN_PASSWORD` del `.env`.
Las tablas se crean automáticamente al arrancar. Si ya tenías datos de una versión anterior, recrea la base
(`DROP DATABASE cowork; CREATE DATABASE cowork OWNER cowork;`) porque hay tablas y columnas nuevas.
Las reservas bloquean la fila del espacio (`FOR UPDATE`) para evitar cruces de horario concurrentes.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```
Corren sobre PostgreSQL en la base `cowork_test` (o la de `TEST_DATABASE_URL`); se niegan a ejecutarse si el nombre de la base
no termina en `_test`, porque borran y recrean las tablas. Incluyen una prueba de reservas simultáneas.

## Roles

| Rol | Puede |
|---|---|
| Cliente | buscar/filtrar, reservar por horas, pagar (simulado), cancelar con reembolso simulado, reseñar, abrir disputas |
| Dueño | publicar/editar espacios con fotos y precio, ver reservas pagadas, responder reseñas (una vez), abrir disputas |
| Admin | aprobar/rechazar/suspender espacios, suspender usuarios, resolver disputas, **eliminar** usuarios, espacios, fotos, reservas y reseñas, ver auditoría |

## Reglas nuevas

- **Pago simulado** (sin pasarela real): al reservar, el horario se retiene **15 minutos** (pendiente de pago); al pagar queda confirmada.
  Si no se paga, el horario se libera solo. Tarjetas de prueba: `4242 4242 4242 4242` (aprueba), `4000 0000 0000 0002` (rechaza),
  `4000 0000 0000 9995` (fondos insuficientes); cualquier vencimiento futuro (MM/AA) y CVV. No se guardan datos de tarjeta.
  Cancelar una reserva pagada (hasta el día anterior) o resolverla a favor del cliente en una disputa marca el pago como reembolsado.
- **Reseñas**: solo el cliente, una por reserva, cuando la reserva ya está pagada y terminó. Calificación 1-5 y comentario.
  El dueño puede responder una vez; el admin puede eliminarlas. El promedio aparece en el catálogo y en el detalle.
- **Límite de login**: 5 intentos fallidos por usuario o 20 por IP en 15 minutos; después responde 429 aunque la clave sea correcta.
  Un login exitoso reinicia el contador. Se guarda en la BD, así funciona con varios procesos.

## Seguridad incluida
bcrypt, sesión firmada, token CSRF en todos los POST, control de rol por ruta, fotos re-codificadas (se valida que sean imágenes
y se elimina el EXIF/GPS), consultas parametrizadas, auditoría sin datos personales.

## Pendiente para producción
Pasarela de pago real, verificación de correo/recuperar clave, migraciones con Alembic, fotos en S3, HTTPS (`HTTPS_ONLY=true`),
política de privacidad y consentimiento (Habeas Data / Ley 1581 en Colombia: valídalo con un abogado).
