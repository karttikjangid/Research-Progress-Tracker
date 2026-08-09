"""Editable current-week theme (GET/PUT /api/theme).

The plan default comes from week.yaml; the owner can override it, and clearing
the override reverts to the plan. The label week number is computed from today,
never a stale stored number.
"""
from conftest import freeze


def test_defaults_to_plan_theme(client):
    d = client.get("/api/theme").json()
    # week.yaml ships a real theme; whatever it is, custom is false and the shown
    # theme equals the plan theme.
    assert d["custom"] is False
    assert d["theme"] == d["plan_theme"]


def test_week_number_is_todays_not_stored(app, client):
    freeze(app, "2026-08-10")               # ISO week 33
    assert client.get("/api/theme").json()["week"] == 33
    freeze(app, "2026-01-01")               # Thursday → ISO week 1
    assert client.get("/api/theme").json()["week"] == 1


def test_put_sets_custom_theme(client):
    r = client.put("/api/theme", json={"theme": "Prove the spectral theorem cold"})
    assert r.status_code == 200
    d = r.json()
    assert d["custom"] is True
    assert d["theme"] == "Prove the spectral theorem cold"
    # persisted across a fresh GET
    assert client.get("/api/theme").json()["theme"] == "Prove the spectral theorem cold"


def test_empty_put_reverts_to_plan(client):
    client.put("/api/theme", json={"theme": "temporary override"})
    d = client.put("/api/theme", json={"theme": ""}).json()
    assert d["custom"] is False
    assert d["theme"] == d["plan_theme"]


def test_whitespace_only_is_treated_as_clear(client):
    client.put("/api/theme", json={"theme": "override"})
    d = client.put("/api/theme", json={"theme": "   "}).json()
    assert d["custom"] is False


def test_override_persists_and_plan_still_exposed(client):
    d = client.put("/api/theme", json={"theme": "my own focus"}).json()
    # plan_theme is preserved alongside the override so the UI can offer revert
    assert d["theme"] == "my own focus"
    assert d["plan_theme"] and d["plan_theme"] != "my own focus"
