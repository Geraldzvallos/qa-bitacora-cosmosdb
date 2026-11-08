"""Esquemas de entrada y reglas del dominio (incidencias de calidad)."""
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class Severidad(str, Enum):
    BAJA = "BAJA"
    MEDIA = "MEDIA"
    ALTA = "ALTA"
    CRITICA = "CRITICA"


class Estado(str, Enum):
    ABIERTA = "ABIERTA"
    EN_PROGRESO = "EN_PROGRESO"
    RESUELTA = "RESUELTA"
    CERRADA = "CERRADA"


# Transiciones permitidas del ciclo de vida de una incidencia.
TRANSICIONES = {
    Estado.ABIERTA: {Estado.EN_PROGRESO, Estado.CERRADA},
    Estado.EN_PROGRESO: {Estado.RESUELTA, Estado.ABIERTA},
    Estado.RESUELTA: {Estado.CERRADA, Estado.ABIERTA},
    Estado.CERRADA: {Estado.ABIERTA},
}

SLUG = r"^[a-z0-9][a-z0-9-]{1,39}$"


def _limpiar(texto: str) -> str:
    return " ".join(texto.split())


class IncidenciaCrear(BaseModel):
    proyecto: str = Field(..., pattern=SLUG, description="Clave de partición, p. ej. 'tienda-web'")
    titulo: str = Field(..., min_length=5, max_length=120)
    descripcion: str = Field("", max_length=2000)
    severidad: Severidad = Severidad.MEDIA
    etiquetas: List[str] = Field(default_factory=list, max_length=8)
    reportado_por: str = Field(..., min_length=2, max_length=60)

    @field_validator("proyecto", mode="before")
    @classmethod
    def proyecto_minusculas(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("titulo", "reportado_por")
    @classmethod
    def sin_espacios_extra(cls, v: str) -> str:
        return _limpiar(v)

    @field_validator("etiquetas")
    @classmethod
    def normalizar_etiquetas(cls, v: List[str]) -> List[str]:
        vistas: List[str] = []
        for etiqueta in v:
            e = etiqueta.strip().lower()
            if not e:
                continue
            if len(e) > 25:
                raise ValueError("Cada etiqueta debe tener como máximo 25 caracteres")
            if e not in vistas:
                vistas.append(e)
        return vistas


class CambioEstado(BaseModel):
    estado: Estado
    autor: str = Field(..., min_length=2, max_length=60)


class ComentarioCrear(BaseModel):
    autor: str = Field(..., min_length=2, max_length=60)
    texto: str = Field(..., min_length=1, max_length=1000)


class Filtros(BaseModel):
    proyecto: Optional[str] = None
    estado: Optional[Estado] = None
    severidad: Optional[Severidad] = None
    etiqueta: Optional[str] = None
    q: Optional[str] = None
