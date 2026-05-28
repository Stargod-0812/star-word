# Redis 集群迁移 RFC

> 元注释：示范气-03（明确选 A 不选 B）、气-04（先 reframe 问题）、式-08（节奏变化）。

---

我们不该迁移 Redis 集群，应该先把 hot key 拆了。

## 真问题不是容量

申请理由写的是「容量从 64GB → 256GB」。真实数据：当前 64GB 实际占用 38GB，连 60% 都不到。慢查询日志里 90% 集中在 3 个 key，单 key 都 500MB+。

容量是表象，hot key 才是病。再加机器，hot key 还在那台机器上。

## 改 hot key 的方案

三个 key 分别是：
- `hot_user_list` —— 全平台活跃用户榜，500MB list
- `recommendation_pool` —— 推荐候选池，800MB hash
- `session_index` —— 全局 session 索引，1.2GB sorted set

`hot_user_list` 拆 256 片，按 user_id mod 256 路由。读放大 1 倍可接受（榜单本来就要 merge）。

`recommendation_pool` 改成 Redis Cluster + hash tag，让同一用户的候选落同一片。这个不需要扩容。

`session_index` 最贵——按 region + day 分 32 × 7 = 224 片。索引重写两周。

## 如果非要扩容

那也是拆完 hot key 之后再扩。不然 256GB 的机器还是会被这 3 个 key 把单核 CPU 打满，集群只是看起来大。

## 不接受的反对意见

「拆 key 太麻烦，不如换大机器」—— 大机器买回来 hot key 还是单点，3 个月后又要再申请一次更大的。这是技术债的复利。
