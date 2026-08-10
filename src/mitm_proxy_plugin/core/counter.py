"""
This module provides a function to atomically increment a counter stored in a file. 
It uses file locking to ensure that concurrent access to the counter is handled safely, 
preventing race conditions and ensuring that the counter value is updated correctly.
"""
import fcntl
import os
import threading
from pathlib import Path

_local_lock = threading.Lock()


def atomic_increment(counter_path: Path, lock_path: Path) -> int:
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with _local_lock:
        lock_path.touch(exist_ok=True)

        with lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    current = int(counter_path.read_text().strip() or "0")
                except FileNotFoundError:
                    current = 0

                current += 1

                tmp_path = counter_path.with_name(counter_path.name + ".tmp")
                tmp_path.write_text(str(current))
                os.replace(tmp_path, counter_path)

                return current
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)