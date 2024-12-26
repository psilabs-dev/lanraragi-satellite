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
