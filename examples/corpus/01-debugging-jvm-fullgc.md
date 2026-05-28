# JVM Full GC 排查复盘

> 元注释：这篇示范气-01（直接入题）、气-02（每句推进）、气-03（给出判断）、式-08（句长有变化）。

---

线上服务每隔 4 小时 Full GC 一次，每次卡 8 秒。原因是 ParNew 晋升对象太多，Old Gen 满了触发 CMS。改完后稳定。

## 排查路径

`-XX:+PrintGCDetails` 翻日志，发现 promotion failure 频发。Eden 才 256MB，Young GC 一次挤进 Old 50MB——这不是泄漏，是分代尺寸错了。

业务里有个批处理任务，每分钟跑一次，瞬时申请 100MB 的临时 list。这堆对象按理在 Eden 就能回收，但 Eden 太小，直接溢到 S0/S1，再溢到 Old。两小时积累一波，触发 CMS。

## 改法

调三个参数。

```
-Xmn4g                  # Young 从 256m → 4g
-XX:SurvivorRatio=4     # Eden:S0:S1 从 8:1:1 → 4:1:1
-XX:MaxTenuringThreshold=15  # 让对象在 S 区多熬几次再晋升
```

## 为什么 G1 没解

试过 G1，Full GC 频率没降。原因：G1 的 region size 默认 1MB，那个 100MB 的临时 list 直接当 humongous object 进 Old。换 ParNew + 调大 Young 才是对的。

## 教训

GC 调优先看分代溢出，不要先换 collector。换 collector 是结构性大动作，分代尺寸是参数级小动作——先做小的，错了改回来成本低。
