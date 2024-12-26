def get_version() -> str:
    import importlib.metadata
    return importlib.metadata.version("satellite")
