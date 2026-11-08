"""Configuración de la aplicación a partir de variables de entorno."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    cosmos_endpoint: str
    cosmos_key: str
    cosmos_database: str
    cosmos_container: str
    app_name: str
    app_version: str

    @property
    def cosmos_enabled(self) -> bool:
        """Cosmos DB se usa solo si hay endpoint y clave; si no, la app usa memoria."""
        return bool(self.cosmos_endpoint and self.cosmos_key)


def get_settings() -> Settings:
    return Settings(
        cosmos_endpoint=os.getenv("COSMOS_ENDPOINT", "").strip(),
        cosmos_key=os.getenv("COSMOS_KEY", "").strip(),
        cosmos_database=os.getenv("COSMOS_DATABASE", "bitacora").strip() or "bitacora",
        cosmos_container=os.getenv("COSMOS_CONTAINER", "incidencias").strip() or "incidencias",
        app_name="QA Bitácora",
        app_version=os.getenv("APP_VERSION", "1.0.0"),
    )
