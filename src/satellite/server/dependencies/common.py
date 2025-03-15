from fastapi import Depends
import logging
from typing import Annotated, TypeAlias

from lanraragi.client import LRRClient
from satellite.server.config import SatelliteConfig

LOGGER = logging.getLogger("uvicorn.satellite")
def get_logger():
    return LOGGER
LoggerT: TypeAlias = Annotated[logging.Logger, Depends(get_logger)]

def get_config():
    config = SatelliteConfig()
    return config
ConfigT: TypeAlias = Annotated[SatelliteConfig, Depends(get_config)]

async def get_lanraragi_client(config: ConfigT):
    client = LRRClient(lrr_host=config.LRR_HOST, lrr_api_key=config.LRR_API_KEY, ssl=config.LRR_SSL_VERIFY)
    yield client
    await client.close()
LRRClientT: TypeAlias = Annotated[LRRClient, Depends(get_lanraragi_client)]