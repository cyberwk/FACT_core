from contextlib import contextmanager
from typing import Callable


@contextmanager
def mock_patch(o: object, method: str, replacement_method: Callable):
    if not hasattr(o, method):
        raise AttributeError('{} has no method {}'.format(type(o), method))
    tmp = getattr(o, method)
    try:
        setattr(o, method, replacement_method)
        yield o
    finally:
        setattr(o, method, tmp)
