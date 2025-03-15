from fastapi import Depends
from typing import Annotated, TypeAlias

from satellite.server.dependencies.common import ConfigT, LRRClientT, LoggerT
from satellite.server.dependencies.nhdd.database import NhddDatabaseServiceT
from satellite.service.nhdd import DeduplicationService, Img2VecClient

async def get_img2vec_service(config: ConfigT, logger: LoggerT):
    img2vec = Img2VecClient(config.IMG2VEC_HOST)
    yield img2vec
    await img2vec.close()
Img2VecServiceT: TypeAlias = Annotated[Img2VecClient, Depends(get_img2vec_service)]

async def get_deduplication_service(lrr: LRRClientT, db: NhddDatabaseServiceT, img2vec: Img2VecServiceT, config: ConfigT, logger: LoggerT):
    dd_service = DeduplicationService(
        lrr, db, img2vec, config.IMG2VEC_WORKERS, 
        nhentai_archivist_dndm=config.NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH,
        lrr_contents_dir=config.LRR_CONTENTS_DIR,
        logger=logger
    )
    yield dd_service
    await dd_service.close()
DeduplicationServiceT: TypeAlias = Annotated[DeduplicationService, Depends(get_deduplication_service)]