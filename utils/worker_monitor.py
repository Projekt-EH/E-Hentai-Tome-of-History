"""Minimal worker output tagging and end-of-task memory reporting."""

import os
import ctypes
import gc
import sys
import threading
from contextlib import contextmanager
from functools import wraps

import psutil


def _load_malloc_trim():
    if sys.platform != "linux":
        return None
    try:
        trim = ctypes.CDLL(None).malloc_trim
    except (OSError, AttributeError):
        return None
    trim.argtypes = [ctypes.c_size_t]
    trim.restype = ctypes.c_int
    return trim


_malloc_trim = _load_malloc_trim()


def _load_windows_trim():
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        get_process = kernel32.GetCurrentProcess
        get_process.argtypes = []
        get_process.restype = wintypes.HANDLE
        empty_working_set = psapi.EmptyWorkingSet
        empty_working_set.argtypes = [wintypes.HANDLE]
        empty_working_set.restype = wintypes.BOOL
    except (OSError, AttributeError):
        return None

    def trim():
        if not empty_working_set(get_process()):
            error = ctypes.get_last_error()
            print(f"Memory trim unavailable: Windows error {error}")

    return trim


_windows_trim = _load_windows_trim()


def release_unused_memory():
    """Collect unreachable objects and return free allocator pages where supported."""
    gc.collect()
    if _malloc_trim is not None:
        _malloc_trim(0)
    elif _windows_trim is not None:
        _windows_trim()


class _WorkerOutput:
    def __init__(self, stream):
        self.stream = stream
        self.local = threading.local()
        self.lock = threading.RLock()

    def write(self, text):
        if not getattr(self.local, "worker", False):
            with self.lock:
                return self.stream.write(text)
        with self.lock:
            pending = getattr(self.local, "pending", "") + text
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                prefix = f"[{os.getpid()}] " if line.strip() else ""
                self.stream.write(prefix + line + "\n")
            self.local.pending = pending
        return len(text)

    def flush(self):
        with self.lock:
            self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


@contextmanager
def worker_output():
    """Install one shared router before starting workers, restore after they join."""
    original = sys.stdout
    sys.stdout = _WorkerOutput(original)
    try:
        yield
    finally:
        sys.stdout = original


def worker(function):
    @wraps(function)
    def tagged(*args, **kwargs):
        stream = sys.stdout
        if not isinstance(stream, _WorkerOutput):
            return function(*args, **kwargs)
        previous = getattr(stream.local, "worker", False)
        stream.local.worker = True
        try:
            return function(*args, **kwargs)
        finally:
            pending = getattr(stream.local, "pending", "")
            if pending:
                with stream.lock:
                    stream.stream.write(f"[{os.getpid()}] {pending}\n")
                stream.local.pending = ""
            stream.local.worker = previous
    return tagged


def report_memory():
    try:
        rss = psutil.Process().memory_info().rss / 1048576
    except psutil.Error as exc:
        print(f"Memory usage unavailable: {exc}")
    else:
        print(f"Memory usage (RSS): {rss:.1f} MiB")
