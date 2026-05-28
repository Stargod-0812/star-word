# 正向语料库 — 写得好的中文技术文字长什么样

5 个原创技术写作片段，演示 star-word 规则的目标态。

每篇 200-500 字，覆盖五种常见技术写作场景。每篇前面有一段元注释（meta），说明这篇示例**有判断力**地命中了哪些 star-word 原则。

---

## 为什么需要正向语料

ban list 告诉模型不要写什么。但模型不知道**该写什么**。`before.md → after.md` 一对样本不够建立稳定 mental model；5+ 篇覆盖不同场景的样本能让模型在生成时有可对齐的目标分布。

正向语料 + forcing function（adapter 里的 6 条自检）+ 词表禁用 = 三层兜底。词表是底线，自检是过程，正向语料是 target state。

---

## 索引

1. [JVM Full GC 排查复盘](./01-debugging-jvm-fullgc.md)
2. [Redis 集群迁移 RFC](./02-rfc-redis-migration.md)
3. [缓存击穿事故复盘](./03-postmortem-cache-stampede.md)
4. [限流器选型设计](./04-design-rate-limiter.md)
5. [数据库索引优化提效](./05-perf-database-index.md)

---

## 用法

```bash
# 看每篇都干净
for f in examples/corpus/0*.md; do
  echo "=== $f ==="
  star-word review "$f" --mode strict
done
```

预期：所有文件文档分 ≥ 85（B 级以上），strict 模式下也不应触发任何机械违规。

如果某条规则在你的 corpus 上触发太多——很可能是规则误报，提 issue。
