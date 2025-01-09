from aiorwlock import RWLock


class LockState:
    """
    Allow concurrent reader, only one writer.
    """
    RWLOCK = RWLock()

lock_state = LockState()
def get_lock_state():
    return lock_state
