# test_directory_object_store.md

对应测试文件：`tests/test_directory_object_store.py`

## 验证内容

验证 `DirectoryObjectStore` 的隔离边界：桶名白名单、key 相对路径校验，以及
`.` 桶名不能越过"一个桶 = 数据根下一个子目录"的映射。

## 实现思路

- `_bucket_dir`：桶名白名单（小写字母/数字/下划线/连字符，1-63 字符，无点号）
  加拼接后解析校验（必须直接位于数据根下），不合法抛 `InvalidBucketName`。
- `_obj_path`：key 拒绝空串、`.`（`Path.parts` 为空，会指向桶目录本身）、
  绝对路径和 `..`，不合法抛 `InvalidKey`。

## 测试函数

| 函数 | 验证内容 |
| --- | --- |
| `test_bucket_whitelist_rejects_path_ambiguity` | 空名、`.`、`..`、路径分隔符、尾部斜杠、大写、以点开头结尾的名字全部拒绝。 |
| `test_bucket_whitelist_accepts_existing_shapes` | 现有命名（`res_<hex>`、`b-<hex>`、单字符）保持合法并建出子目录。 |
| `test_object_keys_reject_empty_and_dot` | key 为空串或 `.` 时 put/get/head/delete 全部拒绝。 |
| `test_dot_bucket_cannot_reach_other_buckets` | 以 `.` 为桶读、写、列举都抛异常，兄弟桶对象不被触碰、不被注入。 |
