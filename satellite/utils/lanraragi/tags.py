

from typing import Union


def get_source_from_tags(tags: str) -> Union[str, None]:
    """
    Return the source from tags if exists, else None.
    """
    tags = tags.split(',')
    for tag in tags:
        if tag.startswith("source:"):
            return tag[7:]
    return None
