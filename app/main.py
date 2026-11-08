"""API y página web de QA Bitácora."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .models import (
    SLUG,
    CambioEstado,
    ComentarioCrear,
    Estado,
    Filtros,
    IncidenciaCrear,
    Severidad,
)
from .repository import ConflictoConcurrencia, NoEncontrada, RepositorioCosmos, RepositorioMemoria
from .service import ServicioIncidencias, TransicionInvalida

log = logging.getLogger("qa_bitacora")
STATIC_DIR = Path(__file__).parent / "static"

EJEMPLOS = [
    IncidenciaCrear(
        proyecto="tienda-web", titulo="El total del carrito no suma el envío",
        descripcion="Al pagar, el total mostrado no incluye el costo de envío.",
        severidad=Severidad.ALTA, etiquetas=["checkout", "calculo"], reportado_por="Kevin",
    ),
    IncidenciaCrear(
        proyecto="tienda-web", titulo="Productos duplicados en el catálogo",
        descripcion="Dos productos aparecen con el mismo código SKU.",
        severidad=Severidad.MEDIA, etiquetas=["datos", "catalogo"], reportado_por="Gerald",
    ),
    IncidenciaCrear(
        proyecto="app-reservas", titulo="Se pueden reservar fechas pasadas",
        descripcion="El formulario acepta fechas anteriores a hoy.",
        severidad=Severidad.CRITICA, etiquetas=["validacion"], reportado_por="Gerald",
    ),
]


def crear_repositorio():
    s = get_settings()
    if s.cosmos_enabled:
        log.info("Usando Azure Cosmos DB: base %s, contenedor %s", s.cosmos_database, s.cosmos_container)
        return RepositorioCosmos(s.cosmos_endpoint, s.cosmos_key, s.cosmos_database, s.cosmos_container)
    log.warning("COSMOS_ENDPOINT/COSMOS_KEY no definidos: se usa almacenamiento en memoria (demo local).")
    repo = RepositorioMemoria()
    servicio = ServicioIncidencias(repo)
    for ejemplo in EJEMPLOS:
        servicio.crear(ejemplo)
    return repo


def create_app(repo=None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "repo", None) is None:
            app.state.repo = crear_repositorio()
        yield

    app = FastAPI(
        title="QA Bitácora",
        description="Registro de incidencias de calidad con Azure Cosmos DB (API for NoSQL).",
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.repo = repo

    @app.middleware("http")
    async def cabeceras_seguridad(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    def servicio(request: Request) -> ServicioIncidencias:
        return ServicioIncidencias(request.app.state.repo)

    def no_encontrada():
        return HTTPException(status_code=404, detail="La incidencia no existe")

    @app.get("/health")
    def health(request: Request):
        repo = request.app.state.repo
        try:
            repo.ping()
        except Exception:  # noqa: BLE001
            log.exception("La base de datos no responde")
            return JSONResponse(
                status_code=503,
                content={"status": "error", "almacenamiento": repo.almacenamiento},
            )
        return {"status": "ok", "almacenamiento": repo.almacenamiento, "version": settings.app_version}

    @app.get("/api/incidencias")
    def listar(
        proyecto: Optional[str] = Query(None, pattern=SLUG),
        estado: Optional[Estado] = None,
        severidad: Optional[Severidad] = None,
        etiqueta: Optional[str] = Query(None, max_length=25),
        q: Optional[str] = Query(None, max_length=60),
        svc: ServicioIncidencias = Depends(servicio),
    ) -> List[dict]:
        filtros = Filtros(
            proyecto=proyecto,
            estado=estado,
            severidad=severidad,
            etiqueta=etiqueta.strip().lower() if etiqueta and etiqueta.strip() else None,
            q=q.strip() if q and q.strip() else None,
        )
        return svc.listar(filtros)

    @app.post("/api/incidencias", status_code=201)
    def crear(datos: IncidenciaCrear, svc: ServicioIncidencias = Depends(servicio)):
        return svc.crear(datos)

    @app.get("/api/incidencias/{proyecto}/{incidencia_id}")
    def obtener(proyecto: str, incidencia_id: str, svc: ServicioIncidencias = Depends(servicio)):
        try:
            return svc.obtener(proyecto, incidencia_id)
        except NoEncontrada:
            raise no_encontrada()

    @app.patch("/api/incidencias/{proyecto}/{incidencia_id}/estado")
    def cambiar_estado(
        proyecto: str,
        incidencia_id: str,
        cambio: CambioEstado,
        svc: ServicioIncidencias = Depends(servicio),
    ):
        try:
            return svc.cambiar_estado(proyecto, incidencia_id, cambio)
        except NoEncontrada:
            raise no_encontrada()
        except TransicionInvalida as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ConflictoConcurrencia:
            raise HTTPException(
                status_code=409,
                detail="Otra persona modificó la incidencia al mismo tiempo. Recarga e inténtalo de nuevo.",
            )

    @app.post("/api/incidencias/{proyecto}/{incidencia_id}/comentarios", status_code=201)
    def comentar(
        proyecto: str,
        incidencia_id: str,
        datos: ComentarioCrear,
        svc: ServicioIncidencias = Depends(servicio),
    ):
        try:
            return svc.comentar(proyecto, incidencia_id, datos)
        except NoEncontrada:
            raise no_encontrada()

    @app.delete("/api/incidencias/{proyecto}/{incidencia_id}", status_code=204)
    def eliminar(proyecto: str, incidencia_id: str, svc: ServicioIncidencias = Depends(servicio)):
        try:
            svc.eliminar(proyecto, incidencia_id)
        except NoEncontrada:
            raise no_encontrada()
        return Response(status_code=204)

    @app.get("/api/resumen")
    def resumen(svc: ServicioIncidencias = Depends(servicio)):
        return svc.resumen()

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def inicio():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
