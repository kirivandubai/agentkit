"""X2-20: folders walked through descriptors and never through a link, FIFOs not waited on, files written whole."""

import errno
import os
import stat
import threading

import pytest

from agentkit import safefs


@pytest.fixture
def root(tmp_path):
    (tmp_path / "root" / "a" / "b").mkdir(parents=True)
    (tmp_path / "root" / "a" / "b" / "f.txt").write_text("hello")
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "f.txt").write_text("secret")
    return tmp_path / "root"


def test_walk_and_read(root):
    fd = safefs.walk(root, ["a", "b"])
    try:
        leaf, info = safefs.open_regular(fd, "f.txt")
    finally:
        os.close(fd)
    assert stat.S_ISREG(info.st_mode) and safefs.read_bounded(leaf, 10) == b"hello"


def test_walk_refuses_a_link_anywhere_on_the_way(root, tmp_path):
    (root / "a" / "link").symlink_to(tmp_path / "outside")
    with pytest.raises(OSError) as error:
        safefs.walk(root, ["a", "link"])
    assert error.value.errno in (errno.ELOOP, errno.ENOTDIR) and error.value.filename == "link"
    # The root itself, given as a path, is no link either.
    (tmp_path / "root-link").symlink_to(root)
    with pytest.raises(OSError):
        safefs.walk(tmp_path / "root-link")


def test_walk_refuses_a_file_in_the_way_and_says_a_missing_folder(root):
    with pytest.raises(NotADirectoryError):
        safefs.walk(root, ["a", "b", "f.txt"])
    with pytest.raises(FileNotFoundError) as error:
        safefs.walk(root, ["a", "nope"])
    assert error.value.filename == "nope"


def test_walk_creates_and_borrows_a_descriptor(root):
    base = safefs.walk(root)
    fd = safefs.walk(base, ["new", "deeper"], create=True)
    os.close(fd)
    os.fstat(base)  # the borrowed one stays open
    os.close(base)
    assert (root / "new" / "deeper").is_dir()


def test_a_folder_swapped_for_a_link_after_the_check_is_not_followed(root, tmp_path, monkeypatch):
    """The race: a check by name, then a swap, then the open. Here the open itself is the check, so the swap made
    between two steps of the walk is met by O_NOFOLLOW."""
    real_open = os.open
    swapped = []

    def swapping_open(path, flags, *args, **kwargs):
        if path == "b" and not swapped:
            swapped.append(True)
            os.rename(root / "a" / "b", root / "a" / "b-moved")
            (root / "a" / "b").symlink_to(tmp_path / "outside")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapping_open)
    with pytest.raises(OSError) as error:
        safefs.walk(root, ["a", "b"])
    assert swapped and error.value.errno in (errno.ELOOP, errno.ENOTDIR)


def test_a_leaf_link_is_refused(root, tmp_path):
    (root / "a" / "b" / "evil").symlink_to(tmp_path / "outside" / "f.txt")
    fd = safefs.walk(root, ["a", "b"])
    try:
        with pytest.raises(OSError) as error:
            safefs.open_regular(fd, "evil")
        assert error.value.errno == errno.ELOOP
    finally:
        os.close(fd)


def test_a_fifo_is_refused_not_waited_on(root):
    os.mkfifo(root / "pipe")
    fd = safefs.walk(root)
    done = []

    def read():
        try:
            safefs.open_regular(fd, "pipe")
        except safefs.NotRegular:
            done.append("refused")

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(5)
    assert done == ["refused"]
    # A writer of a FIFO without a reader gets ENXIO at once rather than blocking.
    with pytest.raises(OSError) as error:
        safefs.create(fd, "pipe", replace=True)
    assert error.value.errno == errno.ENXIO
    os.close(fd)


def test_a_folder_is_not_a_regular_file(root):
    fd = safefs.walk(root)
    try:
        with pytest.raises(safefs.NotRegular):
            safefs.open_regular(fd, "a")
        assert isinstance(safefs.NotRegular("x"), OSError)
    finally:
        os.close(fd)


def test_read_bounded(root):
    path = root / "a" / "b" / "f.txt"
    with pytest.raises(safefs.TooLarge) as error:
        safefs.read_bounded(os.open(path, os.O_RDONLY), 4, "f.txt")
    assert (error.value.size, error.value.limit) == (5, 4)
    assert safefs.read_bounded(os.open(path, os.O_RDONLY), 5) == b"hello"
    folder = os.open(root, os.O_RDONLY)
    with pytest.raises(safefs.NotRegular):
        safefs.read_bounded(folder, 5)


def test_read_json_bounded(root):
    (root / "x.json").write_text('{"a": 1}')
    fd = safefs.walk(root)
    try:
        assert safefs.read_json_bounded(fd, "x.json", 100) == {"a": 1}
        with pytest.raises(safefs.TooLarge):
            safefs.read_json_bounded(fd, "x.json", 3)
    finally:
        os.close(fd)


def test_create_new_or_replace(root):
    fd = safefs.walk(root)
    try:
        with pytest.raises(FileExistsError):
            safefs.create(fd, "a", replace=False)
        out = safefs.create(fd, "n.txt", replace=False, mode=0o600)
        os.write(out, b"x")
        os.close(out)
        out = safefs.create(fd, "n.txt", replace=True)
        os.close(out)
        assert (root / "n.txt").read_bytes() == b""
    finally:
        os.close(fd)


def test_write_atomic_by_path_and_by_descriptor(root):
    target = root / "w.txt"
    safefs.write_atomic(target, b"one", mode=0o640)
    assert target.read_bytes() == b"one" and stat.S_IMODE(target.stat().st_mode) == 0o640
    fd = safefs.walk(root)
    try:
        safefs.write_atomic("w.txt", b"two", dir_fd=fd)
        with pytest.raises(ValueError):
            safefs.write_atomic("a/w.txt", b"x", dir_fd=fd)
    finally:
        os.close(fd)
    assert target.read_bytes() == b"two"
    assert [p.name for p in root.iterdir() if p.name.endswith(".tmp")] == []


def test_write_atomic_never_replaces_what_is_no_regular_file(root, tmp_path):
    (root / "link").symlink_to(tmp_path / "outside" / "f.txt")
    with pytest.raises(safefs.NotRegular):
        safefs.write_atomic(root / "link", b"x")
    with pytest.raises(safefs.NotRegular):
        safefs.write_atomic(root / "a", b"x")
    assert (tmp_path / "outside" / "f.txt").read_text() == "secret"


def test_write_atomic_without_replace_refuses_an_existing_name(root):
    safefs.write_atomic(root / "once", b"first", replace=False)
    with pytest.raises(FileExistsError):
        safefs.write_atomic(root / "once", b"second", replace=False)
    assert (root / "once").read_bytes() == b"first"
    assert [p.name for p in root.iterdir() if p.name.endswith(".tmp")] == []


def test_a_failed_write_leaves_neither_half_a_file_nor_its_temporary(root):
    (root / "keep").write_bytes(b"old")
    with pytest.raises(RuntimeError), safefs.atomic_writer(root / "keep") as file:
        file.write(b"half")
        raise RuntimeError("disk said no")
    assert (root / "keep").read_bytes() == b"old"
    assert [p.name for p in root.iterdir() if p.name.endswith(".tmp")] == []


def test_unlink_regular(root, tmp_path):
    (root / "link").symlink_to(tmp_path / "outside" / "f.txt")
    fd = safefs.walk(root)
    try:
        with pytest.raises(safefs.NotRegular):
            safefs.unlink_regular(fd, "link")
        with pytest.raises(safefs.NotRegular):
            safefs.unlink_regular(fd, "a")
        (root / "gone").write_text("x")
        safefs.unlink_regular(fd, "gone")
    finally:
        os.close(fd)
    assert not (root / "gone").exists() and (tmp_path / "outside" / "f.txt").exists()
