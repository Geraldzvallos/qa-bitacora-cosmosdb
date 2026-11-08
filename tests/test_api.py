"""Pruebas de la API con el repositorio en memoria (no necesitan Azure)."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import ConflictoConcurrencia, RepositorioMemoria


@pytest.fixture
def client():
    with TestClient(create_app(repo=RepositorioMemoria())) as c:
        yield c


def nueva(client, **cambios):
    datos = {
        "proyecto": "tienda-web",
        "titulo": "El carrito no suma el envío",
        "descripcion": "El total no incluye el envío",
        "severidad": "ALTA",
        "etiquetas": ["Checkout", "checkout", " calculo "],
        "reportado_por": "Gerald",
    }
    datos.update(cambios)
    r = client.post("/api/incidencias", json=datos)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_y_pagina(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["almacenamiento"] == "memoria"
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"


def test_crear_documento_completo(client):
    d = nueva(client)
    assert d["estado"] == "ABIERTA"
    assert d["etiquetas"] == ["checkout", "calculo"]
    assert d["comentarios"] == []
    assert d["historial"][0]["a"] == "ABIERTA"
    assert not any(k.startswith("_") for k in d)


@pytest.mark.parametrize("cambio", [
    {"proyecto": "Tienda Web!"},
    {"titulo": "abc"},
    {"severidad": "URGENTE"},
    {"reportado_por": "G"},
    {"etiquetas": ["x" * 26]},
])
def test_validaciones(client, cambio):
    datos = {"proyecto": "tienda-web", "titulo": "Título válido", "reportado_por": "Gerald"}
    datos.update(cambio)
    assert client.post("/api/incidencias", json=datos).status_code == 422


def test_listar_y_filtrar(client):
    nueva(client)
    nueva(client, proyecto="app-reservas", titulo="Fechas pasadas aceptadas", severidad="CRITICA", etiquetas=["validacion"])
    assert len(client.get("/api/incidencias").json()) == 2
    assert len(client.get("/api/incidencias?proyecto=app-reservas").json()) == 1
    assert len(client.get("/api/incidencias?severidad=CRITICA").json()) == 1
    assert len(client.get("/api/incidencias?etiqueta=checkout").json()) == 1
    assert len(client.get("/api/incidencias?q=FECHAS").json()) == 1
    item = client.get("/api/incidencias").json()[0]
    assert "num_comentarios" in item and "comentarios" not in item


def test_obtener_y_404(client):
    d = nueva(client)
    assert client.get(f"/api/incidencias/tienda-web/{d['id']}").json()["id"] == d["id"]
    # Misma id en otra partición: no existe.
    assert client.get(f"/api/incidencias/otro-proyecto/{d['id']}").status_code == 404


def test_ciclo_de_vida(client):
    d = nueva(client)
    base = f"/api/incidencias/tienda-web/{d['id']}/estado"
    for estado in ("EN_PROGRESO", "RESUELTA", "CERRADA", "ABIERTA"):
        r = client.patch(base, json={"estado": estado, "autor": "Kevin"})
        assert r.status_code == 200, r.text
    final = r.json()
    assert final["estado"] == "ABIERTA"
    assert [h["a"] for h in final["historial"]] == ["ABIERTA", "EN_PROGRESO", "RESUELTA", "CERRADA", "ABIERTA"]


def test_transicion_invalida(client):
    d = nueva(client)
    r = client.patch(f"/api/incidencias/tienda-web/{d['id']}/estado", json={"estado": "RESUELTA", "autor": "Kevin"})
    assert r.status_code == 409
    assert "No se puede pasar de ABIERTA a RESUELTA" in r.json()["detail"]


def test_comentarios(client):
    d = nueva(client)
    url = f"/api/incidencias/tienda-web/{d['id']}/comentarios"
    client.post(url, json={"autor": "Kevin", "texto": "Lo reviso hoy"})
    r = client.post(url, json={"autor": "Gerald", "texto": "Gracias"})
    assert r.status_code == 201
    assert [c["texto"] for c in r.json()["comentarios"]] == ["Lo reviso hoy", "Gracias"]
    assert client.get("/api/incidencias").json()[0]["num_comentarios"] == 2
    assert client.post("/api/incidencias/tienda-web/no-existe/comentarios", json={"autor": "Kevin", "texto": "x"}).status_code == 404


def test_eliminar(client):
    d = nueva(client)
    assert client.delete(f"/api/incidencias/tienda-web/{d['id']}").status_code == 204
    assert client.delete(f"/api/incidencias/tienda-web/{d['id']}").status_code == 404


def test_resumen(client):
    nueva(client)
    nueva(client, proyecto="app-reservas", titulo="Fechas pasadas aceptadas", severidad="CRITICA", etiquetas=["checkout"])
    r = client.get("/api/resumen").json()
    assert r["total"] == 2
    assert r["por_estado"]["ABIERTA"] == 2
    assert r["por_severidad"]["CRITICA"] == 1
    assert r["por_proyecto"] == {"app-reservas": 1, "tienda-web": 1}
    assert r["etiquetas_top"][0] == {"etiqueta": "checkout", "total": 2}
    assert r["criticas_pendientes"] == 1


def test_concurrencia_optimista():
    repo = RepositorioMemoria()
    with TestClient(create_app(repo=repo)) as c:
        d = nueva(c)
    doc_a = repo.obtener("tienda-web", d["id"])
    doc_b = repo.obtener("tienda-web", d["id"])
    doc_a["titulo"] = "Cambio A"
    repo.reemplazar(doc_a)
    doc_b["titulo"] = "Cambio B"
    with pytest.raises(ConflictoConcurrencia):
        repo.reemplazar(doc_b)
