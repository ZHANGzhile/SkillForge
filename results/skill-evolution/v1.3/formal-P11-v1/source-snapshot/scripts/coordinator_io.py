"""Bounded retries for Windows sharing contention on coordinator metadata."""
import time

from skillforge.training import atomic_json as write_once


def atomic_json(path, value):
    for attempt in range(6):
        try:
            return write_once(path, value)
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(.05 * (attempt + 1))
