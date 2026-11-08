"""Reglas de negocio: crear incidencias, cambiar su estado, comentar y resumir."""
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from .models import (
    TRANSICIONES,
    CambioEstado,
    ComentarioCrear,
    Estado,
    Filtros,
    IncidenciaCrear,
    Severidad,
)
from .repository import limpiar, nuevo_id


class TransicionInvalida(Exception):
    def __init__(self, actual: Estado, nuevo: Estado):
        permitidos = ", ".join(sorted(e.value for e in TRANSICIONES[actual])) or "ninguno"
        super().__init__(
            f"No se puede pasar de {actual.value} a {nuevo.value}. Desde {actual.value} se permite: {permitidos}."
        )


def ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ServicioIncidencias:
    def __init__(self, repo):
        self.repo = repo

    def crear(self, datos: IncidenciaCrear) -> Dict[str, Any]:
        momento = ahora_iso()
        doc = {
            "id": nuevo_id(),
            "tipo": "incidencia",
            "proyecto": datos.proyecto,
            "titulo": datos.titulo,
            "descripcion": datos.descripcion.strip(),
            "severidad": datos.severidad.value,
            "estado": Estado.ABIERTA.value,
            "etiquetas": datos.etiquetas,
            "reportado_por": datos.reportado_por,
            "creado_en": momento,
            "actualizado_en": momento,
            # Datos relacionados embebidos en el mismo documento (modelo NoSQL):
            "comentarios": [],
            "historial": [
                {"de": None, "a": Estado.ABIERTA.value, "autor": datos.reportado_por, "fecha": momento}
            ],
        }
        return limpiar(self.repo.crear(doc))

    def listar(self, filtros: Filtros) -> List[Dict[str, Any]]:
        return self.repo.listar(filtros)

    def obtener(self, proyecto: str, incidencia_id: str) -> Dict[str, Any]:
        return limpiar(self.repo.obtener(proyecto, incidencia_id))

    def cambiar_estado(self, proyecto: str, incidencia_id: str, cambio: CambioEstado) -> Dict[str, Any]:
        doc = self.repo.obtener(proyecto, incidencia_id)
        actual = Estado(doc["estado"])
        if cambio.estado not in TRANSICIONES[actual]:
            raise TransicionInvalida(actual, cambio.estado)
        momento = ahora_iso()
        doc["estado"] = cambio.estado.value
        doc["actualizado_en"] = momento
        doc["historial"].append(
            {"de": actual.value, "a": cambio.estado.value, "autor": cambio.autor.strip(), "fecha": momento}
        )
        return limpiar(self.repo.reemplazar(doc))

    def comentar(self, proyecto: str, incidencia_id: str, datos: ComentarioCrear) -> Dict[str, Any]:
        momento = ahora_iso()
        comentario = {
            "id": nuevo_id(),
            "autor": " ".join(datos.autor.split()),
            "texto": datos.texto.strip(),
            "fecha": momento,
        }
        return limpiar(self.repo.agregar_comentario(proyecto, incidencia_id, comentario, momento))

    def eliminar(self, proyecto: str, incidencia_id: str) -> None:
        self.repo.eliminar(proyecto, incidencia_id)

    def resumen(self) -> Dict[str, Any]:
        datos = self.repo.datos_resumen()
        por_estado = {e.value: 0 for e in Estado}
        por_severidad = {s.value: 0 for s in Severidad}
        proyectos: Counter = Counter()
        etiquetas: Counter = Counter()
        criticas_pendientes = 0
        for d in datos:
            por_estado[d["estado"]] = por_estado.get(d["estado"], 0) + 1
            por_severidad[d["severidad"]] = por_severidad.get(d["severidad"], 0) + 1
            proyectos[d["proyecto"]] += 1
            etiquetas.update(d.get("etiquetas") or [])
            if d["severidad"] == Severidad.CRITICA.value and d["estado"] in (
                Estado.ABIERTA.value,
                Estado.EN_PROGRESO.value,
            ):
                criticas_pendientes += 1
        return {
            "total": len(datos),
            "por_estado": por_estado,
            "por_severidad": por_severidad,
            "por_proyecto": dict(sorted(proyectos.items())),
            "etiquetas_top": [{"etiqueta": e, "total": n} for e, n in etiquetas.most_common(5)],
            "criticas_pendientes": criticas_pendientes,
        }
