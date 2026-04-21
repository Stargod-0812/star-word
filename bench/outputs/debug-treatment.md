先判定是“泄漏”还是“分配过快”。看 Full GC 后老年代能否明显回落；回落很少，多半有对象留存；回落明显但很快又打满，多半是流量突增、缓存过大或大对象分配过快。

排查顺序：
1. 看 JVM 走势：`jstat -gcutil <pid> 5s`，重点看 `OU`、`YGC`、`FGC`。
2. 看堆分布：`jcmd <pid> GC.heap_info`、`jcmd <pid> GC.class_histogram`，连抓 2 到 3 次，对比哪些类持续增长。
3. 导出堆：`jcmd <pid> GC.heap_dump /tmp/heap.hprof`，用 MAT 查 `Dominator Tree`、`Leak Suspects`、大对象引用链。
4. 看线程：`jstack <pid> > /tmp/jstack.txt`，排查任务堆积、线程池打满、请求卡死。
5. 看本地内存：`jcmd <pid> VM.native_memory summary`，排除堆外内存、直接缓冲区、Metaspace。
6. 查配置与代码：缓存未设上限、静态 Map、ThreadLocal 未清、连接或会话对象滞留、消息消费阻塞。

线上先做两件事：打开 GC 日志，保留一份堆 dump。没有 dump，结论大多不可靠。
