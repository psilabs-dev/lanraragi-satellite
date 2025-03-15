import asyncio
from typing import Annotated, TypeAlias
from aiorwlock import RWLock
from fastapi import Depends


class LockState:
    """
    Allow concurrent reader, only one writer.
    """
    RWLOCK = RWLock()

    # nhdd locks.
    nhentai_archives_data_lock = asyncio.Lock()
    create_page_embeddings_lock = asyncio.Lock()
    compute_subarchives_lock = asyncio.Lock()
    contents_lock = asyncio.Lock()

lock_state = LockState()
def get_lock_state():
    return lock_state
LockStateT: TypeAlias = Annotated[LockState, Depends(get_lock_state)]
