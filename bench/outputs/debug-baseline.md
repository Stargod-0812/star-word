先看趋势，再定类，再抓证据。

1. 判定类型  
`jstat -gcutil <pid> 1s 20`：看 `OU/MU` 是否持续涨。  
`jcmd <pid> GC.heap_info`、`jcmd <pid> VM.native_memory summary`：区分堆内泄漏、Metaspace、直接内存、线程栈。  
`top -Hp <pid>`、`ps -L -p <pid>`：确认线程数是否异常。

2. 堆内排查  
`jcmd <pid> GC.class_histogram`：看大对象/实例数 Top。  
`jmap -dump:live,format=b,file=heap.hprof <pid>`：导堆，用 MAT 看 Dominator Tree、Leak Suspects、GC Roots。  
重点查：缓存未淘汰、集合持续增长、ThreadLocal、消息堆积、连接对象未释放。

3. GC 日志  
开启/检查：`-Xlog:gc*:file=gc.log:time,uptime,level,tags`（JDK11+）。  
看 Full GC 触发原因、晋升失败、Old 区回收后是否回不去。

4. 非堆排查  
Metaspace：动态代理/类加载器泄漏。  
直接内存：`-XX:MaxDirectMemorySize`，查 Netty/NIO Buffer。  
线程：线程池失控会放大栈内存与对象滞留。

5. 同步业务侧  
查慢请求、队列积压、流量突增、单机热点。  
命令：`jcmd <pid> Thread.print`、`vmstat 1`、`sar -n DEV 1`、`ss -antp`。

结论原则：先确认“哪块内存涨”，再用直方图/heap dump 锁定“谁持有、为何不释放”。
