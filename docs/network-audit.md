# 学校入口批量 DNS 与直连检查

开发版提供只读 `audit_campus_network`，CLI 为 `stu-mcp network-audit`。检查固定登记的学校第一方入口；当前是16个域名、17个协议入口，ITS的HTTP/HTTPS分别测试。来源为产品访问策略、维护的校园服务目录和实际采集来源白名单，另有网络中心公开说明路径。不是全校完整网站清单；狐友、充电、雨课堂和第三方导航不在此学校域名批次中。

```sh
# 当前主机的解析与匿名直连，不改设置
stu-mcp network-audit --refresh
# 用户已说明使用非校园网络：再向两家公共DNS查询A/AAAA作对照
stu-mcp network-audit --location-hint off_campus --compare-public-dns --refresh
```

MCP 对应 `audit_campus_network(location_hint="off_campus", compare_public_dns=true, refresh=true)`。`location_hint`只是用户的接入网络提示；不根据SSID、私有IP、代理配置推断人在校内还是校外。工具不读取SSID，不改系统DNS、hosts、代理、TUN或网络连接；不自动切换业务访问路径。普通业务读取仍按来源执行，不自动增加批量预检。

## 三类结果分别解释

| 观察 | 能说明的范围 |
| --- | --- |
| `hosts[].system_dns` | 本机OS的A/AAAA合并解析，包含缓存、hosts和系统解析策略；失败写`not_resolved`或临时/未知错误，不冒充权威DNS的NXDOMAIN |
| `hosts[].public_dns` | 显式开启时向固定公共DNS地址查A/AAAA。分别记录`nxdomain`、`no_answer`、`timeout`等；没有AAAA不等于域名不存在。DNS应答不改变HTTP使用的系统解析器和路由 |
| `checks[].direct` | 该协议/入口的一次匿名GET响应头，忽略HTTP代理环境变量；不跟随重定向、读正文或发送登录态，TLS校验保持开启。仍受系统DNS、路由和TUN影响 |

公共对照目标为[阿里公共DNS](https://alidns.com/)的`223.5.5.5`与[腾讯Public DNS](https://cloud.tencent.com/document/product/302/110786)的`119.29.29.29`，不修改网卡配置。查询使用[dnspython 2.9 Resolver](https://dnspython.readthedocs.io/en/stable/resolver-class.html)，禁用搜索后缀和库级缓存，对同一主机/提供方的A/AAAA共用2.5秒预算。显式发送到某地址不能排除网络对53端口的拦截，解析器身份未认证。结果只比较解析状态与地址类型，不判断两家返回的具体IP是否相同，不强制连接每个应答地址。

地址仅保留数量、IPv4/IPv6与公有/私有/fake-IP等类型，不返回目标IP清单、原始应答、代理地址、正文、Cookie或认证跳转参数。公开DNS的`resolver_address`是固定提供方地址，不是业务服务器地址。

`entry_responding`表示此次入口收到可继续访问的匿名响应头；`entry_rejected`表示收到401/403，仍能区分于未连接到服务器。`os_dns_unresolved`、`direct_probe_failed`、`tls_failed`和`http_error_or_unexpected`分别保留失败范围；`inconclusive`、`probe_busy`、`deadline_exceeded`不能写成网站停服。SSO成功不代表repair等其他系统成功，WebVPN门户成功也不代表其OA别名或受保护业务成功。

队列和全局工作线程有界，批量最多12个工作线程，总调用等待15秒。卡住的系统解析占用原有工作槽直到退出，后续调用不会无限建线程；期限后不启动剩余工作，迟到结果不改变已返回报告。`partial`和`summary.incomplete_dns_checks`明确指出未完成的观察；已返回A但AAAA超时也会注明。调用结束后仅保留进程内15秒缓存，返回`checked_at/cached/age_seconds`；切网后用`refresh=true`。进程启动时间不含在探测预算内。

## 2026-10-19 的一次非校园热点实测

22:53对当前手机热点网络执行一次上述公开DNS对照批次；实际探测5.312秒，连同CLI进程启动约9.795秒。没有登录、读用户工单或修改网络。完整报告留在本机诊断目录，不随仓库分发。

| 范围 | 本次观察 |
| --- | --- |
| `repair.stu.edu.cn`、`a.stu.edu.cn` | 本机未解析，两家公共DNS的A/AAAA均返回NXDOMAIN；HTTP失败阶段为DNS |
| `its.stu.edu.cn` HTTP/HTTPS、`oa.stu.edu.cn` HTTP | 本机和公共DNS有IPv4私有地址，匿名直连超时；公开DNS查得到仍不代表热点具备对应内网路由 |
| `oa-stu-edu-cn.webvpn.stu.edu.cn` HTTPS | 有解析，但本次TLS证书校验失败；没有关闭校验或绕过警告 |
| 其余11个入口 | r、一网通办、SSO、官网、netms、uptime、xsc、WebVPN门户、教务、MySTU、网络中心公开说明收到200或可接受的301/302响应头。未验证正文、登录或业务可用 |

这轮总状态为`partial`：阿里DNS对ITS的A记录有应答，但AAAA查询超时，不能改写为ITS无AAAA或整个域名无解析。以上只描述当时该主机这条网络，不能当作所有校外Wi-Fi的永久不可用清单，不能据此宣布ITS退役或学校停服。软件边界测试使用合成DNS/HTTP，与本轮真实匿名网络探测分别记录。
