# 数据库索引提效 — 一条联合索引 P99 降 27 倍

> 元注释：示范气-05（极致信息密度）、式-08（短句 + 长句节奏）。

---

`orders` 表 5000w 行，按 `user_id` 查最近订单，P99 800ms。加联合索引 `(user_id, created_at DESC)` 之后 P99 30ms。

## 慢在哪

原来只有 `user_id` 单列索引。SQL：

```sql
SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 20;
```

执行计划：先走索引找到 user_id 的所有行（活跃用户能有 5000 行），回表读 5000 个 row，再按 created_at 排序，最后取 20 个。回表 + 排序是瓶颈。

## 联合索引怎么救的

`(user_id, created_at DESC)` 让索引自带顺序。`WHERE user_id = ?` 命中前缀，`ORDER BY created_at DESC` 直接走索引顺序。MySQL 拿到前 20 个 entry 就能停，不用扫 5000 行也不用排序。回表 5000 → 20，提升 27 倍。

## 为什么不加 covering index

考虑过 `(user_id, created_at DESC) INCLUDE (amount, status)`——索引里直接带常用字段，连回表都省。但要付出：

- 索引大小从 800MB 涨到 3.2GB
- 写入放大：每次 INSERT/UPDATE 都要更新索引
- 我们的写 QPS 不低，3.2GB 索引 buffer pool 占用太大

折中：联合索引不 include，回表 20 行可以接受。

## 教训

排序慢的查询，先看 `ORDER BY` 字段在不在索引里。在 → 改成联合索引让 MySQL 走索引顺序；不在 → 加。covering index 是大招，先用普通联合索引，扛不住了再上 covering。
