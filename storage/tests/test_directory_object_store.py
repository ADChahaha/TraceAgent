"""DirectoryObjectStore 的隔离边界：桶名白名单、key 相对路径校验。"""

from pathlib import Path

import pytest

from storage.core.object_store import DirectoryObjectStore


@pytest.fixture
def store(tmp_path):
    return DirectoryObjectStore(tmp_path)


def test_bucket_whitelist_rejects_path_ambiguity(store):
    """空名、点号、路径分隔符和大小写越界都不允许，"." 不能解析到数据根。"""
    for name in ("", ".", "..", "a/b", "a\\b", "res_x/", "Res_x", "..x", "x."):
        with pytest.raises(ValueError):
            store.create_bucket(name)


def test_bucket_whitelist_accepts_existing_shapes(store, tmp_path):
    """现有命名（res_<hex>、b-<hex>）保持合法。"""
    for name in ("a", "res_a1b2c3", "b-1a2b3c"):
        store.create_bucket(name)
        assert (tmp_path / name).is_dir()


def test_object_keys_reject_empty_and_dot(store):
    """key 为空串或 "." 时 parts 为空，必须拒绝而不是指向桶目录本身。"""
    store.create_bucket("res_a1b2c3")
    store.put_object("res_a1b2c3", "docs/a.txt", b"x")
    for key in ("", "."):
        with pytest.raises(ValueError):
            store.put_object("res_a1b2c3", key, b"x")
        with pytest.raises(ValueError):
            store.get_object("res_a1b2c3", key)
        with pytest.raises(ValueError):
            store.head_object("res_a1b2c3", key)
        with pytest.raises(ValueError):
            store.delete_object("res_a1b2c3", key)


def test_dot_bucket_cannot_reach_other_buckets(store):
    """以 "." 为桶的读写不得落到数据根、不得触达兄弟桶。"""
    store.create_bucket("res_a1b2c3")
    store.put_object("res_a1b2c3", "secret.txt", b"secret")
    with pytest.raises(ValueError):
        store.get_object(".", "res_a1b2c3/secret.txt")
    with pytest.raises(ValueError):
        store.put_object(".", "res_a1b2c3/injected.txt", b"pwn")
    assert store.get_object("res_a1b2c3", "injected.txt") is None
    with pytest.raises(ValueError):
        store.list_objects(".")
