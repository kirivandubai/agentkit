"""Files reached through directory descriptors, never through a link, and files written whole or not at all.

For folders that someone else writes too — a sandbox's /work/out, a keeper's draft, dev's box — a check by name and an
open by name are two moments, and a folder swapped for a link between them would lead the open elsewhere. So every
folder on the way is opened by itself, relative to its parent, with O_NOFOLLOW, and the check and the read are the same
descriptor. A leaf is opened with O_NONBLOCK as well, so a FIFO planted in place of a file cannot hang the open; fstat
then refuses it.

Errors stay OSError (a missing folder, ELOOP for a link, ENOTDIR for a file in the way), with the component that
failed as its filename, so each caller words its own refusal; NotRegular and TooLarge are the two this module adds.
Stdlib only and Python 3.9 (annotations are never evaluated): a host script on /usr/bin/python3 and dev's box run a
vendored copy of it.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import secrets
import stat
from collections.abc import Iterable, Iterator
from typing import IO, Any

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
LEAF_FLAGS = os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class NotRegular(OSError):
    """The name is there, but as a folder, a FIFO, a device or a link rather than a regular file."""

    def __init__(self, name: str):
        super().__init__(errno.EINVAL, "not a regular file", name)


class TooLarge(ValueError):
    def __init__(self, name: str, size: int, limit: int):
        super().__init__(f"{name} is {size} bytes, over the limit of {limit}")
        self.name, self.size, self.limit = name, size, limit


def walk(root: str | os.PathLike[str] | int, folders: Iterable[str] = (), *, create: bool = False,
         mode: int = 0o755) -> int:
    """A descriptor on root/folders..., each folder opened by itself relative to its parent and never through a link;
    the caller closes it. root: a path (opened with O_NOFOLLOW: a link there is refused too) or a descriptor, which is
    borrowed and stays open. create: missing folders are made on the way (one made in between by someone else is
    fine; the open after it still refuses a link)."""
    fd = os.dup(root) if isinstance(root, int) else os.open(root, DIR_FLAGS)
    try:
        for name in folders:
            try:
                next_fd = os.open(name, DIR_FLAGS, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                with contextlib.suppress(FileExistsError):
                    os.mkdir(name, mode, dir_fd=fd)
                next_fd = os.open(name, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
    except BaseException:
        os.close(fd)
        raise
    return fd


def open_leaf(dir_fd: int, name: str, flags: int = os.O_RDONLY, mode: int = 0o644) -> int:
    """os.open of a name in a folder, with LEAF_FLAGS: no link followed, no FIFO waited on."""
    return os.open(name, flags | LEAF_FLAGS, mode, dir_fd=dir_fd)


def open_regular(dir_fd: int, name: str) -> tuple[int, os.stat_result]:
    """A read descriptor on the regular file name in dir_fd, and its fstat; NotRegular for anything else."""
    fd = open_leaf(dir_fd, name)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise NotRegular(name)
    return fd, info


def create(dir_fd: int, name: str, *, replace: bool, mode: int = 0o644) -> int:
    """A write descriptor on a regular file name in dir_fd. replace=False: the file must be new (FileExistsError)."""
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    fd = open_leaf(dir_fd, name, flags, mode)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise NotRegular(name)
    return fd


def read_bounded(fd: int, limit: int, name: str = "the file") -> bytes:
    """The bytes of an open regular file, at most limit, else TooLarge — counted as read, not trusted from fstat, as
    a file still being written can grow. Always closes fd."""
    try:
        # Before fdopen, which refuses a folder with its own, less telling error.
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise NotRegular(name)
        if info.st_size > limit:
            raise TooLarge(name, info.st_size, limit)
    except BaseException:
        os.close(fd)
        raise
    with os.fdopen(fd, "rb") as file:
        data = file.read(limit + 1)
    if len(data) > limit:
        raise TooLarge(name, len(data), limit)
    return data


def read_json_bounded(dir_fd: int, name: str, limit: int) -> Any:
    """A JSON file of at most limit bytes, reached as open_regular reaches it; ValueError when it is not JSON."""
    fd, _ = open_regular(dir_fd, name)
    return json.loads(read_bounded(fd, limit, name).decode("utf-8"))


def unlink_regular(dir_fd: int, name: str) -> None:
    """name removed from dir_fd, only when it is a regular file (a link or a folder is refused, never followed)."""
    if not stat.S_ISREG(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode):
        raise NotRegular(name)
    os.unlink(name, dir_fd=dir_fd)


@contextlib.contextmanager
def atomic_writer(path: str | os.PathLike[str], *, dir_fd: int | None = None, mode: int = 0o644,
                  replace: bool = True, fsync: bool = True) -> Iterator[IO[bytes]]:
    """A file written beside its target under a random name and moved over it only when the block ends without an
    error: a reader never sees half a file, a crash leaves no half file under the name.

    dir_fd: the folder (path is then a bare name), as os functions take it; without one the target's own folder is
    opened. A name there that is not a regular file is refused (NotRegular) rather than replaced. replace=False: the
    file is published with link(), which refuses an existing name — a link included — with FileExistsError."""
    name = os.fspath(path)
    if dir_fd is None:
        folder = os.open(os.path.dirname(name) or ".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        name = os.path.basename(name)
    elif os.sep in name:
        raise ValueError(f"with dir_fd, {name!r} must be a name, not a path")
    else:
        folder = dir_fd
    temporary = f".{name}.{secrets.token_hex(6)}.tmp"
    try:
        with contextlib.suppress(FileNotFoundError):
            if not stat.S_ISREG(os.stat(name, dir_fd=folder, follow_symlinks=False).st_mode):
                raise NotRegular(name)
        fd = open_leaf(folder, temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as file:
                yield file
                file.flush()
                os.fchmod(file.fileno(), mode)
                if fsync:
                    os.fsync(file.fileno())
            if replace:
                os.rename(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
            else:
                os.link(temporary, name, src_dir_fd=folder, dst_dir_fd=folder, follow_symlinks=False)
                os.unlink(temporary, dir_fd=folder)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary, dir_fd=folder)
            raise
    finally:
        if folder != dir_fd:
            os.close(folder)


def write_atomic(path: str | os.PathLike[str], data: bytes, *, dir_fd: int | None = None,
                 mode: int = 0o644, replace: bool = True, fsync: bool = True) -> None:
    """data as the file at path, whole or not at all (atomic_writer)."""
    with atomic_writer(path, dir_fd=dir_fd, mode=mode, replace=replace, fsync=fsync) as file:
        file.write(data)
