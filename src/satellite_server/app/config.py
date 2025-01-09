

import os
from pathlib import Path


class SatelliteConfig:
    """
    Configuration singleton for the satellite server.
    """

    SATELLITE_API_KEY: str
    SATELLITE_HOME: Path
    SATELLITE_DB_PATH: Path
    SATELLITE_GIT_COMMIT_HASH: str

    LRR_HOST: str
    LRR_API_KEY: str

    # contents directory processing-related configuration
    LRR_CONTENTS_DIR: Path

    # metadata-related configuration
    METADATA_NHENTAI_ARCHIVIST_DB: Path
    METADATA_PIXIVUTIL2_DB: Path

    # upload-related configuration
    UPLOAD_DIR: Path

    def load_configs(self):
        """
        Load configuration for satellite based on environment variables.
        """
        _SATELLITE_HOME = os.getenv("SATELLITE_HOME")
        if not _SATELLITE_HOME:
            SATELLITE_HOME = Path.home() / ".satellite"
        else:
            SATELLITE_HOME = Path(_SATELLITE_HOME)
        self.SATELLITE_HOME = SATELLITE_HOME
        self.SATELLITE_DB_PATH = self.SATELLITE_HOME / "db" / "db.sqlite"
        self.SATELLITE_API_KEY = os.getenv("SATELLITE_API_KEY")
        self.SATELLITE_GIT_COMMIT_HASH = os.getenv("SATELLITE_GIT_COMMIT_HASH")
        self.LRR_HOST = os.getenv("LRR_HOST", "http://localhost:3000")
        self.LRR_API_KEY = os.getenv("LRR_API_KEY")
        if _LRR_CONTENTS_DIR := os.getenv("LRR_CONTENTS_DIR"):
            self.LRR_CONTENTS_DIR = Path(_LRR_CONTENTS_DIR)
        if _METADATA_NHENTAI_ARCHIVIST_DB := os.getenv("METADATA_NHENTAI_ARCHIVIST_DB"):
            self.METADATA_NHENTAI_ARCHIVIST_DB = Path(_METADATA_NHENTAI_ARCHIVIST_DB)
        if _METADATA_PIXIVUTIL2_DB := os.getenv("METADATA_PIXIVUTIL2_DB"):
            self.METADATA_PIXIVUTIL2_DB = Path(_METADATA_PIXIVUTIL2_DB)
        self.UPLOAD_DIR = os.getenv("UPLOAD_DIR")

satellite_config = SatelliteConfig()
satellite_config.load_configs()