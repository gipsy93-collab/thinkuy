"""Pruebas de aislamiento multiusuario (DOFA D3).

Verifica que múltiples investigadores en una instancia compartida de Thinkuy
tengan aislamiento estricto de sus protocolos PRISMA, decisiones de screening
y datos de charteo (JBI), impidiendo la contaminación cruzada de datos.
"""
import pytest
from fastapi.testclient import TestClient
from radar import db
from radar.api.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Configura una base de datos temporal limpia para cada test."""
    test_db = tmp_path / "test_multiusuario.db"
    conn = db.connect(test_db)
    db.init_db(conn)
    conn.close()

    monkeypatch.setattr(db.config, "DB_PATH", test_db)
    return TestClient(app)


def test_protocol_isolation_between_users(client):
    # 1. Investigador Alice crea su protocolo
    res_alice = client.post(
        "/api/review/protocol",
        json={
            "title": "Protocolo de Oncología - Alice",
            "research_question": "¿Eficacia de inmunoterapia?",
            "framework": "PICO",
        },
        headers={"X-User-Id": "alice"},
    )
    assert res_alice.status_code == 200
    proto_alice_id = res_alice.json()["protocol_id"]

    # 2. Investigador Bob crea su protocolo
    res_bob = client.post(
        "/api/review/protocol",
        json={
            "title": "Protocolo de Inteligencia Artificial - Bob",
            "research_question": "¿Uso de LLMs en educación?",
            "framework": "SPIDER",
        },
        headers={"X-User-Id": "bob"},
    )
    assert res_bob.status_code == 200

    # 3. Bob consulta la lista de protocolos: solo debe ver el suyo (y los 'default' públicos si hubiera)
    list_bob = client.get("/api/review/protocols", headers={"X-User-Id": "bob"})
    assert list_bob.status_code == 200
    bob_titles = [p["title"] for p in list_bob.json()["protocols"]]
    assert "Protocolo de Inteligencia Artificial - Bob" in bob_titles
    assert "Protocolo de Oncología - Alice" not in bob_titles

    # 4. Alice consulta la lista: solo ve el suyo
    list_alice = client.get("/api/review/protocols", headers={"X-User-Id": "alice"})
    assert list_alice.status_code == 200
    alice_titles = [p["title"] for p in list_alice.json()["protocols"]]
    assert "Protocolo de Oncología - Alice" in alice_titles
    assert "Protocolo de Inteligencia Artificial - Bob" not in alice_titles

    # 5. Bob intenta acceder directamente al protocolo de Alice por ID: debe retornar 404
    get_alice_as_bob = client.get(f"/api/review/protocol/{proto_alice_id}", headers={"X-User-Id": "bob"})
    assert get_alice_as_bob.status_code == 404

    # 6. Alice accede a su propio protocolo por ID: debe retornar 200
    get_alice_as_alice = client.get(f"/api/review/protocol/{proto_alice_id}", headers={"X-User-Id": "alice"})
    assert get_alice_as_alice.status_code == 200
    assert get_alice_as_alice.json()["id"] == proto_alice_id


def test_protocol_status_mutation_isolation(client):
    # Alice crea protocolo
    res_alice = client.post(
        "/api/review/protocol",
        json={"title": "Revisión Alice"},
        headers={"X-User-Id": "alice"},
    )
    pid = res_alice.json()["protocol_id"]

    # Bob intenta cambiar el estado del protocolo de Alice
    res_hack = client.post(
        f"/api/review/protocol/{pid}/status",
        json={"status": "screening"},
        headers={"X-User-Id": "bob"},
    )
    assert res_hack.status_code == 404

    # Alice cambia el estado de su propio protocolo
    res_ok = client.post(
        f"/api/review/protocol/{pid}/status",
        json={"status": "screening"},
        headers={"X-User-Id": "alice"},
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["protocol"]["status"] == "screening"


def test_screening_and_charting_isolation(client):
    # Alice crea protocolo
    res = client.post(
        "/api/review/protocol",
        json={"title": "Vacunas COVID"},
        headers={"X-User-Id": "alice"},
    )
    pid = res.json()["protocol_id"]

    # Alice realiza screening de dos artículos
    client.post(
        f"/api/review/protocol/{pid}/screen",
        json={"doi": "10.1001/jama.2021.0001", "decision": "included", "reason": "Ensayo clave"},
        headers={"X-User-Id": "alice"},
    )
    client.post(
        f"/api/review/protocol/{pid}/screen",
        json={"doi": "10.1001/jama.2021.0002", "decision": "excluded", "reason": "No cumple criterios"},
        headers={"X-User-Id": "alice"},
    )

    # Alice registra charting
    client.post(
        f"/api/review/protocol/{pid}/chart",
        json={
            "doi": "10.1001/jama.2021.0001",
            "population": "Adultos mayores",
            "concept": "Inmunogenicidad",
            "key_findings": "95% eficacia",
        },
        headers={"X-User-Id": "alice"},
    )

    # Alice consulta sus screenings y su flow diagram
    screenings_alice = client.get(f"/api/review/protocol/{pid}/screenings", headers={"X-User-Id": "alice"}).json()
    assert screenings_alice["total"] == 2

    flow_alice = client.get(f"/api/review/protocol/{pid}/flow-diagram", headers={"X-User-Id": "alice"}).json()
    # `total_identified` es ahora la identificación PRISMA (registro de búsquedas); los registros
    # únicos que entraron al cribado viven en `prisma_2020.cribado.registros_unicos`.
    assert flow_alice["prisma_2020"]["cribado"]["registros_unicos"] == 2
    assert flow_alice["included"] == 1
    assert flow_alice["excluded"] == 1

    charting_alice = client.get(f"/api/review/protocol/{pid}/charting", headers={"X-User-Id": "alice"}).json()
    assert charting_alice["total"] == 1
    assert charting_alice["charting"][0]["key_findings"] == "95% eficacia"

    # Bob intenta ver los screenings de Alice
    screenings_bob = client.get(f"/api/review/protocol/{pid}/screenings", headers={"X-User-Id": "bob"}).json()
    assert screenings_bob["total"] == 0

    # Bob tampoco puede ver el diagrama de flujo del protocolo de Alice
    flow_bob = client.get(f"/api/review/protocol/{pid}/flow-diagram", headers={"X-User-Id": "bob"})
    assert flow_bob.status_code == 404

    # Bob intenta exportar el protocolo de Alice: el protocolo no le pertenece
    export_bob = client.get(f"/api/review/protocol/{pid}/export?format=csv", headers={"X-User-Id": "bob"})
    assert export_bob.status_code == 404

    # Alice exporta su protocolo
    export_alice = client.get(f"/api/review/protocol/{pid}/export?format=csv", headers={"X-User-Id": "alice"})
    assert export_alice.status_code == 200
    assert "10.1001/jama.2021.0001" in export_alice.text
    assert "95% eficacia" in export_alice.text


def test_default_backward_compatibility(client):
    # Petición sin header X-User-Id (comportamiento local mono-usuario preexistente)
    res = client.post(
        "/api/review/protocol",
        json={"title": "Protocolo Local Monousuario"},
    )
    assert res.status_code == 200
    assert res.json()["protocol"]["owner_id"] == "default"

    # Listado sin header debe mostrarlo sin problemas
    list_res = client.get("/api/review/protocols")
    assert list_res.status_code == 200
    titles = [p["title"] for p in list_res.json()["protocols"]]
    assert "Protocolo Local Monousuario" in titles


def test_jwt_bearer_token_authentication(client):
    # 1. Solicitar token JWT para el investigador Carlos
    token_res = client.post("/api/auth/token", json={"user_id": "carlos", "expires_in_seconds": 3600})
    assert token_res.status_code == 200
    data = token_res.json()
    token = data["access_token"]
    assert token is not None

    # 2. Consultar perfil con token Bearer
    me_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_res.status_code == 200
    assert me_res.json()["user_id"] == "carlos"
    assert me_res.json()["authenticated"] is True
    assert me_res.json()["auth_method"] == "bearer_jwt"

    # 3. Carlos crea un protocolo protegido usando su Bearer token
    proto_res = client.post(
        "/api/review/protocol",
        json={"title": "Protocolo Vacunas - Carlos"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert proto_res.status_code == 200
    assert proto_res.json()["protocol"]["owner_id"] == "carlos"

    # 4. Alice intenta ver los protocolos: no ve el de Carlos
    alice_list = client.get("/api/review/protocols", headers={"X-User-Id": "alice"})
    assert alice_list.status_code == 200
    alice_titles = [p["title"] for p in alice_list.json()["protocols"]]
    assert "Protocolo Vacunas - Carlos" not in alice_titles

    # 5. Carlos consulta sus protocolos con su Bearer token: sí lo ve
    carlos_list = client.get("/api/review/protocols", headers={"Authorization": f"Bearer {token}"})
    assert carlos_list.status_code == 200
    carlos_titles = [p["title"] for p in carlos_list.json()["protocols"]]
    assert "Protocolo Vacunas - Carlos" in carlos_titles
