# 线上接口超时排查思路

接口超时通常三类原因，按概率从高到低：

**数据库慢查询**——最常见。看慢查询日志（>100ms）的 TOP 10，用 EXPLAIN 看是否走索引。临时方案是加索引 + LIMIT；根治要看业务是否真需要这个查询。

**下游服务异常**——级联超时。先看下游服务的 P99 latency 是否抖动；如果是，给下游加熔断（Hystrix/Sentinel），熔断后走降级逻辑。

**网络抖动**——少见，但要会区分。TCP retransmission rate > 0.1% 算异常；本机 ping 同 AZ 机器看 latency。

排查顺序：先看监控大盘有无明显异常，再看错误日志，最后用 trace 工具定位具体调用链。

工具：监控用 Prometheus + Grafana，trace 用 Jaeger，日志用 ELK。
