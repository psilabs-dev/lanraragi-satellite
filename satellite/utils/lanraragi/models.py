import io


class LanraragiResponse:
    
    success: int
    status_code: int
    message: str
    error: str
    data: object
    operation: str

    def __repr__(self) -> str:
        return str(self.__dict__)

class LanraragiArchiveMetadataResponse(LanraragiResponse):

    filename: str
    title: str
    tags: str
    summary: str

class LanraragiArchiveDownloadResponse(LanraragiResponse):

    data: io.BytesIO

class LanraragiServerInfoResponse(LanraragiResponse):

    archives_per_page: int
    cache_last_cleared: int
    debug_mode: bool
    has_password: bool
    motd: str
    name: str
    nofun_mode: bool
    server_resizes_images: bool
    server_tracks_progress: bool
    total_archives: int
    total_pages_read: int
    version: str
    version_desc: str
    version_name: str
