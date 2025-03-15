import dotenv
import os
from pathlib import Path

class SatelliteConfig:
    """
    Configuration singleton for the satellite server.
    """

    def __init__(self):
        dotenv.load_dotenv()

        _SATELLITE_HOME = os.getenv("SATELLITE_HOME")
        if not _SATELLITE_HOME:
            SATELLITE_HOME = Path.home() / ".satellite"
        else:
            SATELLITE_HOME = Path(_SATELLITE_HOME)
        self.SATELLITE_HOME = SATELLITE_HOME
        self.SATELLITE_DB_PATH = self.SATELLITE_HOME / "db" / "db.sqlite"
        self.SATELLITE_API_KEY = os.getenv("SATELLITE_API_KEY")
        self.SATELLITE_DISABLE_API_KEY = os.getenv("SATELLITE_DISABLE_API_KEY", "false").lower() == "true"

        self.SATELLITE_GIT_COMMIT_HASH = os.getenv("SATELLITE_GIT_COMMIT_HASH")
        self.LRR_HOST = os.getenv("LRR_HOST", "http://localhost:3000")
        self.LRR_API_KEY = os.getenv("LRR_API_KEY", "lanraragi")
        self.LRR_SSL_VERIFY = os.getenv("LRR_SSL_VERIFY", "true").lower() == "true"
        if _LRR_CONTENTS_DIR := os.getenv("LRR_CONTENTS_DIR"):
            self.LRR_CONTENTS_DIR = Path(_LRR_CONTENTS_DIR)
        else:
            self.LRR_CONTENTS_DIR = None
        if _METADATA_NHENTAI_ARCHIVIST_DB := os.getenv("METADATA_NHENTAI_ARCHIVIST_DB"):
            self.METADATA_NHENTAI_ARCHIVIST_DB = Path(_METADATA_NHENTAI_ARCHIVIST_DB)
        else:
            self.METADATA_NHENTAI_ARCHIVIST_DB = None
        if _NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH := os.getenv("NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH"):
            self.NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH = Path(_NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH)
        else:
            self.NHENTAI_ARCHIVIST_DONOTDOWNLOADME_PATH = None
        if _METADATA_PIXIVUTIL2_DB := os.getenv("METADATA_PIXIVUTIL2_DB"):
            self.METADATA_PIXIVUTIL2_DB = Path(_METADATA_PIXIVUTIL2_DB)
        else:
            self.METADATA_PIXIVUTIL2_DB = None
        self.UPLOAD_DIR = os.getenv("UPLOAD_DIR")

        self.NHDD_DB = os.getenv("NHDD_DB", "postgres")
        self.NHDD_DB_HOST = os.getenv("NHDD_DB_HOST", "localhost")
        self.NHDD_DB_USER = os.getenv("NHDD_DB_USER", "postgres")
        self.NHDD_DB_PASS = os.getenv("NHDD_DB_PASS")
        self.IMG2VEC_HOST = os.getenv("IMG2VEC_HOST")

        # this should be proportional to the amount of img2vec services running in the backend.
        self.IMG2VEC_WORKERS = int(os.getenv("IMG2VEC_WORKERS", 1))

    def get_is_nhdd_configured(self) -> bool:
        return all(x is not None for x in [self.NHDD_DB, self.NHDD_DB_HOST, self.NHDD_DB_USER, self.NHDD_DB_PASS, self.IMG2VEC_HOST])
