from tests.helpers import login, make_user, register


def test_register_client_and_owner(anon):
    assert "Cuenta creada" in register(anon, "client", "ana").text
    assert "Cuenta creada" in register(anon, "owner", "oscar").text


def test_owner_requires_business_name(anon):
    r = register(anon, "owner", "oscar", business_name="")
    assert r.status_code == 422 and "negocio" in r.text


def test_cannot_register_as_admin(anon):
    assert register(anon, "admin", "malo").status_code == 422


def test_duplicate_username_rejected(anon):
    register(anon, "client", "ana")
    r = register(anon, "client", "ana", email="otro@example.com")
    assert r.status_code == 422 and "ya están registrados" in r.text


def test_short_password_rejected(anon):
    assert register(anon, "client", "ana", password="corta").status_code == 422


def test_wrong_password(anon):
    register(anon, "client", "ana")
    assert "incorrectos" in login(anon, "ana", "mala-clave").text


def test_login_goes_to_role_home(owner):
    assert owner.get("/owner").status_code == 200


def test_post_without_csrf_is_rejected(anon):
    assert anon.post("/login", data={"username": "a", "password": "b"}).status_code == 403


def test_lockout_after_5_failures_even_with_right_password(anon):
    register(anon, "client", "ana")
    for _ in range(5):
        login(anon, "ana", "mala")
    r = login(anon, "ana", "password123")
    assert r.status_code == 429 and "Demasiados intentos" in r.text
    assert anon.get("/my/bookings").url.path == "/login"  # no entró


def test_successful_login_resets_counter(anon):
    register(anon, "client", "ana")
    for _ in range(4):
        login(anon, "ana", "mala")
    assert login(anon, "ana", "password123").url.path == "/"
    anon.submit("/logout")
    for _ in range(4):
        login(anon, "ana", "mala")
    assert login(anon, "ana", "password123").status_code == 200  # 4+4 sin reinicio habría bloqueado


def test_lockout_applies_to_unknown_usernames(anon):
    for _ in range(5):
        login(anon, "fantasma", "x")
    assert login(anon, "fantasma", "x").status_code == 429


def test_role_protection(anon, cliente):
    assert anon.get("/owner").url.path == "/login"
    assert cliente.get("/admin").status_code == 403
    assert cliente.get("/owner").status_code == 403
