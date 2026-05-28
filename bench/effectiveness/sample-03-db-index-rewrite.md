# 数据库索引优化

## 三个常见误区

**1. 给所有字段都加索引**——错。索引也有维护成本：写入时每个索引都要更新，B+ 树高度增加导致查询变慢。我们见过最极端的表有 30 个索引，DELETE 一行要 50ms。

**2. 只加单列索引**——大部分查询是多列条件。`WHERE a=? AND b=?` 用 `(a, b)` 联合索引比两个单列索引快 3-10 倍（看选择性）。

**3. 索引顺序拍脑袋决定**——左前缀原则。把选择性高（distinct 多）的列放前面，把范围查询的列放后面。`(status, created_at)` 比 `(created_at, status)` 在「找最近的待处理」场景快得多。

## 优化流程

1. 用 `pt-query-digest` 分析慢查询日志，找 TOP 10
2. 每条 SQL 用 EXPLAIN 看 type 列：const/eq_ref/ref 是好的，ALL/index 是差的
3. 评估增删索引：DBA 工具 `gh-ost` 在线改表

## 一个具体案例

订单表 5000 万行，按 `user_id + status` 查。原来只有 `user_id` 单列索引，慢查询 P99 = 1.2s。加 `(user_id, status, created_at)` 联合索引后 P99 降到 80ms。

## 不要做的事

- 不要在 OLTP 库上跑 OLAP 查询（用从库或专门的分析库）
- 不要给低基数字段加索引（如 gender、status 只有几个值的）
