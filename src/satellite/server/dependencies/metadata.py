from fastapi import Depends
from typing import Annotated, TypeAlias

from satellite.server.dependencies.common import ConfigT
from satellite.service.metadata import NhentaiArchivistMetadataService, PixivUtil2MetadataService

def get_nhentai_archivist_metadata_service(config: ConfigT):
    metadata_service = NhentaiArchivistMetadataService(config.METADATA_NHENTAI_ARCHIVIST_DB)
    yield metadata_service
NhentaiArchivistMetadataServiceT: TypeAlias = Annotated[NhentaiArchivistMetadataService, Depends(get_nhentai_archivist_metadata_service)]

def get_pixivutil2_metadata_service(config: ConfigT):
    metadata_service = PixivUtil2MetadataService(config.METADATA_PIXIVUTIL2_DB)
    yield metadata_service
PixivUtilMetadataServiceT: TypeAlias = Annotated[PixivUtil2MetadataService, Depends(get_pixivutil2_metadata_service)]