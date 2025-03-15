"""
Healthcheck API
"""

import logging
from aiohttp import ClientConnectionError
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from satellite.server.dependencies.common import ConfigT, LRRClientT


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
async def lanraragi_healthcheck(config: ConfigT, client: LRRClientT):
    """
    Perform healthcheck against LANraragi server.

    Checks if the LRR_HOST, LRR_API_KEY are configured,
    if the LRR host is reachable and if the LRR_API_KEY works.
    """
    try:
        response = await client.get_shinobu_status()
        if response.status_code == 200:
            return JSONResponse({"message": f"LANraragi is configured properly! Targeting host: {config.LRR_HOST}"})
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
    finally:
        await client.close()