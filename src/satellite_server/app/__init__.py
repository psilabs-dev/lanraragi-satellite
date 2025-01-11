import asyncio
import logging
from pathlib import Path
import sys
import aiohttp
import aiohttp.client_exceptions
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

from lanraragi.client import LRRClient
from satellite_server.app import config
from satellite_server.app.routers import archives, database, healthcheck, metadata, upload
from satellite_server.service.database import DatabaseService
from satellite_server.utils.version import get_version

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

    # check if LRR is configured.
    lrr_host = None
    lrr_api_key = None
    lrr_version = None
    if config.satellite_config.LRR_HOST and config.satellite_config.LRR_API_KEY:
        retry_count = 0
        while True:
            try:
                lrr_host = config.satellite_config.LRR_HOST
                lrr_api_key = config.satellite_config.LRR_API_KEY
                client = LRRClient(lrr_host=lrr_host, lrr_api_key=lrr_api_key)
                server_info = await client.get_server_info()
                if server_info.status_code == 200:
                    lrr_version = server_info.version
                    break
                else:
                    logger.error(f"Failed to obtain server info from LRR: {server_info.error}")
                    break
            except aiohttp.client_exceptions.ClientConnectionError:
                if retry_count < 3:
                    time_to_sleep = 2 ** (retry_count + 3)
                    logger.warning(f"Cannot establish connection to LRR server; sleeping for {time_to_sleep}s...")
                    await asyncio.sleep(time_to_sleep)
                    retry_count += 1
                else:
                    logger.error("Failed to obtain server info from LRR due to connection issues.")
                    break
    else:
        logger.info("""
                    No LANraragi server detected! Satellite will continue to perform tasks that do not require the server.
                    To add a server, configure environment variables for LRR_HOST and LRR_API_KEY.
""")
    
    message = f"""Satellite is configured!

                    Satellite Version:  {get_version()}
                    Database:           {db}"""
    if commit_hash := config.satellite_config.SATELLITE_GIT_COMMIT_HASH:
        message += f"""
                    Commit Hash:        {commit_hash}"""
    if lrr_version:
        message += f"""
                    LANraragi Host:     {lrr_host}
                    LANraragi Version:  {lrr_version}
"""

    message += "\n"
    logger.info(message)
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
