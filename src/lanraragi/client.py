import base64
import io
import aiohttp
import aiohttp.client_exceptions
import logging
from pathlib import Path
from typing import overload, Union

from common.client import AbstractAsyncHTTPContextClient
from lanraragi.models import LanraragiArchiveDownloadResponse, LanraragiArchiveMetadataResponse, LanraragiResponse, LanraragiServerInfoResponse

logger = logging.getLogger(__name__)

def build_auth_header(lrr_api_key: str) -> str:
    bearer = base64.b64encode(lrr_api_key.encode(encoding='utf-8')).decode('utf-8')
    return f"Bearer {bearer}"

class LRRClient(AbstractAsyncHTTPContextClient):
    """
    An asynchronous HTTP client for making API calls to a LANraragi server.

    API documentation: https://sugoi.gitbook.io/lanraragi/api-documentation/getting-started

    Throws
    ------ 
    aiohttp.ClientConnectionError
    """

    def __init__(
            self,
            lrr_host: str=None,
            lrr_api_key: str=None,
            session: Union[None, aiohttp.ClientSession]=None,
            ssl: bool=True
    ):
        if not lrr_host:
            raise KeyError("No host found for LANraragi!")
        if not lrr_host.startswith("https://") and not lrr_host.startswith("http://"):
            raise ValueError(f"lrr_host {lrr_host} must specify HTTP protocol.")
        if not lrr_api_key:
            raise KeyError("No API key found for LANraragi!")
        lrr_headers = {}
        if lrr_api_key:
            lrr_headers["Authorization"] = build_auth_header(lrr_api_key)

        self.lrr_host = lrr_host
        self.headers = lrr_headers
        super().__init__(session, ssl=ssl)

    @classmethod
    async def default_client(cls, session: Union[None, aiohttp.ClientSession]=None) -> "LRRClient":
        """
        Return the default LANraragi client by trying out local and global configuration targets.
        """
        import os
        lrr_host = os.getenv("LRR_HOST", "http://localhost:3000")
        lrr_api_key = os.getenv("LRR_API_KEY", "lanraragi")
        return LRRClient(lrr_host=lrr_host, lrr_api_key=lrr_api_key, session=session)

    def build_url(self, api) -> str:
        """
        Builds the LANraragi server URL.

        Examples:
        - `client.build_url("/api/search")`
        - `client.build_url("/api/archives")`
        """
        return f"{self.lrr_host}{api}"

    # ---- START SEARCH API ----
    # https://sugoi.gitbook.io/lanraragi/api-documentation/search-api
    async def search_archive_index(self, category: str=None, search_filter: str=None, start: str=None, sortby: str=None, order: str=None) -> LanraragiResponse:
        """
        `GET /api/search`
        """
        url = self.build_url("/api/search")
        response = LanraragiResponse()
        form_data = aiohttp.FormData(quote_fields=False)
        for key, value in [
            ("category", category),
            ("filter", search_filter),
            ("start", start),
            ("sortby", sortby),
            ("order", order)
        ]:
            if value:
                form_data.add_field(key, value)

        async with (await self._get_session()).get(url=url, data=form_data, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                response_j = await async_response.json()
                response.data = response_j.get("data")
                response.draw = response_j.get("draw")
                response.records_filtered = response_j.get("recordsFiltered")
                response.records_total = response_j.get("recordsTotal")
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[search] Failed to decode JSON response: ", content_type_error)
            return response

    async def search_random_archives(self, category: str=None, search_filter: str=None, count: int=None):
        """
        `GET /api/search/random`
        """
        url = self.build_url("/api/search/random")
        response = LanraragiResponse()
        form_data = aiohttp.FormData(quote_fields=False)
        for key, value in [
            ("category", category),
            ("filter", search_filter),
            ("count", count)
        ]:
            if value:
                form_data.add_field(key, value)
        async with (await self._get_session()).get(url=url, data=form_data, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                response.data = (await async_response.json()).get("data")
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[search] Failed to decode JSON response: ", content_type_error)
            return response

    async def discard_search_cache(self) -> LanraragiResponse:
        """
        `DELETE /api/search/cache`
        """
        url = self.build_url("/api/search/cache")
        response = LanraragiResponse()
        async with (await self._get_session()).delete(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[clear_cache] Failed to decode JSON response: ", content_type_error)
            return response

    # ---- END SEARCH API ----

    # ---- START ARCHIVE API ----
    # https://sugoi.gitbook.io/lanraragi/api-documentation/archive-api
    async def get_all_archives(self) -> LanraragiResponse:
        """
        `GET /api/archives`
        """
        url = self.build_url("/api/archives")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            response.data = await async_response.json()
            return response

    async def get_untagged_archives(self) -> LanraragiResponse:
        """
        `GET /api/archives/untagged`
        """
        url = self.build_url("/api/archives/untagged")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            response.data = await async_response.json()
            return response

    async def get_archive_metadata(self, archive_id: str) -> LanraragiArchiveMetadataResponse:
        """
        `GET /api/archives/:id/metadata`
        """
        url = self.build_url(f"/api/archives/{archive_id}/metadata")
        response = LanraragiArchiveMetadataResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_archive_metadata] Failed to decode JSON response: ", content_type_error)
            return response

    async def download_archive(self, archive_id: str) -> LanraragiArchiveDownloadResponse:
        """
        `GET /api/archives/:id/download`

        Example:
        ```
        client = LRRClient()
        data = await client.download_archive(arcid)
        with open("archive.cbz", 'wb') as writer:
            writer.write(data.getvalue())
        ```
        """
        url = self.build_url(f"/api/archives/{archive_id}/download")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            buffer = io.BytesIO()
            if response.success:
                while True:
                    chunk = await async_response.content.read(1024)
                    if not chunk:
                        break
                    buffer.write(chunk)
                buffer.seek(0)
                response.data = buffer
            else:
                try:
                    data = await async_response.json()
                    for key in data:
                        response.__setattr__(key, data[key])
                except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                    logger.error("[download_archive] Failed to decode JSON response: ", content_type_error)
            return response

    @overload
    async def upload_archive(
        self, archive_path: str, archive_filename: str, archive_checksum: str=None, 
        title: str=None, tags: str=None, summary: str=None, category_id: str=None
    ) -> LanraragiResponse:
        ...
    
    @overload
    async def upload_archive(
        self, archive_path: Path, archive_filename: str, archive_checksum: str=None, 
        title: str=None, tags: str=None, summary: str=None, category_id: str=None
    ) -> LanraragiResponse:
        ...

    @overload
    async def upload_archive(
        self, archive_io: io.IOBase, archive_filename: str, archive_checksum: str=None, 
        title: str=None, tags: str=None, summary: str=None, category_id: str=None
    ) -> LanraragiResponse:
        ...

    async def upload_archive(
            self, archive: Union[Path, str, io.IOBase], archive_filename: str, archive_checksum: str=None,
            title: str=None, tags: str=None, summary: str=None, category_id: str=None,
    ) -> LanraragiResponse:
        """
        `PUT /api/archives/upload`
        """
        if isinstance(archive, (Path, str)):
            with open(archive, 'rb') as archive_br:
                return await self.upload_archive(
                    archive_br, archive_filename, archive_checksum=archive_checksum, 
                    title=title, tags=tags, summary=summary, category_id=category_id
                )
        elif isinstance(archive, io.IOBase):
            url = self.build_url("/api/archives/upload")
            response = LanraragiResponse()
            form_data = aiohttp.FormData(quote_fields=False)
            form_data.add_field('file', archive, filename=archive_filename, content_type='application/octet-stream')
            if archive_checksum:
                form_data.add_field("file_checksum", archive_checksum)
            if title:
                form_data.add_field('title', title)
            if tags:
                form_data.add_field('tags', tags)
            if summary:
                form_data.add_field('summary', summary)
            if category_id:
                form_data.add_field('category_id', category_id)
            async with (await self._get_session()).put(url=url, data=form_data, headers=self.headers) as async_response:
                response.status_code = async_response.status
                response.success = 1 if async_response.status == 200 else 0
                try:
                    data = await async_response.json()
                    for key in data:
                        response.__setattr__(key, data[key])
                except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                    logger.error("[upload_archive] Failed to decode JSON response: ", content_type_error)
                    response.error = async_response.text
                return response
        else:
            raise TypeError(f"Unsupported upload content type (must be Path, str or IOBase): {type(archive)}")

    async def update_archive(self, archive_id: str, title: str=None, tags: str=None, summary: str=None):
        """
        `PUT /api/archives/:id/metadata`
        """
        if isinstance(tags, str):
            url = self.build_url(f"/api/archives/{archive_id}/metadata")
            response = LanraragiResponse()
            form_data = aiohttp.FormData(quote_fields=False)
            if title:
                form_data.add_field('title', title)
            if tags:
                form_data.add_field('tags', tags)
            if summary:
                form_data.add_field('summary', summary)
            async with (await self._get_session()).put(url=url, headers=self.headers, data=form_data) as async_response:
                response.status_code = async_response.status
                response.success = 1 if async_response.status == 200 else 0
                try:
                    data = await async_response.json()
                    for key in data:
                        response.__setattr__(key, data[key])
                except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                    logger.error("[update_archive] Failed to update Archive: ", content_type_error)
                    response.error = async_response.text
                return response
        else:
            raise TypeError(f"Unsupported type for tags: {type(tags)}")

    async def delete_archive(self, archive_id: str) -> LanraragiResponse:
        """
        `DELETE /api/archives/:id`
        """
        url = self.build_url(f"/api/archives/{archive_id}")
        response = LanraragiResponse()
        async with (await self._get_session()).delete(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[delete_archive] Failed to decode JSON response: ", content_type_error)
            return response

    # ---- END ARCHIVE API ----

    # ---- START DATABASE API ----
    async def get_database_stats(self, minweight: int=1) -> LanraragiResponse:
        """
        `GET /api/database/stats`
        """
        url = self.build_url("/api/database/stats")
        response = LanraragiResponse()
        form_data = aiohttp.FormData(quote_fields=False)
        form_data.add_field('minweight', minweight)
        async with (await self._get_session()).get(url=url, data=form_data, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                response.data = await async_response.json()
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_database_stats] Failed to get database stats: ", content_type_error)
            return response

    async def clean_database(self) -> LanraragiResponse:
        """
        `POST /api/database/clean`
        """
        url = self.build_url("/api/database/clean")
        response = LanraragiResponse()
        async with (await self._get_session()).post(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[clean_database] Failed to clean database: ", content_type_error)
            return response

    async def drop_database(self) -> LanraragiResponse:
        """
        `POST /api/database/drop`
        """
        url = self.build_url("/api/database/drop")
        response = LanraragiResponse()
        async with (await self._get_session()).post(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[drop_database] Failed to drop database: ", content_type_error)
            return response

    async def get_backup(self) -> LanraragiResponse:
        """
        `GET /api/database/backup`
        """
        url = self.build_url("/api/database/backup")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            response.data = await async_response.json()
            return response

    async def clear_new_all(self) -> LanraragiResponse:
        """
        `DELETE /api/database/isnew`
        """
        url = self.build_url("/api/database/isnew")
        response = LanraragiResponse()
        async with (await self._get_session()).delete(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[clear_new_all] Failed to clear new flag on Archives: ", content_type_error)
            return response

    # ---- END DATABASE API ----

    # ---- START CATEGORY API ----
    # https://sugoi.gitbook.io/lanraragi/api-documentation/category-api
    async def get_all_categories(self) -> LanraragiResponse:
        """
        `GET /api/categories`
        """
        url = self.build_url("/api/categories")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                response.data = await async_response.json()
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_categories] Failed to decode JSON response: ", content_type_error)
            return response

    async def get_category(self, category_id: str) -> LanraragiResponse:
        """
        `GET /api/categories/:id`
        """
        url = self.build_url(f"/api/categories/{category_id}")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                response.data = await async_response.json()
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_category] Failed to decode JSON response: ", content_type_error)
            return response

    async def create_category(self, name: str, search: str=None, pinned: bool=None):
        """
        `PUT /api/categories`
        """
        url = self.build_url("/api/categories")
        response = LanraragiResponse()
        form_data = aiohttp.FormData(quote_fields=False)
        form_data.add_field('name', name)
        if search:
            form_data.add_field('search', search)
        if pinned:
            form_data.add_field('pinned', pinned)
        async with (await self._get_session()).put(url=url, data=form_data, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[create_category] Failed to decode JSON response: ", content_type_error)
            return response

    async def update_category(self, category_id: str, name: str=None, search: str=None, pinned: bool=None):
        """
        `PUT /api/categories/:id`
        """
        url = self.build_url(f"/api/categories/{category_id}")
        response = LanraragiResponse()
        form_data = aiohttp.FormData(quote_fields=False)
        if name:
            form_data.add_field('name', name)
        if search:
            form_data.add_field('search', search)
        if pinned:
            form_data.add_field('pinned', pinned)
        async with (await self._get_session()).put(url=url, data=form_data, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[update_category] Failed to decode JSON response: ", content_type_error)
            return response

    async def delete_category(self, category_id: str):
        """
        `DELETE /api/categories/:id`
        """
        url = self.build_url(f"/api/categories/{category_id}")
        response = LanraragiResponse()
        async with (await self._get_session()).delete(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[delete_category] Failed to decode JSON response: ", content_type_error)
            return response
        
    async def add_archive_to_category(self, category_id: str, archive_id: str) -> LanraragiResponse:
        """
        `PUT /api/categories/:id/:archive`
        """
        url = self.build_url(f"/api/categories/{category_id}/{archive_id}")
        response = LanraragiResponse()
        async with (await self._get_session()).put(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[add_archive_to_category] Failed to decode JSON response: ", content_type_error)
            return response

    async def get_bookmark_link(self) -> LanraragiResponse:
        """
        `GET /api/categories/bookmark_link`
        """
        url = self.build_url("/api/categories/bookmark_link")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_bookmark_link] Failed to decode JSON response: ", content_type_error)
            return response

    async def update_bookmark_link(self, category_id: str) -> LanraragiResponse:
        """
        `PUT /api/categories/bookmark_link/:id`
        """
        url = self.build_url(f"/api/categories/bookmark_link/{category_id}")
        response = LanraragiResponse()
        async with (await self._get_session()).put(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[update_bookmark_link] Failed to decode JSON response: ", content_type_error)
            return response

    async def remove_bookmark_link(self):
        """
        `DELETE /api/categories/bookmark_link`
        """
        url = self.build_url("/api/categories/bookmark_link")
        response = LanraragiResponse()
        async with (await self._get_session()).delete(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[remove_bookmark_link] Failed to decode JSON response: ", content_type_error)
            return response

    # ---- END CATEGORY API ----

    # ---- START SHINOBU API ----
    # https://sugoi.gitbook.io/lanraragi/api-documentation/shinobu-api
    async def get_shinobu_status(self) -> LanraragiResponse:
        """
        `GET /api/shinobu`
        """
        url = self.build_url("/api/shinobu")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_shinobu_status] Failed to decode JSON response: ", content_type_error)
            return response

    async def stop_shinobu(self) -> LanraragiResponse:
        """
        `POST /api/shinobu/stop`
        """
        url = self.build_url("/api/shinobu/stop")
        response = LanraragiResponse()
        async with (await self._get_session()).post(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[shinobu_stop] Failed to stop shinobu: ", content_type_error)
            return response

    async def restart_shinobu(self) -> LanraragiResponse:
        """
        `POST /api/shinobu/restart`
        """
        url = self.build_url("/api/shinobu/restart")
        response = LanraragiResponse()
        async with (await self._get_session()).post(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[shinobu_restart] Failed to restart shinobu: ", content_type_error)
            return response

    # ---- END SHINOBU API ----

    # ---- START MISC API ----
    # https://sugoi.gitbook.io/lanraragi/api-documentation/miscellaneous-other-api
    async def get_server_info(self) -> LanraragiServerInfoResponse:
        """
        `GET /api/info`
        """
        url = self.build_url("/api/info")
        response = LanraragiServerInfoResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_server_info] Failed to decode JSON response: ", content_type_error)
            return response

    async def get_available_plugins(self, plugin_type: str) -> LanraragiResponse:
        """
        `GET /api/plugins/:type`
        """
        url = self.build_url(f"/api/plugins/{plugin_type}")
        response = LanraragiResponse()
        async with (await self._get_session()).get(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                response.data = await async_response.json()
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[get_available_plugins] Failed to decode JSON response: ", content_type_error)
            return response

    async def use_plugin(self, plugin: str, arcid: str=None, arg: str=None):
        """
        `POST /api/plugins/use`
        """
        url = self.build_url("/api/plugins/use")
        query = f"?plugin={plugin}"
        if arcid:
            query += f"&id={arcid}"
        if arg:
            query += f"&arg={arg}"
        url = url + query

        response = LanraragiResponse()
        async with (await self._get_session()).post(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            try:
                response_obj = await async_response.json()
                response.data = response_obj.get("data")
                response.success = response_obj.get("success")
                response.operation = "use_plugin"
                response.error = response_obj.get("error")
                response.type = response_obj.get("type")
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[use_plugin] Failed to decode JSON response: ", content_type_error)
            return response

    async def clean_tempfolder(self):
        """
        `DELETE /api/tempfolder`
        """
        url = self.build_url("/api/tempfolder")
        response = LanraragiResponse()
        async with (await self._get_session()).delete(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[cleantemp] Failed to decode JSON response: ", content_type_error)
            return response

    async def regenerate_thumbnails(self):
        """
        `POST /api/regen_thumbs`
        """
        url = self.build_url("/api/regen_thumbs")
        response = LanraragiResponse()
        async with (await self._get_session()).post(url=url, headers=self.headers) as async_response:
            response.status_code = async_response.status
            response.success = 1 if async_response.status == 200 else 0
            try:
                data = await async_response.json()
                for key in data:
                    response.__setattr__(key, data[key])
            except aiohttp.client_exceptions.ContentTypeError as content_type_error:
                logger.error("[cleantemp] Failed to decode JSON response: ", content_type_error)
            return response

    # ---- END MISC API ----
