from fastapi import Depends
from typing import Annotated, TypeAlias

from satellite.server.dependencies.common import ConfigT
from satellite.service.nhdd import DEFAULT_EMBEDDING_DIMENSIONS, PostgresDatabaseService

async def get_postgres_service(config: ConfigT):
    database = PostgresDatabaseService(config.NHDD_DB, config.NHDD_DB_USER, config.NHDD_DB_HOST, config.NHDD_DB_PASS, DEFAULT_EMBEDDING_DIMENSIONS)
    yield database
    await database.close()
NhddDatabaseServiceT: TypeAlias = Annotated[PostgresDatabaseService, Depends(get_postgres_service)]