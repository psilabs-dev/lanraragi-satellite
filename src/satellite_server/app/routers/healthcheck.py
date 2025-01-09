"""
Healthcheck API
"""

import logging
from aiohttp import ClientConnectionError
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from lanraragi.client import LRRClient
from satellite_server.app import config

# disable healthcheck logging to reduce noise.
class HealthcheckFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        return record.getMessage().find("/api/healthcheck") == -1
logging.getLogger("uvicorn.access").addFilter(HealthcheckFilter())

router = APIRouter(
    prefix="/api/healthcheck"
)

@router.get("")
async def healthcheck():
    return "success"

@router.get("/lanraragi")
async def lanraragi_healthcheck():
    """
    Perform healthcheck against LANraragi server.

    Checks if the LRR_HOST, LRR_API_KEY are configured,
    if the LRR host is reachable and if the LRR_API_KEY works.
    """
    try:
        lrr_host = config.satellite_config.LRR_HOST
        client = LRRClient(lrr_host=lrr_host, lrr_api_key=config.satellite_config.LRR_API_KEY)
        response = await client.get_shinobu_status()
        if response.status_code == 200:
            return JSONResponse({"message": f"LANraragi is configured properly! Targeting host: {lrr_host}"})
        else:
            return JSONResponse({
                "message": "Invalid LRR configuration: " + response.error
            }, status_code=500)
    except ClientConnectionError as connection_error:
        return JSONResponse({
            "message": "Connection error: " + str(connection_error)
        }, status_code=500)
    except KeyError as key_error:
        return JSONResponse({
            "message": "Invalid LRR configuration: " + str(key_error)
        }, status_code=500)
