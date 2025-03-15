"""
Satellite Database API

Offers ways to reset the server's various tables.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from satellite.server.auth import is_valid_api_key_header
from satellite.server.dependencies.database import DatabaseServiceT

router = APIRouter(
    prefix="/api/database",
    dependencies=[Depends(is_valid_api_key_header)]
)

@router.delete("/auth")
async def reset_auth_table(database: DatabaseServiceT):
    await database.drop_auth_table()
    await database.create_auth_table()
    return JSONResponse({
        "message": "auth reset."
    })

@router.delete("/archive_scan")
async def reset_archive_scan_table(database: DatabaseServiceT):
    await database.drop_archive_scan_table()
    await database.create_archive_scan_table()
    return JSONResponse({
        "message": "archive_scan reset."
    })

@router.delete("/archive_upload")
async def reset_archive_upload_table(database: DatabaseServiceT):
    await database.drop_archive_upload_table()
    await database.create_archive_upload_table()
    return JSONResponse({
        "message": "archive_upload reset."
    })

@router.delete("/metadata_plugin_task")
async def reset_metadata_plugin_task(database: DatabaseServiceT):
    await database.drop_metadata_plugin_task_table()
    await database.create_metadata_plugin_task_table()
    return JSONResponse({
        "message": "metadata_plugin_task reset."
    })
