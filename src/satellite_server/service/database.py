

import asyncio
from pathlib import Path
import time
from typing import Iterable, List, Tuple, Union

import aiosqlite
import bcrypt

from satellite_server.models import MetadataPluginTaskStatus


class DatabaseService:

    def __init__(self, db: Path) -> None:
        self.db = db

    async def connect(self):
        if not self.db.parent.exists():
            self.db.parent.mkdir(parents=True, exist_ok=True)
        await self.create_archive_scan_table()
        await self.create_archive_upload_table()
        await self.create_metadata_plugin_task_table()
        await self.create_auth_table()

    async def register_api_key(self, api_key_b: bytes):
        salt = bcrypt.gensalt()
        hash = bcrypt.hashpw(api_key_b, salt)
        last_updated = time.time()
        await self.update_auth(0, salt, hash, last_updated)

    async def verify_api_key(self, api_key_b: bytes) -> bool:
        row = await self.get_auth_by_user_id(0)
        salt = self.get_auth_user_salt(row)
        expected_hash = self.get_auth_user_hash(row)
        actual_hash = bcrypt.hashpw(api_key_b, salt)
        return expected_hash == actual_hash

    @staticmethod
    def get_auth_user_id(auth: Tuple[int, bytes, bytes, float]):
        return auth[0]
    @staticmethod
    def get_auth_user_salt(auth: Tuple[int, bytes, bytes, float]):
        return auth[1]
    @staticmethod
    def get_auth_user_hash(auth: Tuple[int, bytes, bytes, float]):
        return auth[2]
    @staticmethod
    def get_auth_user_last_updated(auth: Tuple[int, bytes, bytes, float]):
        return auth[3]

    async def create_auth_table(self):
        async with aiosqlite.connect(self.db) as conn:
            await conn.execute("""
                               CREATE TABLE IF NOT EXISTS auth (
                               user_id INTEGER PRIMARY KEY,
                               salt BLOB,
                               hash BLOB,
                               last_updated REAL)
""")
            await conn.commit()
        return

    async def update_auth(self, user_id: int, salt: bytes, hash: bytes, last_updated: float):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("""
                                       INSERT OR IGNORE INTO auth
                                       (user_id, salt, hash, last_updated)
                                       VALUES (?, ?, ?, ?)
                                       ON CONFLICT(user_id) DO UPDATE SET
                                       salt = excluded.salt,
                                       hash = excluded.hash,
                                       last_updated = excluded.last_updated
""", (user_id, salt, hash, last_updated))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def get_auth_by_user_id(self, user_id: int) -> Union[Tuple[int, str, str, float], None]:
        async with aiosqlite.connect(self.db) as conn, conn.execute("SELECT user_id, salt, hash, last_updated FROM auth WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

    async def drop_auth_table(self):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DROP TABLE IF EXISTS auth")
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    @staticmethod
    def get_archive_scan_md5(archive_scan: Tuple[str, str, int, float]):
        return archive_scan[0]
    @staticmethod
    def get_archive_scan_path(archive_scan: Tuple[str, str, int, float]):
        return archive_scan[1]
    @staticmethod
    def get_archive_scan_status(archive_scan: Tuple[str, str, int, float]):
        return archive_scan[2]
    @staticmethod
    def get_archive_scan_mtime(archive_scan: Tuple[str, str, int, float]):
        return archive_scan[3]

    async def create_archive_scan_table(self):
        async with aiosqlite.connect(self.db) as conn:
            await conn.execute("""
                               CREATE TABLE IF NOT EXISTS archive_scan (
                               md5      VARCHAR(255)    PRIMARY KEY,
                               path     TEXT,
                               status   INTEGER,
                               mtime    REAL)
""")
            await conn.commit()
        return
    
    async def update_archive_scan(self, md5: str, path: str, status: int, mtime: float):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("""
                                       INSERT OR IGNORE INTO archive_scan
                                       (md5, path, status, mtime)
                                       VALUES (?, ?, ?, ?)
                                       ON CONFLICT(md5) DO UPDATE SET
                                       path     = excluded.path,
                                       status   = excluded.status,
                                       mtime    = excluded.mtime
""", (md5, path, status, mtime))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def get_archive_scan_by_md5(self, md5: str) -> Union[Tuple[str, str, int, float], None]:
        async with aiosqlite.connect(self.db) as conn, conn.execute("SELECT md5, path, status, mtime FROM archive_scan WHERE md5 = ?", (md5,)) as cursor:
            return await cursor.fetchone()
    
    async def get_archive_scans_by_status(self, status: int, limit: int=100_000) -> List[Tuple[str, str, int, float]]:
        if limit:
            async with aiosqlite.connect(self.db) as conn, conn.execute("SELECT md5, path, status, mtime FROM archive_scan WHERE status = ? LIMIT ?", (status, limit)) as cursor:
                return await cursor.fetchall()
        else:
            async with aiosqlite.connect(self.db) as conn, conn.execute("SELECT md5, path, status, mtime FROM archive_scan WHERE status = ?", (status,)) as cursor:
                return await cursor.fetchall()

    async def delete_archive_scan(self, md5: str):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DELETE FROM archive_scan WHERE md5 = ?", (md5,))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def drop_archive_scan_table(self):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DROP TABLE IF EXISTS archive_scan")
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    @staticmethod
    def get_metadata_plugin_task_arcid(metadata_plugin_task: Tuple[str, str, str, int, float, int]):
        return metadata_plugin_task[0]
    @staticmethod
    def get_metadata_plugin_task_source(metadata_plugin_task: Tuple[str, str, str, int, float, int]):
        return metadata_plugin_task[1]
    @staticmethod
    def get_metadata_plugin_task_namespace(metadata_plugin_task: Tuple[str, str, str, int, float, int]):
        return metadata_plugin_task[2]
    @staticmethod
    def get_metadata_plugin_task_status(metadata_plugin_task: Tuple[str, str, str, int, float, int]):
        return metadata_plugin_task[3]
    @staticmethod
    def get_metadata_plugin_task_last_updated(metadata_plugin_task: Tuple[str, str, str, int, float, int]):
        return metadata_plugin_task[4]
    @staticmethod
    def get_metadata_plugin_task_num_failures(metadata_plugin_task: Tuple[str, str, str, int, float, int]):
        return metadata_plugin_task[5]

    async def create_metadata_plugin_task_table(self):
        async with aiosqlite.connect(self.db) as conn:
            await conn.execute("""
                               CREATE TABLE IF NOT EXISTS metadata_plugin_task (
                               arcid VARCHAR(255) PRIMARY KEY,
                               source TEXT,
                               namespace VARCHAR(255),
                               status INTEGER,
                               last_updated REAL,
                               num_failures INTEGER
                               )
""")
            await conn.commit()
        return

    async def update_metadata_plugin_task(self, arcid: str, source: str, namespace: str, status: int, last_updated: float, num_failures: int):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("""
                                       INSERT OR IGNORE INTO metadata_plugin_task
                                       (arcid, source, namespace, status, last_updated, num_failures)
                                       VALUES (?, ?, ?, ?, ?, ?)
                                       ON CONFLICT(arcid) DO UPDATE SET
                                       source = excluded.source,
                                       status = excluded.status,
                                       namespace = excluded.namespace,
                                       last_updated = excluded.last_updated,
                                       num_failures = excluded.num_failures
""", (arcid, source, namespace, status, last_updated, num_failures))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def get_metadata_plugin_task_by_arcid(self, arcid: str) -> Union[Tuple[str, str, str, int, float, int], None]:
        async with aiosqlite.connect(self.db) as conn, conn.execute("SELECT * FROM metadata_plugin_task WHERE arcid = ?", (arcid,)) as cursor:
            return await cursor.fetchone()

    async def get_metadata_plugin_task_by_status_and_namespace(self, status: int, namespace: str, limit: int=100_000) -> Iterable[Tuple[str, str, str, int, float, int]]:
        if limit:
            async with aiosqlite.connect(self.db) as conn, conn.execute("""
                                                                        SELECT arcid, source, namespace, status, last_updated, num_failures 
                                                                        FROM metadata_plugin_task 
                                                                        WHERE status = ? AND namespace = ?
                                                                        LIMIT ?
""", (status, namespace, limit)) as cursor:
                return await cursor.fetchall()
        else:
            async with aiosqlite.connect(self.db) as conn, conn.execute("""
                                                                        SELECT arcid, source, namespace, status, last_updated, num_failures 
                                                                        FROM metadata_plugin_task 
                                                                        WHERE status = ? AND namespace = ?
""", (status, namespace)) as cursor:
                return await cursor.fetchall()
    
    async def get_metadata_plugin_task_expired(self, now: float) -> Iterable[Tuple[str, str, str, int, float, int]]:
        """
        Get all tasks where status is NOT_FOUND and whose do-not-scan dates
        (governed by exp backoff) have expired.
        """
        async with aiosqlite.connect(self.db) as conn, conn.execute("""
                                                                    SELECT arcid, source, namespace, status, last_updated, num_failures
                                                                    FROM metadata_plugin_task
                                                                    WHERE status = ?
                                                                    AND last_updated + 86400 * power(2, num_failures) < ?
""", (MetadataPluginTaskStatus.NOT_FOUND.value, now)) as cursor:
            return await cursor.fetchall()

    async def delete_metadata_plugin_task(self, arcid: str):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DELETE FROM metadata_plugin_task WHERE arcid = ?", (arcid,))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def drop_metadata_plugin_task_table(self):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DROP TABLE IF EXISTS metadata_plugin_task")
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    @staticmethod
    def get_archive_upload_md5(archive_upload: Tuple[str, str, float]):
        return archive_upload[0]
    @staticmethod
    def get_archive_upload_path(archive_upload: Tuple[str, str, float]):
        return archive_upload[1]
    @staticmethod
    def get_archive_upload_mtime(archive_upload: Tuple[str, str, float]):
        return archive_upload[2]

    async def create_archive_upload_table(self):
        async with aiosqlite.connect(self.db) as conn:
            await conn.execute("""
                               CREATE TABLE IF NOT EXISTS archive_upload (
                               md5      VARCHAR(255)    PRIMARY KEY,
                               path     TEXT,
                               mtime    REAL)
""")
            await conn.commit()
        return

    async def update_archive_upload(self, md5: str, path: str, mtime: float):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("""
                                       INSERT OR IGNORE INTO archive_upload
                                       (md5, path, mtime)
                                       VALUES (?, ?, ?)
                                       ON CONFLICT(md5) DO UPDATE SET
                                       path     = excluded.path,
                                       mtime    = excluded.mtime
""", (md5, path, mtime))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def get_archive_upload_by_md5(self, md5: str) -> Union[Tuple[str, str, float], None]:
        async with aiosqlite.connect(self.db) as conn, conn.execute("SELECT md5, path, mtime FROM archive_upload WHERE md5 = ?", (md5,)) as cursor:
            return await cursor.fetchone()
    
    async def delete_archive_upload(self, md5: str):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DELETE FROM archive_upload WHERE md5 = ?", (md5,))
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue

    async def drop_archive_upload_table(self):
        retry_count = 0
        while True:
            try:
                async with aiosqlite.connect(self.db) as conn:
                    await conn.execute("DROP TABLE IF EXISTS archive_upload")
                    await conn.commit()
                    return
            except aiosqlite.OperationalError:
                # this may happen if database is locked; in this case, 
                # simply wait and try again.
                time_to_sleep = 2 ** (retry_count + 1)
                await asyncio.sleep(time_to_sleep)
                continue
