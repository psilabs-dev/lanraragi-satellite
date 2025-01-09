

import re
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from satellite_server.app import config
from satellite_server.service.database import DatabaseService


api_key_header = APIKeyHeader(name="Authorization")

def extract_api_key(api_key_header: str):
    """
    Gets API key from header.
    """
    pattern = re.compile('Bearer (.*)')
    result = pattern.findall(api_key_header)
    return result[0] if result else ""

async def is_valid_api_key_header(api_key_header: str = Security(api_key_header)):
    """
    Check if the API key header is valid.

    Format: `Authorization: Bearer $YOUR_API_KEY`
    """
    database = DatabaseService(config.satellite_config.SATELLITE_DB_PATH)
    api_key = extract_api_key(api_key_header)
    api_key_b = api_key.encode(encoding='utf-8')
    if await database.verify_api_key(api_key_b):
        return True
    raise HTTPException(status_code=401, detail="Invalid API key.")
