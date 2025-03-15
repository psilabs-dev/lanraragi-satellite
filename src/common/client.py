from contextlib import AbstractAsyncContextManager
from typing import Union, override

import aiohttp


class AbstractAsyncHTTPContextClient(AbstractAsyncContextManager):
    """
    Abstract base class for an asynchronous HTTP client with a context manager.

    Allows the use of passing custom sessions, and running `async with Client()` context.
    """

    def __init__(self, session: Union[None, aiohttp.ClientSession], ssl: bool=True):
        self.session = session
        self.ssl = ssl
        self._created_session = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None:
            if not self.ssl:
                self.session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
            else:
                self.session = aiohttp.ClientSession()
            self._created_session = True
        return self.session

    async def close(self):
        if self.session is not None and self._created_session:
            await self.session.close()
            self.session = None
            self._created_session = False
    
    @override
    async def __aenter__(self):
        await self._get_session()
        return self
    
    @override
    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()
        return None

    # async def __aexit__(self, exc_type, exc_val, exc_tb):
    #     await self.close()
