import asyncio
import logging
from pathlib import Path
import aiohttp
import aiohttp.client_exceptions
from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager

from lanraragi.client import LRRClient
from satellite.server.dependencies.common import get_config
from satellite.server.routers import archives, database, healthcheck, metadata
try:
    from satellite.service.nhdd import DEFAULT_EMBEDDING_DIMENSIONS, Img2VecClient, PostgresDatabaseService
    from satellite.server.routers.nhdd import nhdd_router
except ImportError:
    nhdd_router = None
from satellite.service.database import DatabaseService
from satellite.utils.version import get_version

logger = logging.getLogger("uvicorn.satellite")

@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Satellite server setup and teardown lifecycle.
    Because dependencies cannot be brought in on a lifespan function, we will be instantiating
    temporary instances of those objects instead.
    """
    config = get_config()

    db = config.SATELLITE_DB_PATH
    if not db:
        raise KeyError("Database not configured!")
    db = Path(db)
    database = DatabaseService(db)
    await database.connect()
    if api_key:=config.SATELLITE_API_KEY:
        api_key = api_key.encode(encoding='utf-8')
        await database.register_api_key(api_key)
        logger.info("API key is registered into database.")

    # check if LRR is configured.
    if not config.LRR_SSL_VERIFY:
        logger.warning("SSL verification for LANraragi client is disabled.")
    lrr_host = None
    lrr_version = None
    if config.LRR_HOST and config.LRR_API_KEY:
        retry_count = 0
        while True:
            try:
                async with LRRClient(
                    lrr_host=config.LRR_HOST, lrr_api_key=config.LRR_API_KEY, ssl=config.LRR_SSL_VERIFY
                ) as client:
                    lrr_host = config.LRR_HOST
                    server_info = await client.get_server_info()
                    if server_info.status_code == 200:
                        lrr_version = server_info.version
                        break
                    else:
                        logger.error(f"Failed to obtain server info from LRR: {server_info.error}")
                        break
            except (
                aiohttp.client_exceptions.ClientConnectorCertificateError,
                aiohttp.client_exceptions.ClientConnectorSSLError
            ) as cert_or_ssl_error:
                logger.error(f"Satellite could not establish a secure SSL connection to the LRR server! Fix the SSL issue or disable verification: {cert_or_ssl_error}")
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
                    Server Database:    {db} (SQLite)"""
    if nhdd_router and config.get_is_nhdd_configured():
        try:
            nhdd_db = PostgresDatabaseService(config.NHDD_DB, config.NHDD_DB_USER, config.NHDD_DB_HOST, config.NHDD_DB_PASS, DEFAULT_EMBEDDING_DIMENSIONS)
            img2vec = Img2VecClient(config.IMG2VEC_HOST)
            try:
                if not (await img2vec.get_healthcheck()):
                    logger.error("Failed to connect to img2vec service! Img2vec service will not be available.")
            except Exception as exception:
                logger.error(f"Failed to connect to img2vec service! Img2vec service will not be available. {exception}")
            await nhdd_db.setup_database()
            message += f"""
                    NHDD Database:      {config.NHDD_DB_HOST} (PostgreSQL)"""
        except Exception as exception:
            logger.error(f"Unhandled exception occurred during nhdd setup: {exception}")
        finally:
            await nhdd_db.close()
            await img2vec.close()
    if commit_hash := config.SATELLITE_GIT_COMMIT_HASH:
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
    title="Satellite Server",
    lifespan=lifespan,
    docs_url=None,
    openapi_url=None,
    redoc_url=None,
)

app.include_router(archives.router)
app.include_router(healthcheck.router)
app.include_router(metadata.router)
app.include_router(database.router)
if nhdd_router and get_config().get_is_nhdd_configured():
    logger.info("NHDD service is enabled.")
    app.include_router(nhdd_router)