from tests.helpers import future, paid_booking, publish, reserve


def test_availability_marks_taken_hours(cliente, approved_space, anon):
    day = future()
    paid_booking(cliente, approved_space, day, 9, 11)
    r = anon.get(f"/spaces/{approved_space}/availability", params={"day": day.isoformat()})
    assert r.status_code == 200 and r.json()["taken"] == [9, 10] and r.json()["past"] == []


def test_availability_counts_pending_holds(cliente, approved_space, anon):
    reserve(cliente, approved_space, future(), 14, 16)  # retenida, sin pagar
    assert anon.get(f"/spaces/{approved_space}/availability", params={"day": future().isoformat()}).json()["taken"] == [14, 15]


def test_availability_hidden_for_unapproved_space(owner, anon):
    sid = publish(owner)
    assert anon.get(f"/spaces/{sid}/availability", params={"day": future().isoformat()}).status_code == 404
    assert anon.get("/spaces/999/availability", params={"day": "no-fecha"}).status_code == 404


def test_amenity_filter_and_sort(approved_space, anon):
    assert "Sala Centro" in anon.get("/", params={"amenity": "wifi"}).text
    assert "Sala Centro" not in anon.get("/", params={"amenity": "terraza"}).text
    assert anon.get("/", params={"sort": "price_desc"}).status_code == 200
    assert anon.get("/", params={"sort": "inventado"}).status_code == 200


def test_pages_render_for_each_role(anon, cliente, owner, admin, approved_space):
    paid_booking(cliente, approved_space)
    for c, urls in [
        (anon, ["/", "/login", "/register", "/register?role=owner", f"/spaces/{approved_space}"]),
        (cliente, ["/my/bookings", f"/spaces/{approved_space}"]),
        (owner, ["/owner", "/owner/spaces/new", f"/owner/spaces/{approved_space}/edit"]),
        (admin, ["/admin"]),
    ]:
        for u in urls:
            assert c.get(u).status_code == 200, u
