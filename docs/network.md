# 校园服务的直连与代理诊断

STU MCP v0.6.0 学生预览版提供 `diagnose_campus_network`，CLI 为 `stu-mcp network`。按服务检查固定入口的匿名 GET 响应头和系统 DNS；SSO按依赖需要检查，本机代理对照需明确开启。不读正文或登录信息，不提交表单，不改配置。普通业务读取不调用整轮诊断。

它与[学校入口批量检测](network-audit.md)同属“网络访问与排障”：一个深入单服务及其必要依赖，一个横向比较固定目录。校园功能和登录关系见[入口映射](campus-services.md)；公开导航普查是独立的证据整理，不会自动扩大两个工具的请求白名单。

## 按服务选择访问方式

| 服务 | 默认访问策略 | 诊断范围 |
| --- | --- | --- |
| `r` 综合报修 | 当前运行主机应用层直连，不预设只允许校园网 | 默认只查入口；需要登录时加查SSO |
| 一网通办 `service` | 当前主机直连，具体业务另行核验 | 默认只查入口；需要登录时加查SSO |
| 宿舍 `repair` | 先用本机已有网络直连；失败后提示核实校园网或获准VPN接入 | 默认查报修站和SSO；不能宣称永久仅校园可用 |
| SSO | 单独直连；故障只影响依赖认证的操作 | 单独一个端点 |
| 学校官网 | 按当前主机直连，不因其失败跳过其他服务 | 默认只查官网 |
| ITS | HTTP与HTTPS各自匿名诊断，不作为优先网络报修入口 | 不凭空添加SSO依赖，不降级发送认证 |

这套选择保留OA受限读取的WebVPN流程；没有添加Hermes、SSH或Tailscale自动业务执行器。校园接入指 MCP 宿主已有的真实网络/VPN路径，远程客户端所在校园不能自动赋予服务器该路径。代码不认证物理网络位置或私网目标身份，也不提供云主机私网连接隔离；不能把提示当作上述能力验收。

学校认证默认使用直连 HTTP 客户端并校验 HTTPS，普通代理不参与认证兜底。教务网页配置内部处理已验证的固定回调，并将对应读取路线随会话加密保存；CLI 兼容参数保持可用。OA 目录指定的 HTTP 8118 传输仍须另行明确开启，默认关闭，不从匿名探测成功或教务登录扩展许可；详见[认证与传输](authentication.md)。诊断本身仍只发送匿名探测，不携带学校会话。

匿名采集复用同一个HTTP客户端的连接池。单个 `CampusHTTP` 读取批次最多一次额外建连尝试，只有客户端trace显示TLS尚未开始且为连接超时、剩余预算足够时才退避150ms重试。该阶段仍可能含解析，不能声称已隔离到目标TCP。DNS明确失败、证书错误、TLS阶段或阶段不明的连接失败不自动重试；已收到部分正文也不重放。认证读取与POST均不套用这项重试。

匿名读取连接超时预算3秒；认证读取和POST保留原8秒连接预算。单次I/O最多18秒，读取批次沿用45秒预算；这些是产品预算，实验没有证明全局最优。匿名读取遇到连接/DNS/TLS失败时，仅在当前客户端内对同一协议、主机和规范端口冷却15秒；缓存失败附 `cached_failure` 和剩余时间，其他主机和协议继续读取，HTTP资源错误不触发整站冷却。新一轮客户端重新尝试，不后台轮询，不保存网络库存。

## 批量比较学校入口与公共 DNS

用 `audit_campus_network` 或 `stu-mcp network-audit` 检查当前登记的16个学校域名、17个入口。仅显式开启 `compare_public_dns` / `--compare-public-dns` 时，额外对比阿里和腾讯公共DNS的A/AAAA。系统解析、指定DNS应答、HTTP响应分开记录；公共DNS返回地址不会改变业务传输。普通采集不会自动运行全量检查。入口清单、状态解释和本次热点实测见[批量检测](network-audit.md)。

## 四种环境

| 用户说明的环境 | MCP 的处理 |
| --- | --- |
| 校园网，未配置 HTTP/SOCKS 代理 | 直连业务站和统一认证；失败时检查校园网接入认证、DNS和路由 |
| 非校园网，未配置 HTTP/SOCKS 代理 | 可公开访问的服务仍可直连；私网服务不可达时报告接入限制，不判断学校停服 |
| 校园网，配置 Clash、v2rayN 等代理 | 校园 HTTP 和业务窗口保持应用层直连；排障时明确开启本机代理对照，不改规则或关闭代理 |
| 非校园网，配置 Clash、v2rayN 等代理 | 直连优先，本机代理对照按需开启；普通代理不等于校园 VPN，不因首页代理探测成功切换登录或报修传输 |

`location_hint` 只接受 `campus`、`off_campus`、`unknown`。仅当用户已说明接入网络时传前两者，否则留空。不根据私有 IP、DNS、代理配置或能打开网页推断物理位置。校园 VPN 也可能让校外电脑访问内网。

配置检测与流量路径不同。HTTPS入口读取当前进程的HTTPS_PROXY/ALL_PROXY，ITS旧HTTP入口读取HTTP_PROXY/ALL_PROXY（均含小写形式）；Windows系统代理同样按目标协议选择，不把HTTPS专用配置当成HTTP配置。不读代理客户端账户、订阅或控制器密钥，不猜客户端名称。其他操作系统的系统代理、PAC/WPAD、TUN和系统路由没有完整检测，明确标记未知/未评估。检测到配置不表示代理在运行，未检测到显式配置也不能排除TUN。

只比较无凭据的本机 HTTP、HTTPS、SOCKS5/SOCKS5h 端点；远端、PAC、格式无效或需凭据代理只报告未探测。显式比较忽略该次的 NO_PROXY/系统绕过规则，并附 `bypass_matches_target`，不能当成用户原浏览器的实际路径。相同环境/系统代理地址合并探测。

## 使用和结果

```sh
stu-mcp network --service-id sangpushan_repair --location-hint campus --refresh
# r匿名入口；需要登录才加查SSO，代理对照另行开启
stu-mcp network --service-id campus_repair
stu-mcp network --service-id campus_repair --check-login --compare-proxy
# 明确只查宿舍入口，或分别检查ITS两个协议
stu-mcp network --service-id sangpushan_repair --anonymous-only
stu-mcp network --service-id network_repair_http
stu-mcp network --service-id network_repair
```

| service_id | 实际检测入口 |
| --- | --- |
| `sangpushan_repair`（默认） | `https://repair.stu.edu.cn/`，桑浦山学生社区宿舍报修 |
| `campus_repair` | `https://r.stu.edu.cn/`，含两校区网络故障分类的综合报修 |
| `network_repair` | `https://its.stu.edu.cn/`，原有网络报修引用的HTTPS端点 |
| `network_repair_http` | `http://its.stu.edu.cn/`，旧HTTP入口，仅匿名诊断 |
| `school_service_portal` | `https://service.stu.edu.cn/fe/`，一网通办目录与申请 |
| `school_sso` | `https://sso.stu.edu.cn/login`，统一认证 |
| `school_homepage` | `https://www.stu.edu.cn/`，学校官网 |

宿舍repair默认并行检查统一认证；r和一网通办仅在 `check_login=true` 时加查，`false`明确只查入口。官网与ITS不添加未经核验的登录依赖。`compare_proxy=true`才发出代理比较请求，默认仅只读识别配置。`its` 失败不影响其他站点的结论，也不证明已停用；一网通办可达不代表有故障工单功能。完整用途见[服务目录](campus-services.md)。

- `direct_ready`：此次选定的检查均已收到可继续访问的响应头；不证明完整正文、认证、表单或受理。`can_attempt_anonymous_read`与`can_attempt_login`分开，没检查SSO时登录能力为null。
- `direct_blocked`：至少一个所需端点此次超时、拒绝、连接失败或返回异常；逐站保留原因，不能说全校服务宕机。
- `direct_inconclusive`：等待预算耗尽、工作槽占满等导致证据不足，不等于端点不可达。

`checks` 逐站返回直连结果、DNS地址类型和按需开启的本机代理对照；不返回IP清单、代理地址、凭据、正文、Cookie或SSO跳转查询。代理对照成功也不自动回退。系统DNS出现198.18.0.0/15时标记可能的fake-IP影响，不能据此确定客户端。失败阶段优先根据异常类型和客户端trace判断，无法区分的建连/TLS写 `connect_or_tls`；代理错误保留 `proxy_or_upstream_unknown`，实际代理出站为unknown，不把CONNECT或端口可达当作原站成功。

HTTP不跟随跳转、没有自动重试，TLS检查保持开启。探测并发，总等待预算6秒；阻塞的系统DNS在有数量上限的后台线程中结束，不拖住MCP关机，不无限新建线程。进程启动和浏览器总耗时另计。短缓存15秒，返回 `checked_at`、`cached`、`age_seconds`；配置变化使缓存失效，切网络、改DNS/TUN或需要最新结果时用 `refresh=true`。缓存只在进程内。

ITS旧HTTP诊断允许观察本源HTTP跳转的响应头，但不跟随或发送认证；HTTPS入口指向HTTP时仍不判为可继续访问，禁止自动降级。该区别不影响正式报修HTTPS策略。

宿舍报修打开学校窗口前另做一次**新鲜的业务站及统一认证直连预检**，同样并行、预算6秒，不用旧诊断缓存。失败时提示诊断，不反复弹登录窗口。显式直连仍不能绕过TUN、系统DNS或路由。诊断不改变“展示实际表单→用户确认→单次提交→只读核对”的规则；中断后禁止重复发单。

## 验证范围

软件测试中的四种环境、SSO单独失败、fake-IP、未知位置、凭据脱敏、缓存和超时采用合成数据；真实HTTP/SOCKS/TLS软件回归仅用本机回环服务，不创建学校工单。较早一次本机匿名检查repair/SSO及本机代理均可达，耗时约0.5秒，不是持续健康保证。

访问策略另参考用户委托的2026-10-19 v2网络矩阵报告，SHA-256 `7a5acea07e1ce2c8c7f6430f48b40f5b72bac7f93900275a7c52cab15306da77`。研究窗口中新加坡r为22/22、一网通办21/21，repair为21次DNS失败；初始校园同一台电脑及其远程调用路径每格只保留8轮，repair/SSO/r/service入口均取得8/8成功。代理条件可命中DIRECT，独立非校园代理条件未形成。换网后样本单独分组，TLS解释使用修正后的normalized_stages。

这些证据支持逐服务判断，不支持“校园网本身不稳定”“repair永久仅限校园”或完整矩阵已验收。报告原始脱敏数据及拓扑保留在用户私有研究目录，不随仓库分发；本项目没有自动接入研究隧道。实现验证见[验证记录](verification.md)。
