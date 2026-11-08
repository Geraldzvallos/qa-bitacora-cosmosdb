"""Acceso a datos: Azure Cosmos DB (API for NoSQL) y una versión en memoria.

Cada incidencia es un documento JSON. La clave de partición es /proyecto:
todas las incidencias de un mismo proyecto viven en la misma partición lógica,
así que leerlas o filtrarlas por proyecto es barato (consulta de una sola partición).
"""
import copy
import uuid
from typing import Any, Dict, List

from .models import Filtros

CAMPOS_LISTA = (
    "c.id, c.proyecto, c.titulo, c.severidad, c.estado, c.etiquetas, "
    "c.reportado_por, c.creado_en, c.actualizado_en, "
    "ARRAY_LENGTH(c.comentarios) AS num_comentarios"
)


class NoEncontrada(Exception):
    """La incidencia no existe en esa partición."""


class ConflictoConcurrencia(Exception):
    """El documento cambió desde que se leyó (ETag distinto)."""


def limpiar(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Quita las propiedades de sistema de Cosmos DB (_rid, _self, _etag, _ts...)."""
    return {k: v for k, v in doc.items() if not k.startswith("_")}


class RepositorioCosmos:
    almacenamiento = "cosmos"

    def __init__(self, endpoint: str, key: str, database: str, container: str):
        from azure.cosmos import CosmosClient, PartitionKey

        self._client = CosmosClient(endpoint, credential=key)
        db = self._client.create_database_if_not_exists(id=database)
        # Sin throughput explícito: funciona en cuentas serverless y en la capa gratuita.
        self._c = db.create_container_if_not_exists(
            id=container, partition_key=PartitionKey(path="/proyecto")
        )

    def ping(self) -> None:
        self._c.read()

    def crear(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return self._c.create_item(body=doc)

    def listar(self, f: Filtros) -> List[Dict[str, Any]]:
        condiciones = ["c.tipo = 'incidencia'"]
        params: List[Dict[str, Any]] = []
        if f.proyecto:
            condiciones.append("c.proyecto = @proyecto")
            params.append({"name": "@proyecto", "value": f.proyecto})
        if f.estado:
            condiciones.append("c.estado = @estado")
            params.append({"name": "@estado", "value": f.estado.value})
        if f.severidad:
            condiciones.append("c.severidad = @severidad")
            params.append({"name": "@severidad", "value": f.severidad.value})
        if f.etiqueta:
            condiciones.append("ARRAY_CONTAINS(c.etiquetas, @etiqueta)")
            params.append({"name": "@etiqueta", "value": f.etiqueta})
        if f.q:
            condiciones.append("CONTAINS(c.titulo, @q, true)")
            params.append({"name": "@q", "value": f.q})
        query = (
            f"SELECT TOP 200 {CAMPOS_LISTA} FROM c WHERE "
            + " AND ".join(condiciones)
            + " ORDER BY c.creado_en DESC"
        )
        if f.proyecto:
            # Consulta de una sola partición: más rápida y consume menos RU.
            items = self._c.query_items(query=query, parameters=params, partition_key=f.proyecto)
        else:
            items = self._c.query_items(
                query=query, parameters=params, enable_cross_partition_query=True
            )
        return list(items)

    def obtener(self, proyecto: str, incidencia_id: str) -> Dict[str, Any]:
        from azure.cosmos import exceptions

        try:
            # Lectura puntual (id + clave de partición): la operación más barata, ~1 RU.
            return self._c.read_item(item=incidencia_id, partition_key=proyecto)
        except exceptions.CosmosResourceNotFoundError as exc:
            raise NoEncontrada() from exc

    def reemplazar(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        from azure.core import MatchConditions
        from azure.cosmos import exceptions

        try:
            # Concurrencia optimista: solo se guarda si nadie lo modificó desde la lectura.
            return self._c.replace_item(
                item=doc["id"],
                body=doc,
                etag=doc.get("_etag"),
                match_condition=MatchConditions.IfNotModified,
            )
        except exceptions.CosmosAccessConditionFailedError as exc:
            raise ConflictoConcurrencia() from exc
        except exceptions.CosmosResourceNotFoundError as exc:
            raise NoEncontrada() from exc

    def agregar_comentario(
        self, proyecto: str, incidencia_id: str, comentario: Dict[str, Any], ahora: str
    ) -> Dict[str, Any]:
        from azure.cosmos import exceptions

        try:
            # Actualización parcial (Patch): agrega al arreglo sin reescribir el documento.
            return self._c.patch_item(
                item=incidencia_id,
                partition_key=proyecto,
                patch_operations=[
                    {"op": "add", "path": "/comentarios/-", "value": comentario},
                    {"op": "set", "path": "/actualizado_en", "value": ahora},
                ],
            )
        except exceptions.CosmosResourceNotFoundError as exc:
            raise NoEncontrada() from exc

    def eliminar(self, proyecto: str, incidencia_id: str) -> None:
        from azure.cosmos import exceptions

        try:
            self._c.delete_item(item=incidencia_id, partition_key=proyecto)
        except exceptions.CosmosResourceNotFoundError as exc:
            raise NoEncontrada() from exc

    def datos_resumen(self) -> List[Dict[str, Any]]:
        query = (
            "SELECT c.proyecto, c.estado, c.severidad, c.etiquetas "
            "FROM c WHERE c.tipo = 'incidencia'"
        )
        return list(self._c.query_items(query=query, enable_cross_partition_query=True))


class RepositorioMemoria:
    """Mismo comportamiento que Cosmos, para pruebas y para correr la app sin nube."""

    almacenamiento = "memoria"

    def __init__(self):
        self._docs: Dict[tuple, Dict[str, Any]] = {}

    def ping(self) -> None:
        return None

    def _guardar(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        doc = copy.deepcopy(doc)
        doc["_etag"] = uuid.uuid4().hex
        self._docs[(doc["proyecto"], doc["id"])] = doc
        return copy.deepcopy(doc)

    def crear(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        return self._guardar(doc)

    def listar(self, f: Filtros) -> List[Dict[str, Any]]:
        res = []
        for d in self._docs.values():
            if d.get("tipo") != "incidencia":
                continue
            if f.proyecto and d["proyecto"] != f.proyecto:
                continue
            if f.estado and d["estado"] != f.estado.value:
                continue
            if f.severidad and d["severidad"] != f.severidad.value:
                continue
            if f.etiqueta and f.etiqueta not in d["etiquetas"]:
                continue
            if f.q and f.q.lower() not in d["titulo"].lower():
                continue
            item = {k: d[k] for k in (
                "id", "proyecto", "titulo", "severidad", "estado", "etiquetas",
                "reportado_por", "creado_en", "actualizado_en",
            )}
            item["num_comentarios"] = len(d["comentarios"])
            res.append(copy.deepcopy(item))
        res.sort(key=lambda x: x["creado_en"], reverse=True)
        return res[:200]

    def obtener(self, proyecto: str, incidencia_id: str) -> Dict[str, Any]:
        doc = self._docs.get((proyecto, incidencia_id))
        if doc is None:
            raise NoEncontrada()
        return copy.deepcopy(doc)

    def reemplazar(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        actual = self._docs.get((doc["proyecto"], doc["id"]))
        if actual is None:
            raise NoEncontrada()
        if doc.get("_etag") != actual["_etag"]:
            raise ConflictoConcurrencia()
        return self._guardar(doc)

    def agregar_comentario(
        self, proyecto: str, incidencia_id: str, comentario: Dict[str, Any], ahora: str
    ) -> Dict[str, Any]:
        doc = self.obtener(proyecto, incidencia_id)
        doc["comentarios"].append(comentario)
        doc["actualizado_en"] = ahora
        return self._guardar(doc)

    def eliminar(self, proyecto: str, incidencia_id: str) -> None:
        if self._docs.pop((proyecto, incidencia_id), None) is None:
            raise NoEncontrada()

    def datos_resumen(self) -> List[Dict[str, Any]]:
        return [
            {k: d[k] for k in ("proyecto", "estado", "severidad", "etiquetas")}
            for d in self._docs.values()
            if d.get("tipo") == "incidencia"
        ]


def nuevo_id() -> str:
    return str(uuid.uuid4())
