import asyncio
import enum
import io
import logging
import os
from pathlib import Path
import random
import tempfile
import time
import traceback
from typing import Dict, List, Set, Tuple, Union, overload
import zipfile
import PIL.Image
import aiohttp
import aiohttp.client_exceptions
import dotenv
import numpy
import pgvector.psycopg
import psycopg

from common.client import AbstractAsyncHTTPContextClient
from lanraragi.client import LRRClient
from lanraragi.utils import get_source_from_tags
from satellite.utils.fdiscover import discover_all_archives_in_folder

LOGGER = logging.getLogger("NHDD")

# >>>>> COMMON >>>>>

DEFAULT_EMBEDDING_DIMENSIONS = 512

def cosine_similarity(embedding_1: List[float], embedding_2: List[float]):
    embedding_1 = numpy.array(embedding_1)
    embedding_2 = numpy.array(embedding_2)
    result = numpy.dot(embedding_1, embedding_2) / (numpy.linalg.norm(embedding_1) * numpy.linalg.norm(embedding_2))
    return result

def _convert_embedding(embedding: str) -> List[float]:
    resp = [float(x.strip()) for x in embedding[1:-1].split(',')]
    return resp

def is_subsequence(embeddings_1: List[float], embeddings_2: List[float], min_similarity: float=0.95) -> Tuple[bool, bool]:
    """
    CPU-bound part of archive similarity computation.
    Compares the first list of embeddings to the second and checks whether its
    embeddings are members in sorted order.
    
    An embedding e belongs to a set of embeddings if there exists a similar 
    embedding e' ~ e in said set. Uses cosine similarity.
    """
    t_count = len(embeddings_1)
    s_count = len(embeddings_2)
    if t_count > s_count:
        return (False, False)
    offset = 0
    for i in range(t_count):
        while i + offset < s_count:
            similarity_score = cosine_similarity(embeddings_1[i], embeddings_2[i+offset])
            if similarity_score > min_similarity:
                LOGGER.debug(f"page-{i+1} ~ page-{i+offset+1}")
                if i == t_count-1:
                    return (True, t_count != s_count)
                else:
                    break
            else:
                LOGGER.debug(f"page-{i+1} !~ page-{i+offset+1}")
                offset += 1
                continue
    return (False, False)

def _get_source(tags: List[str]) -> int:
    """
    Return source of a tag ID, otherwise return -1 if it does not exist.
    """
    for tag in tags:
        if tag.startswith("source:nhentai.net"):
            return int(tag.split("/")[-1])
    return -1

class CreateEmbeddingResponse:
    status: int
    embeddings: List[float]

class BatchCreateEmbeddingResponse:
    status: int
    embeddings_list: List[List[float]]

class NhentaiArchivistDeduplicationResponse:
    deleted_duplicates: int = 0
    duplicate_size: int = 0
    delete_failed: int = 0
    lrr_contents_size: int = 0

class Img2VecClient(AbstractAsyncHTTPContextClient):
    """
    Git repository: https://github.com/psilabs-dev/img2vec
    """
    
    def __init__(self, host: str, session: Union[None, aiohttp.ClientSession]=None, ssl: bool=True):
        self.host = host
        super().__init__(session, ssl=ssl)

    def build_url(self, api: str) -> str:
        return f"{self.host}{api}"

    @staticmethod
    def to_bytes(image: PIL.Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

    async def get_healthcheck(self) -> bool:
        """
        Check if service is reachable.
        """
        url = self.build_url("/api/healthcheck")
        async with (await self._get_session()).get(url=url) as async_response:
            return async_response.status == 200

    async def create_embedding(self, image: PIL.Image.Image) -> CreateEmbeddingResponse:
        url = self.build_url("/api/embeddings")
        response = CreateEmbeddingResponse()
        image_bytes = self.to_bytes(image)
        data = aiohttp.FormData(quote_fields=False)
        data.add_field('file', image_bytes)
        async with (await self._get_session()).post(url=url, data=data) as async_response:
            response.status = async_response.status
            if async_response.status == 200:
                response.embeddings = (await async_response.json()).get("embeddings")
        return response

    async def create_batch_embeddings(self, images: List[PIL.Image.Image]) -> BatchCreateEmbeddingResponse:
        url = self.build_url("/api/embeddings-batch")
        response = BatchCreateEmbeddingResponse()
        data = aiohttp.FormData(quote_fields=False)
        for (i, image) in enumerate(images):
            image_bytes = self.to_bytes(image)
            data.add_field('files', image_bytes, filename=f'image_{i}.png')
        async with (await self._get_session()).post(url=url, data=data) as async_response:
            response.status = async_response.status
            if async_response.status == 200:
                response.embeddings_list = (await async_response.json()).get("embeddings_list")
        return response

# <<<<< COMMON <<<<<

# >>>>> MODEL >>>>>
class CompareArchiveResponse:

    duplicate_archive_id: str

class KeepReasonAndScoreEnum(enum.Enum):
    IS_IN_STATIC_CATEGORY           = (0, 2 ** 4)
    HAS_HIGHER_FAVORITE_COUNT       = (1, 2 ** 3)
    HAS_DECENSORED_TAG              = (2, 2 ** 2)
    HAS_HIGHER_TAG_COUNT            = (3, 2 ** 2)
    HAS_NO_ROUGH_TRANSLATION        = (4, 2 ** 2)
    HAS_NO_POOR_GRAMMAR             = (5, 2 ** 2)
    IS_MORE_RECENT                  = (6, 2 ** 1)
    HAS_READING_PROGRESS            = (7, 2 ** 0)

    def __repr__(self):
        return f"{self.name} (score={self.get_score()})"
    
    def get_score(self):
        return self.value[1]

class MetadataPluginStatus(enum.Enum):
    SUCCESS     = 0
    FAILED      = 1
    PENDING     = 2
    NOT_FOUND   = 3

class ArchiveEmbeddingJobStatus(enum.Enum):
    SUCCESS     = 0
    FAILED      = 1
    PENDING     = 2
    NOT_FOUND   = 3
    SKIPPED     = 4

class NhArchiveLanguage(enum.Enum):
    ENGLISH         = 0
    JAPANESE        = 1
    CHINESE         = 2
    OTHER           = 3
    NO_TRANSLATE    = 4

class CreatePageResponse:
    status: ArchiveEmbeddingJobStatus
    pages: int
# <<<<< MODEL <<<<<

def get_language(tags: List[str]) -> NhArchiveLanguage:
    languages = set()
    for tag in tags:
        match tag.lower():
            case "language:japanese":
                languages.add(NhArchiveLanguage.JAPANESE)
            case "language:english":
                languages.add(NhArchiveLanguage.ENGLISH)
            case "language:chinese":
                languages.add(NhArchiveLanguage.CHINESE)
            case "language:translated":
                languages.add(NhArchiveLanguage.OTHER)
    if languages:
        if NhArchiveLanguage.ENGLISH in languages:
            return NhArchiveLanguage.ENGLISH
        if NhArchiveLanguage.CHINESE in languages:
            return NhArchiveLanguage.CHINESE
        if NhArchiveLanguage.JAPANESE in languages:
            return NhArchiveLanguage.JAPANESE
        return NhArchiveLanguage.OTHER
    return NhArchiveLanguage.NO_TRANSLATE

# >>>>> TABLE GET/SET >>>>>
def get_archive_embedding_job_pages(row):
    return row[1]
def get_archive_embedding_job_status(row):
    return row[2]

def get_page_archive_id(row):
    return row[0]
def get_page_embedding(row):
    return row[2]

# <<<<< TABLE GET/SET <<<<<

# >>>>> DATABASE >>>>>
class PostgresDatabaseService:
    """
    Interface for postgres vector database. May throw psycopg.OperationalError which
    should be handled.
    """

    def __init__(self, database: str, user: str, host: str, password: str, embedding_dim: int):
        self.database = database
        self.user = user
        self.host = host
        self.password = password
        self.embedding_dim = embedding_dim

    async def close(self):
        return

    async def get_connection(self):
        return await psycopg.AsyncConnection.connect(f"dbname='{self.database}' user='{self.user}' host='{self.host}' password='{self.password}'")

    async def setup_database(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('CREATE EXTENSION IF NOT EXISTS vector')
            await pgvector.psycopg.register_vector_async(aconn)
            LOGGER.info("Registered vector extension.")
            await aconn.execute(
                '''
                CREATE TABLE IF NOT EXISTS archive_embedding_job (
                    archive_id VARCHAR(255) PRIMARY KEY,
                    pages INTEGER,
                    status VARCHAR(255),
                    last_updated REAL,
                    message TEXT
                )
                '''
            )
            LOGGER.info("Created archive embedding job table.")
            await aconn.execute(
                '''
                CREATE TABLE IF NOT EXISTS archive_metadata_job (
                    archive_id VARCHAR(255) PRIMARY KEY,
                    status VARCHAR(255),
                    message TEXT,
                    last_updated REAL
                )
                '''
            )
            LOGGER.info("Created archive metadata job.")
            await aconn.execute(
                f'''
                CREATE TABLE IF NOT EXISTS page (
                    archive_id VARCHAR(255),
                    page_no INTEGER,
                    embedding VECTOR({self.embedding_dim}),
                    CONSTRAINT unique_archive_page UNIQUE (archive_id, page_no)
                )
                ''')
            await aconn.execute('CREATE INDEX IF NOT EXISTS page_index ON page USING hnsw (embedding vector_cosine_ops)')
            LOGGER.info("Created page embedding table.")
            await aconn.execute(
                '''
                CREATE TABLE IF NOT EXISTS subarchive_map (
                    archive_id VARCHAR(255) PRIMARY KEY,
                    leq VARCHAR(255)
                )
                '''
            )
            LOGGER.info("Created proper subarchive map table.")
            await aconn.execute(
                '''
                CREATE TABLE IF NOT EXISTS nhentai_archive (
                    archive_id VARCHAR(255) PRIMARY KEY,
                    nhentai_id VARCHAR(255),
                    favorites INTEGER,
                    language VARCHAR(255),
                    last_updated REAL
                )
                '''
            )
            LOGGER.info("Created nhentai archive table.")

    async def clear_archive_embedding_job_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM archive_embedding_job')

    async def drop_archive_embedding_job_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DROP TABLE IF EXISTS archive_embedding_job')

    async def drop_page_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DROP TABLE IF EXISTS page')

    async def clear_page_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM page')

    async def drop_subarchive_map_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DROP TABLE IF EXISTS subarchive_map')
    
    async def clear_subarchive_map_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM subarchive_map')

    async def drop_nhentai_metadata_job_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DROP TABLE IF EXISTS archive_metadata_job')

    async def clear_archive_metadata_job_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM archive_metadata_job')

    async def drop_nhentai_archive_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DROP TABLE IF EXISTS nhentai_archive')

    async def clear_nhentai_archive_table(self):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM nhentai_archive')

    # >>>>> ARCHIVE EMBEDDING CRUD >>>>>
    async def get_archive_embedding_job(self, archive_id: str) -> Union[Tuple[str, int, str, float, str], None]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('SELECT * FROM archive_embedding_job WHERE archive_id = %s', (archive_id,))).fetchone()
            return row

    async def get_pages_from_aej(self, archive_id: str) -> int:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('SELECT pages FROM archive_embedding_job WHERE archive_id = %s', (archive_id,))).fetchone()
            if row:
                return row[0]
            return None

    async def get_num_archive_embedding_jobs_by_status(self, status: ArchiveEmbeddingJobStatus) -> int:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('SELECT COUNT(*) FROM archive_embedding_job WHERE status = %s', (status.name,))).fetchone()
            if row:
                return row[0]
            return 0

    async def get_archive_embedding_jobs_by_status(self, status: str, limit: int=None) -> List[Tuple[str, int, str, float, str]]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            query = 'SELECT * FROM archive_embedding_job WHERE status = %s ORDER BY archive_id ASC'
            params = [status]
            if limit:
                query += ' LIMIT %s'
                params.append(limit)
            row = await (await cursor.execute(query, params)).fetchall()
            return row

    async def insert_archive_embedding_job(self, archive_id: str, pages: int, status: str, message: str=None):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                INSERT INTO archive_embedding_job aej(archive_id, pages, status, last_updated, message)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (archive_id)
                                DO NOTHING
                                ''', (archive_id, pages, status, time.time(), message))
    
    async def insert_archive_embedding_jobs(self, aej_items: List[Tuple[str, int, str, str]]):
        async with await self.get_connection() as aconn, aconn.transaction(), aconn.cursor() as cursor:
            await cursor.executemany('''
                                    INSERT INTO archive_embedding_job (archive_id, pages, status, last_updated, message)
                                    VALUES (%s, %s, %s, %s, %s)
                                    ON CONFLICT (archive_id)
                                    DO NOTHING
                                    ''', [(job[0], job[1], job[2], time.time(), job[3]) for job in aej_items])

    async def update_archive_embedding_job(self, archive_id: str, status: str, message: str=None):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                UPDATE archive_embedding_job
                                SET status = %s, last_updated = %s, message = %s
                                WHERE archive_id = %s
                                ''', (status, time.time(), message, archive_id))

    # <<<<< ARCHIVE EMBEDDING CRUD <<<<<

    # >>>>> ARCHIVE METADATA CRUD >>>>>
    async def get_archive_metadata_job(self, archive_id: str) -> Union[Tuple[str, MetadataPluginStatus, str, float], None]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('''
                                               SELECT 
                                               archive_id, status, message, last_updated
                                               FROM archive_metadata_job WHERE archive_id = %s
                                               ''', (archive_id,))).fetchone()
            if row:
                return row[0]
            return row

    async def get_archive_metadata_jobs_by_status(self, status: MetadataPluginStatus) -> List[str]:
        """
        Get list of archive IDs by metadata job status.
        """
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute('SELECT archive_id FROM archive_metadata_job WHERE status = %s', (status.name,))).fetchall()
            for i in range(len(rows)):
                rows[i] = rows[i][0]
            return rows

    async def get_num_archive_metadata_jobs_by_status(self, status: MetadataPluginStatus) -> int:
        """
        Return number of archive metadata jobs by status (e.g. for tracking).
        """
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('SELECT COUNT(*) FROM archive_metadata_job WHERE status = %s', (status.name,))).fetchone()
            return row[0]

    async def insert_archive_metadata_job(self, archive_id: str, status: MetadataPluginStatus, message: str=None):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute(
                '''
                INSERT INTO archive_metadata_job (archive_id, status, message, last_updated)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (archive_id)
                DO NOTHING
                ''', (archive_id, status.name, message, time.time())
            )
    
    async def update_archive_metadata_job(self, archive_id: str, status: MetadataPluginStatus, message: str=None):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                UPDATE archive_metadata_job
                                SET status = %s, message = %s
                                WHERE archive_id = %s
                                ''', (status.name, message, archive_id))

    async def delete_archive_metadata_job(self, archive_id: str):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM archive_metadata_job WHERE archive_id = %s', (archive_id,))

    # <<<<< ARCHIVE METADATA CRUD <<<<<

    # >>>>> PAGE CRUD >>>>>

    async def get_page(self, archive_id: str, page_no: int) -> Union[None, Tuple[str, int, List[float]]]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('''
                                              SELECT * FROM page WHERE archive_id = %s AND page_no = %s
                                              ''', (archive_id, page_no))).fetchone()
            result = (row[0], row[1], _convert_embedding(row[2]))
            return result

    async def get_pages_by_archive_id(self, archive_id: str) -> List[Tuple[str, str, List[float]]]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute('''
                                               SELECT * FROM page WHERE archive_id = %s ORDER BY page_no ASC
                                               ''', (archive_id,))).fetchall()
            for i in range(len(rows)):
                rows[i][2] = _convert_embedding(rows[i][2])
            return rows

    async def get_count_pages_by_archive_id(self, archive_id: str) -> int:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute('''
                                               SELECT COUNT(*) FROM page WHERE archive_id = %s
                                               ''', (archive_id,))).fetchone()
            return rows[0]

    async def get_embeddings_by_archive_id(self, archive_id: str) -> List[List[float]]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute(
                'SELECT embedding FROM page WHERE archive_id = %s ORDER BY page_no ASC', (archive_id,)
            )).fetchall()
            for i in range(len(rows)):
                rows[i] = _convert_embedding(rows[i][0])
            return rows

    async def get_pages_by_embedding_and_cosine_dist(
            self, embedding: Union[str, List[float]], min_similarity: float=0.95, page_no: int=None, exclude_arcid: str=None
    ) -> List[Tuple[str, str, List[float]]]:
        max_distance = 1 - min_similarity
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = None
            if page_no and exclude_arcid:
                rows = await (
                    await cursor.execute(
                        'SELECT * FROM page WHERE embedding <=> %s <= %s AND page_no = %s AND archive_id != %s',
                        (embedding, max_distance, page_no, exclude_arcid)
                    )
                ).fetchall()
            elif page_no:
                rows = await (
                    await cursor.execute(
                        'SELECT * FROM page WHERE embedding <=> %s <= %s AND page_no = %s',
                        (embedding, max_distance, page_no)
                    )
                ).fetchall()
            elif exclude_arcid:
                rows = await (
                    await cursor.execute(
                        'SELECT * FROM page WHERE embedding <=> %s <= %s AND archive_id != %s',
                        (embedding, max_distance, exclude_arcid)
                    )
                ).fetchall()
            else:
                rows = await (
                    await cursor.execute(
                        'SELECT * FROM page WHERE embedding <=> %s <= %s',
                        (embedding, max_distance)
                    )
                ).fetchall()
            for i in range(rows):
                rows[i][2] = _convert_embedding(rows[i][2])
            return rows

    @overload
    async def insert_page(self, archive_id: str, page_no: int, embedding: str):
        ...

    @overload
    async def insert_page(self, archive_id: str, page_no: int, embedding: List[float]):
        ...

    async def insert_page(self, archive_id: str, page_no: int, embedding: Union[str, List[float]]):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute(
                '''
                INSERT INTO page (archive_id, page_no, embedding)
                VALUES (%s, %s, %s)
                ON CONFLICT (archive_id, page_no)
                DO NOTHING
                ''', (archive_id, page_no, embedding)
            )

    async def insert_pages(self, page_items: List[Tuple[str, int, str]]):
        """
        Takes a list of page items (archive_id, page_no, embedding) and uploads them as rows into the page
        table.
        """
        async with await self.get_connection() as aconn, aconn.transaction(), aconn.cursor() as cursor:
            await cursor.executemany('''
                                     INSERT INTO page (archive_id, page_no, embedding)
                                     VALUES (%s, %s, %s)
                                     ON CONFLICT (archive_id, page_no)
                                     DO NOTHING
                                     ''', page_items)

    async def delete_page_by_archive_id(self, archive_id: str):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('DELETE FROM page WHERE archive_id = %s', (archive_id,))

    # <<<<< PAGE CRUD <<<<<

    # >>>>> PROPER SUBARCHIVE CRUD >>>>>

    async def get_proper_subarchive(self, archive_id: str) -> Union[Tuple[str, str], None]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('''
                                              SELECT * FROM subarchive_map WHERE archive_id = %s
                                              ''', (archive_id,))).fetchone()
            return row

    async def get_root_suparchive(self, archive_id: str) -> Union[str, None]:
        """
        Get the root of an archive ID.

        subarchive_map <=> a collection of disjoint inverted trees, i.e. each row
        is of the form (S, T).

        A "root" or "max" of a key "S" is obtained by following the sequence
        of rows in the database, (S, S1) -> (S1, S2) -> ... until a value (Sn, T) is obtained
        such that either (T, *) does not exist or (T, T) exists.
        """
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('''
                                        WITH RECURSIVE chain AS (
                                            SELECT archive_id, leq FROM subarchive_map
                                            UNION ALL
                                            SELECT c.archive_id, psm.leq
                                            FROM chain AS c
                                            JOIN subarchive_map AS psm
                                            ON c.leq = psm.archive_id
                                            WHERE psm.archive_id <> psm.leq
                                        )
                                        SELECT DISTINCT ON (archive_id) archive_id, leq AS root
                                        FROM chain c
                                        WHERE NOT EXISTS (
                                            SELECT 1 FROM subarchive_map psm
                                            WHERE psm.archive_id = psm.leq
                                            AND psm.archive_id <> psm.leq
                                        )
                                        ORDER BY archive_id
                                        ''')).fetchone()
            if row:
                return row[0]
            return row

    async def get_subarchive_map_children_by_archive_id(self, archive_id: str) -> List[str]:
        'get depth 1' # TODO: get all children
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute('''
                                               SELECT archive_id FROM subarchive_map WHERE leq = %s AND archive_id != %s
                                               ''', (archive_id, archive_id))).fetchall()
            return [r[0] for r in rows]

    async def get_duplicate_archives(self) -> List[str]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute('SELECT archive_id FROM subarchive_map WHERE archive_id != leq')).fetchall()
            for i in range(len(rows)):
                rows[i] = rows[i][0]
            return rows

    async def insert_subarchive_map(self, archive_id: str, leq: str):
        async with await self.get_connection() as aconn, aconn.transaction(), aconn.cursor() as cursor:
            await cursor.execute('''
                                 INSERT INTO subarchive_map (archive_id, leq)
                                 VALUES (%s, %s)
                                 ON CONFLICT (archive_id)
                                 DO NOTHING
                                 ''', (archive_id, leq))

    async def update_subarchive_map(self, archive_id: str, leq: str):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                UPDATE subarchive_map
                                SET archive_id = %s, leq = %s
                                WHERE archive_id = %s
                                ''', (archive_id, leq))
    
    async def delete_subarchive_map(self, archive_id: str):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                DELETE FROM subarchive_map WHERE archive_id = %s
                                ''', (archive_id,))
            
    async def delete_subarchive_map_children(self, archive_id: str):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                DELETE FROM subarchive_map WHERE leq = %s AND archive_id != %s
                                ''', (archive_id, archive_id))

    # <<<<< PROPER SUBARCHIVE CRUD <<<<<

    # >>>>> NHENTAI ARCHIVE CRUD >>>>>
    async def get_nhentai_archive_favorites(self, archive_id: str) -> int:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('SELECT favorites FROM nhentai_archive WHERE archive_id = %s', (archive_id,))).fetchone()
            if row:
                return row[0]
            return 0

    async def get_nhentai_archive(self, archive_id: str) -> Union[Tuple[str, str, int, NhArchiveLanguage, float], None]:
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            row = await (await cursor.execute('''
                                               SELECT 
                                               archive_id, nhentai_id, favorites, language, last_updated
                                               FROM nhentai_archive WHERE archive_id = %s
                                               ''', (archive_id,))).fetchone()
            if row:
                row[3] = NhArchiveLanguage[row[3]]
            return row

    async def get_nhentai_archives_by_favorites(self, favorites: int, limit: int) -> List[Tuple[str, str, int, NhArchiveLanguage, float]]:
        """
        Get nhentai archives by favorites (e.g. -1) for tasks like updating favorites for an archive.
        These archive IDs must not already exist in the metadata tasks database.
        """
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute('''
                                               SELECT archive_id, nhentai_id, favorites, language, last_updated
                                               FROM nhentai_archive nha
                                               WHERE favorites = %s
                                               AND NOT EXISTS (
                                               SELECT 1 FROM archive_metadata_job amj WHERE amj.archive_id = nha.archive_id
                                               )
                                               LIMIT %s
                                               ''', (favorites, limit))).fetchall()
            return rows
        
    async def get_nhentai_archive_metadata_tasks_by_status(
            self, statuses: List[MetadataPluginStatus], limit: int=None
    ) -> List[Tuple[str, str, int, NhArchiveLanguage, float]]:
        statuses_formatted = ", ".join(f"'{status.name}'" for status in statuses)
        query = f'''
        SELECT archive_id, nhentai_id, favorites, language, last_updated
        FROM nhentai_archive nha
        WHERE EXISTS (
        SELECT 1 FROM archive_metadata_job amj 
        WHERE amj.status IN ({statuses_formatted}) AND amj.archive_id = nha.archive_id
        )
        '''
        params = []
        if limit is not None:
            query += ' LIMIT %s'
            params.append(limit)
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute(query, params=params)).fetchall()
            return rows

    async def insert_nhentai_archive(self, archive_id: str, nhentai_id: str, favorites: int, language: NhArchiveLanguage):
        async with await self.get_connection() as aconn, aconn.transaction(), aconn.cursor() as cursor:
            await cursor.execute('''
                                 INSERT INTO nhentai_archive (archive_id, nhentai_id, favorites, language, last_updated)
                                 VALUES (%s, %s, %s, %s, %s)
                                 ON CONFLICT (archive_id)
                                 DO NOTHING
                                 ''', (archive_id, nhentai_id, favorites, language.name, time.time()))

    async def update_nhentai_archive_favorites(self, archive_id: str, favorites: int):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                UPDATE nhentai_archive
                                SET archive_id = %s, favorites = %s, last_updated = %s
                                WHERE archive_id = %s
                                ''', (archive_id, favorites, time.time(), archive_id))
    
    async def delete_nhentai_archive(self, archive_id: str):
        async with await self.get_connection() as aconn, aconn.transaction():
            await aconn.execute('''
                                DELETE FROM subarchive_map WHERE archive_id = %s
                                ''', (archive_id,))

    # <<<<< NHENTAI ARCHIVE CRUD <<<<<

    # >>>>> COMPOSITE METHODS >>>>>
    async def get_arcids_by_similar_first_page(self, archive_id: str, min_similarity: float=0.95, restrict_language: bool=False) -> List[str]:
        """
        Get all archives with similar first pages as the provided archive ID, (potentially restricted to same language)
        as given in nhentai_archive table.
        """
        max_distance = 1 - min_similarity
        query = """
        SELECT p2.archive_id
        FROM page p1
        JOIN nhentai_archive na1 ON na1.archive_id = p1.archive_id
        JOIN page p2 ON p2.page_no = 1
        JOIN nhentai_archive na2 ON na2.archive_id = p2.archive_id
        WHERE p1.archive_id = %s
        AND p1.page_no = 1
        AND p2.archive_id <> na1.archive_id
        AND (p1.embedding <=> p2.embedding) < %s
        """
        if restrict_language:
            query += " AND na2.language = na1.language"
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute(query, (archive_id, max_distance))).fetchall()
            for i in range(len(rows)):
                rows[i] = rows[i][0]
            return rows

    async def get_arcids_by_page_similar_to_first_page_2(
        self,
        archive_id: str,
        min_similarity: float = 0.95,
        restrict_language: bool = False
    ) -> List[str]:
        """
        Gets all page.archive_id whose (page.embedding <=> the given archive's first-page embedding) < max_distance,
        for some page in that archive. The 'restrict_language' flag ensures we only pick archives with the
        same language as the given archive.
        """
        max_distance = 1 - min_similarity
        query = """
            SELECT DISTINCT p2.archive_id
            FROM page p1
            JOIN nhentai_archive na1    ON na1.archive_id = p1.archive_id
            JOIN page p2                ON p2.archive_id <> p1.archive_id
            JOIN nhentai_archive na2    ON na2.archive_id = p2.archive_id
            WHERE p1.archive_id = %s
            AND p1.page_no = 1
            AND (p1.embedding <=> p2.embedding) < %s
        """
        if restrict_language:
            query += " AND na2.language = na1.language"

        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute(query, (archive_id, max_distance))).fetchall()
            return [r[0] for r in rows]

    async def get_archives_not_in_subarchive_map(
            self, language: NhArchiveLanguage=None, limit: int=None
    ) -> List[str]:
        """
        Return list of archive IDs A from nhentai_archive such that (A, *) does not exist in mapping, and whose page embeddings
        have been inserted to the database successfully.
        """
        embedding_job_statuses = [ArchiveEmbeddingJobStatus.SKIPPED, ArchiveEmbeddingJobStatus.SUCCESS]
        embedding_job_filter = " AND archive_embedding_job.status IN (" + ', '.join(f"'{status.name}'" for status in embedding_job_statuses) + ")"

        query = f'''
        SELECT archive_id
        FROM nhentai_archive
        WHERE EXISTS (
            SELECT 1 FROM archive_embedding_job
            WHERE archive_embedding_job.archive_id = nhentai_archive.archive_id 
            {embedding_job_filter}
        )
        AND NOT EXISTS (SELECT 1 FROM subarchive_map WHERE subarchive_map.archive_id = nhentai_archive.archive_id)
        '''
        params = []
        if language:
            query += ' AND language = %s'
            params.append(language.name)
        if limit is not None:
            query += ' LIMIT %s'
            params.append(limit)
        async with await self.get_connection() as aconn, aconn.cursor() as cursor:
            rows = await (await cursor.execute(query, params)).fetchall()
            rows = [r[0] for r in rows]
            return rows

    # <<<<< COMPOSITE METHODS <<<<<

# <<<<< DATABASE <<<<<

# >>>>> DEDUPLICATION >>>>>

class DeduplicationService:

    categorized_arcids: Set[str]
    logger: logging.Logger

    def __init__(
            self, lrr: LRRClient, db: PostgresDatabaseService, img2vec: Img2VecClient, img2vec_workers: int, 
            nhentai_archivist_dndm: Path=None, lrr_contents_dir: Path=None,
            logger: logging.Logger=None
    ):
        self.lrr = lrr
        self.db = db
        self.img2vec = img2vec
        self.img2vec_semaphore = asyncio.Semaphore(value=img2vec_workers) # when creating embeddings, will reach out to img2vec services.

        self.nhentai_archivist_dndm = nhentai_archivist_dndm
        self.lrr_contents_dir = lrr_contents_dir
        if logger is None:
            logger = LOGGER
        self.logger = logger
        if isinstance(nhentai_archivist_dndm, Path) and not nhentai_archivist_dndm.exists():
            self.logger.warning("DONOTDOWNLOADME path was entered but does not exist.")
        if isinstance(lrr_contents_dir, Path) and not lrr_contents_dir.exists():
            self.logger.warning("LRR contents path was entered but it does not exist.")

    @classmethod
    def from_default(cls) -> "DeduplicationService":
        dotenv.load_dotenv()
        lanraragi = LRRClient(lrr_host=os.getenv("LRR_HOST"), lrr_api_key=os.getenv("LRR_API_KEY"), ssl=os.getenv("LRR_SSL_VERIFY", 'true').lower() == 'true')
        db = PostgresDatabaseService(
            os.getenv("NHDD_DB"), os.getenv("NHDD_DB_USER"), os.getenv("NHDD_DB_HOST"), os.getenv("NHDD_DB_PASS"), DEFAULT_EMBEDDING_DIMENSIONS
        )
        img2vec = Img2VecClient(os.getenv("IMG2VEC_HOST"))
        img2vec_workers = int(os.getenv("IMG2VEC_WORKERS"))
        donotdownloadme_path = os.getenv("NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH")
        if donotdownloadme_path:
            donotdownloadme_path = Path(donotdownloadme_path)
        return DeduplicationService(lanraragi, db, img2vec, img2vec_workers, donotdownloadme_path)
    
    async def close(self):
        if self.lrr.session and not self.lrr.session.closed:
            await self.lrr.session.close()
        await self.db.close()
        await self.lrr.close()
        await self.img2vec.close()

    # >>>>> CREATE EMBEDDING METHODS >>>>>
    async def create_pages_from_arcid(
            self, archive_id: str,
            is_dry_run: bool=False
    ) -> CreatePageResponse:
        pages_from_job: int = None
        pages: int = None
        retry_count = 0
        response = CreatePageResponse()
        response.status = ArchiveEmbeddingJobStatus.SUCCESS

        async def create_embedding_page_no_pair(image: PIL.Image.Image, page_no: int) -> Tuple[List[float], int]:
            if not isinstance(image, PIL.Image.Image):
                raise TypeError(f"Image is not a PIL image: {image}; page no = {page_no}")

            async with self.img2vec_semaphore:
                response = await self.img2vec.create_embedding(image)
                return response.embeddings, page_no
        async def create_embedding_page_no_pairs(image_page_no_pairs: List[Tuple[PIL.Image.Image, int]]) -> List[Tuple[List[float], int]]:
            images = [p[0] for p in image_page_no_pairs]
            async with self.img2vec_semaphore:
                response = await self.img2vec.create_batch_embeddings(images)
            embedding_page_no_pairs = []
            for i in range(len(image_page_no_pairs)):
                to_append = (response.embeddings_list[i], image_page_no_pairs[i][1])
                embedding_page_no_pairs.append(to_append)
            return embedding_page_no_pairs

        async def update_embedding_job(archive_id: str, status_name: str, message: str=None):
            if not is_dry_run:
                await self.db.update_archive_embedding_job(archive_id, status_name, message=message)
        async def insert_pages(page_items):
            if not is_dry_run:
                await self.db.insert_pages(page_items)

        while True:
            try:
                job_info = await self.db.get_archive_embedding_job(archive_id)
                if not job_info:
                    self.logger.warning(f"[{archive_id}] No embedding job found in database; skipping.")
                    response.status = ArchiveEmbeddingJobStatus.NOT_FOUND
                    return response
                pages = await self.db.get_count_pages_by_archive_id(archive_id)
                pages_from_job = get_archive_embedding_job_pages(job_info)
                response.pages = pages_from_job
                if pages == pages_from_job:
                    response.status = ArchiveEmbeddingJobStatus.SKIPPED
                    await update_embedding_job(archive_id, response.status.name)
                    return response
                self.logger.debug(f"[{archive_id}] Downloading archive")
                resp = await self.lrr.download_archive(archive_id)
                if resp.status_code == 401:
                    raise ValueError("An API key is required and not supplied or is invalid.")
                self.logger.debug(f"[{archive_id}] Archive downloaded")
                if pages > 0 and pages != pages_from_job: # job was not complete; redo.
                    await self.db.delete_page_by_archive_id(archive_id)
                    self.logger.debug(f"[{archive_id}] Cleaned embedding response from database.")

                page_items = []
                self.logger.debug(f"[{archive_id}] Extracting pages.")
                image_page_pairs: List[Tuple[PIL.Image.Image, int]] = []
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmpdirp = Path(tmpdir)
                    archive_path = tmpdirp / "extracted.zip"
                    with open(archive_path, 'wb') as writer:
                        writer.write(resp.data.getvalue())
                    extracted_folder = tmpdirp / "images"
                    with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                        zip_ref.extractall(extracted_folder)
                    images = sorted(f for f in extracted_folder.iterdir() if f.suffix.lower() in {".png", ".jpg", "jpeg"})
                    for i, image in enumerate(images):
                        image = PIL.Image.open(image).convert('RGB')
                        page_no = i + 1
                        image_page_pairs.append((image, page_no))
                
                self.logger.debug(f"[{archive_id}] Processing {len(image_page_pairs)} images.")

                page_items = []
                tasks = []
                use_batched = True

                # batching ver.
                if use_batched:
                    img2vec_batch_size = 4
                    for i in range(0, len(image_page_pairs), img2vec_batch_size):
                        batch = image_page_pairs[i:i+img2vec_batch_size]
                        tasks.append(asyncio.create_task(create_embedding_page_no_pairs(batch)))
                    batched_results = await asyncio.gather(*tasks)
                    embedding_page_no_pairs = []
                    for batch_result in batched_results:
                        embedding_page_no_pairs.extend(batch_result)
                    for embedding, page_no in embedding_page_no_pairs:
                        page_items.append((archive_id, page_no, embedding))
                else:
                    for i in range(len(image_page_pairs)):
                        tasks.append(asyncio.create_task(create_embedding_page_no_pair(image_page_pairs[i][0], image_page_pairs[i][1])))
                    results = await asyncio.gather(*tasks)
                    embedding_page_no_pairs = []
                    for embedding, page_no in results:
                        page_items.append((archive_id, page_no, embedding))

                await self.db.insert_pages(page_items)
                self.logger.debug(f"[{archive_id}] Created embeddings for archive.")
                await update_embedding_job(archive_id, response.status.name)
                return response
            except psycopg.OperationalError as operational_error:
                if retry_count < 10:
                    time_to_sleep = 2 ** (retry_count + 1)
                    self.logger.warning(f"[{archive_id}] Encountered database connection error; sleep for {time_to_sleep}s.")
                    await asyncio.sleep(time_to_sleep)
                    retry_count += 1
                    continue
                else:
                    self.logger.error(f"[{archive_id}] Failed to connect to database! Cannot continue.")
                    raise operational_error
            except OSError as os_error:
                self.logger.error(f"[{archive_id}] An error occurred while handling archive.", os_error)
                message = traceback.format_exc()
                response.status = ArchiveEmbeddingJobStatus.FAILED
                await update_embedding_job(archive_id, response.status.name, message=message)
                return response
            except Exception as exception:
                self.logger.error(f"[{archive_id}] Unhandled exception: {exception}")
                raise exception

    async def create_embedding_tasks(self, batch_size: int=1000, max_tasks: int=0):
        """
        Create pending archive embedding tasks out of all archives in the LANraragi server
        and put these tasks to postgres.
        """
        self.logger.info("Fetching archives to create jobs.")
        retry_count = 0
        all_archives: List = []
        while True:
            try:
                all_archives = (await self.lrr.get_all_archives()).data
                break
            except (aiohttp.client_exceptions.ClientConnectionError, aiohttp.client_exceptions.ClientConnectorDNSError) as err:
                if retry_count < 10:
                    time_to_sleep = 2 ** (retry_count + 1)
                    self.logger.warning(f"LANraragi server connection issue ({retry_count+1}/10); retrying in {time_to_sleep}s")
                    await asyncio.sleep(time_to_sleep)
                    retry_count += 1
                    continue
                else:
                    raise err
        # logger.info(f"Obtained {len(all_archives)} archives. Starting embedding task creation in 10s...")
        # await asyncio.sleep(10)
        num_tasks_to_add = len(all_archives) if not max_tasks else min(len(all_archives), max_tasks)
        for i in range(0, num_tasks_to_add, batch_size):
            batch = all_archives[i:i+batch_size]
            batch = [(
                archive.get('arcid'), archive.get('pagecount'), ArchiveEmbeddingJobStatus.PENDING.name, None
            ) for archive in batch]
            while True:
                db_retry_count = 0
                try:
                    await self.db.insert_archive_embedding_jobs(batch)
                    break
                except psycopg.OperationalError as operational_error:
                    if db_retry_count < 10:
                        time_to_sleep = 2 ** (db_retry_count + 1)
                        self.logger.warning(f"Database connection issue ({db_retry_count+1}/10); retrying in {time_to_sleep}s...")
                        await asyncio.sleep(time_to_sleep)
                        db_retry_count += 1
                        continue
                    else:
                        raise operational_error
            self.logger.info(f"[{i}:{i+batch_size}] Pushed task batch.")
        self.logger.info("Completed embedding task creation.")

    async def consume_pending_tasks(
            self, batch_size: int=100_000, max_tasks: int=0,
            max_workers: int=4, download_concurrency: int=4,
            is_dry_run: bool=False
    ):
        """
        Get all archive IDs with pending status, and create embeddings out of every page
        and store them to postgres.
        """
        dl_semaphore = asyncio.Semaphore(value=download_concurrency)

        aej_list = []
        remaining = max_tasks
        while True:
            if max_tasks and not remaining:
                break
            aej_list = await self.db.get_archive_embedding_jobs_by_status(ArchiveEmbeddingJobStatus.PENDING.name, limit=min(remaining, batch_size))
            num_archives = len(aej_list)
            if max_tasks:
                remaining -= num_archives
            if not aej_list:
                break
            async def __consume_embedding_task(archive_id: str, i: int, total_archives: int):
                async with dl_semaphore:
                    response = await self.create_pages_from_arcid(archive_id, is_dry_run=is_dry_run)
                    self.logger.info(f"[{i+1}/{total_archives}][{archive_id}] embedding job status = {response.status.name}; pages = {response.pages}")
            tasks = []
            for i, aej in enumerate(aej_list):
                archive_id = aej[0]
                tasks.append(__consume_embedding_task(archive_id, i, num_archives))
            await asyncio.gather(*tasks)
        self.logger.info("PENDING tasks have been processed.")

    # <<<<< CREATE EMBEDDING METHODS <<<<<

    # >>>>> METADATA METHODS >>>>>
    async def update_nhentai_archives_table(self):
        self.logger.debug("Updating nhentai archives table...")
        semaphore = asyncio.Semaphore(value=8)
        all_archives = (await self.lrr.get_all_archives()).data
        total_archives = len(all_archives)

        async def update_nhentai_archive(archive, progress):
            async with semaphore:
                archive_id = archive.get("arcid")
                tags: str = archive.get("tags")
                if not tags:
                    self.logger.info(f"[{progress}/{total_archives}][{archive_id}] No metadata found in archive.")
                    return
                tags = [tag.strip() for tag in tags.split(",")]
                nhentai_id = _get_source(tags)
                language = get_language(tags)
                await self.db.insert_nhentai_archive(archive_id, nhentai_id, -1, language)
            self.logger.info(f"[{progress}/{total_archives}][{archive_id}] Updated nhentai archive {nhentai_id} (language = {language.name})")

        tasks = []
        for i, archive in enumerate(all_archives):
            tasks.append(asyncio.create_task(update_nhentai_archive(archive, i+1)))
        await asyncio.gather(*tasks)

    async def update_nhentai_favorites(self, redo_failed: bool=False):
        """
        Update favorites count for nhentai_archive table where favorites == -1. Run job in batches
        of 10k.

        This job calls the nhplugin to get metadata and must run synchronously to avoid being rate 
        limited, so it may take a couple days.
        """
        self.logger.info("Creating metadata tasks.")
        while True:
            nhentai_archives = await self.db.get_nhentai_archives_by_favorites(-1, 10_000)
            if not nhentai_archives:
                self.logger.info("No more tasks to create.")
                break

            sem = asyncio.Semaphore(value=16)
            async def _insert_job_as_pending(archive: str):
                async with sem:
                    archive_id, nhentai_id, _, _, _ = archive
                    await self.db.insert_archive_metadata_job(archive_id, MetadataPluginStatus.PENDING)
                    self.logger.info(f"[{archive_id}] Created metadata task.")
            
            tasks = []
            for archive in nhentai_archives:
                tasks.append(asyncio.create_task(_insert_job_as_pending(archive)))
            await asyncio.gather(*tasks)

        self.logger.info("Getting favorites for nhentai archives! Wait patiently.")
        while True:
            statuses_to_fetch = [MetadataPluginStatus.PENDING]
            if redo_failed:
                statuses_to_fetch.append(MetadataPluginStatus.FAILED)
            nhentai_archives = await self.db.get_nhentai_archive_metadata_tasks_by_status(statuses_to_fetch)
            if not nhentai_archives:
                self.logger.info("update nhentai favorites: All done!")
                break
            
            num_archives = len(nhentai_archives)
            for i, archive in enumerate(nhentai_archives):
                progress = i+1
                tts = random.uniform(0, 1)
                await asyncio.sleep(tts)
                archive_id, nhentai_id, _, _, _ = archive
                
                retry_count = 0
                while True:
                    try:
                        resp = await self.lrr.use_plugin("nhplugin", arcid=archive_id, arg=f"nhentai.net/g/{nhentai_id}")
                        if not resp.success:
                            errmessage = resp.error
                            # check error message for hints.
                            if "404" in errmessage or "No matching nHentai Gallery Found" in errmessage:
                                message = f"[{progress}/{num_archives}][{nhentai_id}] Could not find metadata in nhentai! Error: {resp.error}"
                                self.logger.error(message)
                                await self.db.update_archive_metadata_job(archive_id, MetadataPluginStatus.NOT_FOUND, message=message)
                            elif "Try again" in errmessage or "Inactivity timeout" in errmessage:
                                time_to_sleep = 2 ** (retry_count + 1)
                                await asyncio.sleep(time_to_sleep)
                                retry_count += 1
                                continue
                            else:
                                self.logger.error(f"[{progress}/{num_archives}][{nhentai_id}] Failed to get metadata! Error: {resp.error}")
                                await self.db.update_archive_metadata_job(archive_id, MetadataPluginStatus.FAILED, message=f"Failed to get metadata: {resp.error}")
                            break
                        new_tags: str = resp.data.get("new_tags")
                        if not new_tags or not isinstance(new_tags, str):
                            self.logger.warning(f"[{progress}/{num_archives}][{nhentai_id}] New_tags object is None: {resp}")
                            await self.db.update_archive_metadata_job(archive_id, MetadataPluginStatus.FAILED, message=f"new_tags object is None: {resp.error}")
                            break
                        favorites = None
                        for new_tag in [t.strip() for t in new_tags.split(",")]:
                            if new_tag.startswith("nhentai_favorites:"):
                                favorites = int(new_tag.split(":")[1])
                                break
                        if favorites is None:
                            self.logger.error(f"[{progress}/{num_archives}] Favorites count not found for archive {archive_id}.")
                            await self.db.update_archive_metadata_job(archive_id, MetadataPluginStatus.FAILED, message="No favorites count found!")
                            break
                        await self.db.update_nhentai_archive_favorites(archive_id, favorites)
                        await self.db.update_archive_metadata_job(archive_id, MetadataPluginStatus.SUCCESS)
                        self.logger.info(f"[{progress}/{num_archives}] [{nhentai_id}] Updated favorites: {favorites}")
                        break
                    except (aiohttp.client_exceptions.ClientConnectionError, aiohttp.client_exceptions.ClientConnectorDNSError) as exception:
                        if retry_count < 10:
                            time_to_sleep = 2 ** (retry_count + 1)
                            self.logger.error(f"Encountered connection issue with LRR server; retry after {time_to_sleep}s...")
                            await asyncio.sleep(time_to_sleep)
                            retry_count += 1
                            continue
                        else:
                            self.logger.error("Failed to connect to LRR server!")
                            raise exception

    async def load_static_category_archive_ids(self) -> Set[str]:
        """
        Put archives that belong to a static category into a set in memory.
        """
        categorized_arcids = set()
        categories = (await self.lrr.get_all_categories()).data
        for category in categories:
            if not category.get("search"):
                for archive_id in category.get("archives"):
                    categorized_arcids.add(archive_id)
        self.categorized_arcids = categorized_arcids
    # <<<<< METADATA METHODS <<<<<

    # >>>>> SIMILARITY METHODS >>>>>
    async def is_subarchive_of(self, target_arcid: str, source_arcid: str, min_similarity: float=0.95) -> Tuple[bool, bool]:
        """
        Checks if target archive is 1) a subsequence of, and 2) is a *proper* subsequence of source.

        A target archive is a (proper) subarchive of source if:
        - pages(target) is a (proper) subset of pages(source) where equality is replaced with approximate equality by cosine distance,
        - p1 < p2 in target implies ~p1 < ~p2 in source.

        Properties for two archives S, T:
        - if T < S, then S !< T.
        - "<" imposes the structure of disjoint, inverted trees on the set of archives where the max of each tree
        is unique. This unique element corresponds to the archive to keep.
        """
        t_embeddings, s_embeddings = await asyncio.gather(
            asyncio.create_task(self.db.get_embeddings_by_archive_id(target_arcid)),
            asyncio.create_task(self.db.get_embeddings_by_archive_id(source_arcid))
        )
        return is_subsequence(t_embeddings, s_embeddings, min_similarity=min_similarity)

    async def get_keep_reasons(self, archive_id_1: str, archive_id_2: str) -> Dict[str, List[KeepReasonAndScoreEnum]]:
        """
        Return reasons to keep either archive.

        Compare two equal-content archives and return the archive ID judged as duplicate to discard.
        The evaluation will be made by analyzing metadata setting a "keeping score", incrementing it in pwrs of 2
        based on preferential and decisive factors.

        Also this does not necessarily guarantee an order on the set being sorted (i.e. I haven't proven it)
        so circular behavior mayyyy occur but idk I doubt that would happen so I'll fix it when I see it lol
        """
        categorized_arcids = self.categorized_arcids
        archive_1 = await self.lrr.get_archive_metadata(archive_id_1)
        archive_2 = await self.lrr.get_archive_metadata(archive_id_2)
        keep_reasons_1: List[KeepReasonAndScoreEnum] = []
        keep_reasons_2: List[KeepReasonAndScoreEnum] = []

        tags_1 = archive_1.tags
        tags_2 = archive_2.tags
        if not tags_1:
            tags_1 = ""
        if not tags_2:
            tags_2 = ""
        tags_1 = [s.strip() for s in archive_1.tags.split(",")]
        tags_2 = [s.strip() for s in archive_2.tags.split(",")]
        num_tags_1 = len(tags_1)
        num_tags_2 = len(tags_2)
        progress_1 = archive_1.progress
        progress_2 = archive_2.progress
        if not progress_1:
            progress_1 = 0
        if not progress_2:
            progress_2 = 0
        favorites_1, favorites_2 = await asyncio.gather(*[asyncio.create_task(self.db.get_nhentai_archive_favorites(archive_id)) for archive_id in [
            archive_id_1, archive_id_2
        ]])
        favorites_2 = 0
        in_static_category_1 = archive_id_1 in categorized_arcids
        in_static_category_2 = archive_id_2 in categorized_arcids
        has_uncensored_1 = "uncensored" in tags_1
        has_uncensored_2 = "uncensored" in tags_2
        has_no_rough_translation_1 = "rough translation" not in tags_1
        has_no_rough_translation_2 = "rough translation" not in tags_2
        has_no_poor_grammar_1 = "poor grammar" not in tags_1 or "rough grammar" not in tags_1
        has_no_poor_grammar_2 = "poor grammar" not in tags_2 or "rough grammar" not in tags_2
        source_id_1 = _get_source(tags_1)
        source_id_2 = _get_source(tags_2)

        if in_static_category_1:
            keep_reasons_1.append(KeepReasonAndScoreEnum.IS_IN_STATIC_CATEGORY)
        if in_static_category_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.IS_IN_STATIC_CATEGORY)
        if favorites_1 > favorites_2:
            keep_reasons_1.append(KeepReasonAndScoreEnum.HAS_HIGHER_FAVORITE_COUNT)
        elif favorites_1 < favorites_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.HAS_HIGHER_FAVORITE_COUNT)
        if has_uncensored_1:
            keep_reasons_1.append(KeepReasonAndScoreEnum.HAS_DECENSORED_TAG)
        if has_uncensored_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.HAS_DECENSORED_TAG)
        if num_tags_1 > num_tags_2:
            keep_reasons_1.append(KeepReasonAndScoreEnum.HAS_HIGHER_TAG_COUNT)
        elif num_tags_1 < num_tags_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.HAS_HIGHER_TAG_COUNT)
        if source_id_1 > source_id_2:
            keep_reasons_1.append(KeepReasonAndScoreEnum.IS_MORE_RECENT)
        elif source_id_1 < source_id_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.IS_MORE_RECENT)
        if progress_1 > 0:
            keep_reasons_1.append(KeepReasonAndScoreEnum.HAS_READING_PROGRESS)
        if progress_2 > 0:
            keep_reasons_2.append(KeepReasonAndScoreEnum.HAS_READING_PROGRESS)
        if has_no_rough_translation_1:
            keep_reasons_1.append(KeepReasonAndScoreEnum.HAS_NO_ROUGH_TRANSLATION)
        if has_no_rough_translation_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.HAS_NO_ROUGH_TRANSLATION)
        if has_no_poor_grammar_1:
            keep_reasons_1.append(KeepReasonAndScoreEnum.HAS_NO_POOR_GRAMMAR)
        if has_no_poor_grammar_2:
            keep_reasons_2.append(KeepReasonAndScoreEnum.HAS_NO_POOR_GRAMMAR)
        return {
            archive_id_1: keep_reasons_1,
            archive_id_2: keep_reasons_2
        }

    async def compute_subarchives(self, separate_languages: bool=True):
        """
        Go over every archive A for which (A, *) does not exist and calulate its (A, *).
        Incidentally, also calculate all B for which A and B share similar first pages.
        (see "Algorithm for finding subarchives")

        It's best to do this part uninterrupted and if it's interrupted just redo the job ig

        separate_languages: if True, computes subarchives wrt a specific language

        Just a warning, I have NO idea what subarchive behavior is like if you
        run compute_subarchives multiple times. If you want to run this, clear the subarchives
        table and do it from scratch.
        """
        self.logger.debug("Loading static categories...")
        await self.load_static_category_archive_ids()
        self.logger.info("Static categories loaded.")
        async def __compute_subarchives(language: NhArchiveLanguage=None):
            """
            If language is set, will filter subarchive computation to that specific language.
            Otherwise, subarchive computation will be applied to all archives.
            """
            self.logger.debug(f"[{language.name}] Start computing subarchives.")
            while True:
                archive_ids_by_language = await self.db.get_archives_not_in_subarchive_map(language=language)
                num_archives = len(archive_ids_by_language)
                self.logger.debug(f"[{language.name}] Got {num_archives} archives.")
                if not archive_ids_by_language:
                    break

                # no you CAN'T use semamphores for subarchive computation.
                async def _process_archive_id(i, archive_id):
                    self.logger.debug(f"Processing archive {archive_id}...")
                    mapping = await self.db.get_proper_subarchive(archive_id)
                    if mapping: # this archive has already been processed.
                        self.logger.info(f"[{language.name}][{i+1}/{num_archives}][{archive_id}] Already in database.")
                        return
                    _archive_ids = await self.db.get_arcids_by_page_similar_to_first_page_2(archive_id, restrict_language=language is not None)
                    self.logger.debug(f"[{archive_id}] Got archive IDs: {_archive_ids}")

                    curr_max_arcid = archive_id
                    for _archive_id in _archive_ids:
                        _mapping = await self.db.get_proper_subarchive(_archive_id)
                        if _mapping: # set A' = max(A').
                            _archive_id = _mapping[1]
                        (is_subarchive, is_proper_subarchive), (is_suparchive, is_proper_suparchive) = await asyncio.gather(
                            asyncio.create_task(self.is_subarchive_of(curr_max_arcid, _archive_id)),    # A < A'
                            asyncio.create_task(self.is_subarchive_of(_archive_id, curr_max_arcid))     # A' < A
                        )

                        keep_current = False
                        if is_proper_subarchive:
                            pass
                        elif is_proper_suparchive:
                            keep_current = True
                        elif is_subarchive and is_suparchive:
                            keep_reasons_dict = await self.get_keep_reasons(curr_max_arcid, _archive_id)
                            curr_max_score = sum(x.get_score() for x in keep_reasons_dict[curr_max_arcid])
                            _score = sum(x.get_score() for x in keep_reasons_dict[_archive_id])
                            if curr_max_score > _score:
                                keep_current = True
                            elif curr_max_score < _score:
                                pass
                            else: # curr_max_score == _score
                                # do a deterministic tiebreaker.
                                if curr_max_arcid == sorted([curr_max_arcid, _archive_id])[0]:
                                    pass
                                else:
                                    keep_current = True
                        else: # not comparable, do nothing.
                            continue

                        if keep_current: # current archive is max, point all children to it
                            self.logger.debug(f"[{language.name}][{i+1}/{num_archives}][{archive_id}] {curr_max_arcid} > {_archive_id}.")
                            await self.db.insert_subarchive_map(_archive_id, curr_max_arcid)
                            children = await self.db.get_subarchive_map_children_by_archive_id(_archive_id)
                            for c in children:
                                await self.db.insert_subarchive_map(c, curr_max_arcid)
                        else: # current archive is less than new archive; update current max archive
                            self.logger.debug(f"[{language.name}][{i+1}/{num_archives}][{archive_id}] {curr_max_arcid} < {_archive_id}")
                            await self.db.insert_subarchive_map(curr_max_arcid, _archive_id)
                            curr_max_arcid = _archive_id
                    if archive_id == curr_max_arcid:
                        self.logger.info(f"[{language.name}][{i+1}/{num_archives}][{archive_id}] Is unique or preferred duplicate.")
                        await self.db.insert_subarchive_map(archive_id, archive_id) # A = max(A)
                    else:
                        self.logger.info(f"[{language.name}][{i+1}/{num_archives}][{archive_id}] Is not preferred duplicate.")

                for i, archive_id in enumerate(archive_ids_by_language):
                    await _process_archive_id(i, archive_id)
            self.logger.info(f"[{language.name}] Subarchive computations complete.")

        """
        Iterate over all languages. Different langs don't interfere with each other.
        """
        # just do this synchronously for the sake of logging simplicity.
        if separate_languages:
            for language in NhArchiveLanguage:
                await __compute_subarchives(language=language)
        else:
            await __compute_subarchives()

        # compute_archives_by_language_tasks = []
        # for language in NhArchiveLanguage:
        #     compute_archives_by_language_tasks.append(asyncio.create_task(compute_archives_by_language(language)))
        # await asyncio.gather(*compute_archives_by_language_tasks)

    async def get_duplicate_archives(self):
        """
        Get all duplicate archives.
        """
        return await self.db.get_duplicate_archives()
    
    async def remove_duplicate_archives_nhentai_archivist(
            self, lrr_concurrent_connections: int=4, is_dry_run: bool=False
    ) -> NhentaiArchivistDeduplicationResponse:
        """
        Delete all duplicate archives.
        First, update donotdownloadme file. Then remove the files in the contents
        directory by searching for the file with leading nhentai ID to delete.
        """
        dndm_start = time.time()

        # step 1: update donotdownloadme file.
        if not self.nhentai_archivist_dndm.exists():
            raise FileNotFoundError("DONOTDOWNLOADME file not found!")
        duplicate_archive_ids = await self.get_duplicate_archives()
        lrr_sem = asyncio.Semaphore(value=lrr_concurrent_connections)
        async def archive_id_to_nhentai_id(archive_id: str) -> Tuple[str, Union[str, None], Union[str, None]]:
            """
            Returns nhentai ID in right if successful, else error message in left.
            """
            retry_count = 0
            async with lrr_sem:
                while True:
                    try:
                        metadata = await self.lrr.get_archive_metadata(archive_id)
                        if not metadata.success:
                            self.logger.warning(f"[{archive_id}] Error getting metadata: {metadata.error}")
                            return (archive_id, f"Error getting metadata: {metadata.error}", None)
                        tags = metadata.tags
                        if not tags:
                            self.logger.warning(f"[{archive_id}] No tags found!")
                            return (archive_id, "No tags found", None)
                        source = get_source_from_tags(tags)
                        if not source:
                            self.logger.warning(f"[{archive_id}] No source for tag!")
                            return (archive_id, "Tags exist but have no source.")
                        nhentai_id = source.split("/")[-1].strip()
                        if not nhentai_id.isdigit():
                            return (archive_id, f"nHentai ID is not valid digit: {nhentai_id}", None)
                        return (archive_id, None, nhentai_id)
                    except (aiohttp.client_exceptions.ClientConnectionError, aiohttp.client_exceptions.ClientConnectorDNSError) as err:
                        if retry_count < 10:
                            time_to_sleep = 2 ** (retry_count + 1)
                            self.logger.warning(f"LANraragi server connection issue ({retry_count+1}/10); retrying in {time_to_sleep}s")
                            await asyncio.sleep(time_to_sleep)
                            retry_count += 1
                            continue
                        else:
                            raise err

        tasks = []
        for dup_arcid in duplicate_archive_ids:
            tasks.append(asyncio.create_task(archive_id_to_nhentai_id(dup_arcid)))
        results = await asyncio.gather(*tasks)
        with open(self.nhentai_archivist_dndm, 'r') as reader:
            nhentai_ids = reader.readlines()
        new_add_count = 0
        for arcid, err, nhentai_id in results:
            if err:
                ... # do something here?
                continue
            if nhentai_id in nhentai_ids:
                continue
            if nhentai_id:
                nhentai_ids.append(nhentai_id)
                new_add_count += 1
        if not is_dry_run:
            with open(self.nhentai_archivist_dndm, 'w') as writer:
                writer.writelines(nhentai_ids)
        dndm_time = time.time() - dndm_start
        self.logger.info(f"Added {new_add_count} duplicates to DONOTDOWNLOADME file.")

        # step 2: find and remove archives in contents directory.
        response = NhentaiArchivistDeduplicationResponse()
        delete_start = time.time()
        to_delete = {int(nhid) for nhid in nhentai_ids}
        all_archives = discover_all_archives_in_folder(self.lrr_contents_dir)
        contents_size_bytes = 0
        deleted_size_bytes = 0
        deleted_count = 0
        for archive_path in all_archives:
            try:
                name = archive_path.name.strip()
                nhentai_id = int(name.split()[0])
                size_bytes = archive_path.stat().st_size
                contents_size_bytes += size_bytes
                if nhentai_id in to_delete:
                    if not is_dry_run:
                        archive_path.unlink()
                    self.logger.info(f"[{archive_path.name}] Successfully deleted.")
                    deleted_count += 1
                    deleted_size_bytes += size_bytes
            except Exception as exception:
                self.logger.error(f"[{archive_path.name}] Unhandled exception: {exception}")
        delete_time = time.time() - delete_start
        self.logger.info(f"Deduplication successful. Deleted {deleted_count} ({deleted_size_bytes} bytes). DNDM file update time: {dndm_time}s; file delete time: {delete_time}s.")
        response.deleted_duplicates = deleted_count
        response.duplicate_size = deleted_size_bytes
        response.lrr_contents_size = contents_size_bytes
        return response
    # <<<<< SIMILARITY METHODS <<<<<

# <<<<< DEDUPLICATION <<<<<
