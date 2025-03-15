from fastapi import Depends
from typing import Annotated, TypeAlias
from satellite.server.dependencies.common import ConfigT
from satellite.service.database import DatabaseService

def get_server_db_service(config: ConfigT):
    return DatabaseService(config.SATELLITE_DB_PATH)
DatabaseServiceT: TypeAlias = Annotated[DatabaseService, Depends(get_server_db_service)]