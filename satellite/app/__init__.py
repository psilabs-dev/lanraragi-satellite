import logging
from pathlib import Path
import sys
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

from satellite.app import config
from satellite.app.routers import archives, database, healthcheck, metadata, upload
from satellite.service.database import DatabaseService
from satellite.utils.version import get_version

logger = logging.getLogger("uvicorn.satellite")

@asynccontextmanager
async def lifespan(_: FastAPI):
    # set up database.
    db = config.satellite_config.SATELLITE_DB_PATH
    if not db:
        raise KeyError("Database not configured!")
    db = Path(db)
    database = DatabaseService(db)
    await database.connect()
    if api_key:=config.satellite_config.SATELLITE_API_KEY:
        api_key = api_key.encode(encoding='utf-8')
        await database.register_api_key(api_key)
        logger.info("API key is registered into database.")
    logger.info(f"""Satellite is configured!
                
                Satellite Version:  {get_version()}
                Database:           {db}
                LANraragi Host:     {config.satellite_config.LRR_HOST}
""")
    yield

app = FastAPI(
    title="satellite",
    lifespan=lifespan
)

app.include_router(archives.router)
app.include_router(healthcheck.router)
app.include_router(metadata.router)
app.include_router(upload.router)
app.include_router(database.router)
