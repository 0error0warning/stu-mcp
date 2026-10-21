# 容器部署

本模板面向 Linux 服务器上的一个用户、一个 HTTP worker。连接方式、授权边界和学校网络诊断见
[服务器部署](server.md)。Docker 镜像在本地构建，目前不提供已发布镜像地址。

## 初始化并启动

在服务器上以普通用户操作。构建 UID/GID 与该用户一致，让容器直接读取其私有密钥文件；不要把文件放宽为
全局可读，也不要以 root 运行这个模板。密钥目录和数据卷分别保存。

```sh
export STU_MCP_UID="$(id -u)"
export STU_MCP_GID="$(id -g)"
export STU_MCP_SECRETS_DIR="$HOME/.config/stu-mcp/secrets"
mkdir -p -m 700 "$HOME/.config/stu-mcp"
docker compose build
docker run --rm \
  --mount "type=bind,src=$HOME/.config/stu-mcp,dst=/private" \
  stu-mcp:local server-init /private/secrets
docker compose up -d
```

`server-init` 只接受新目录，生成 `master.key` 和 `http-token`，不显示文件内容，不覆盖原有密钥。
已经初始化的实例跳过这一步。升级沿用同一个 UID/GID、密钥目录和数据卷；更换主密钥会令原加密数据无法解密。
在所选目录的父目录已有配置时，保留其原权限与文件。
可将这三个非敏感的 UID/GID、目录路径配置保存到本地 `.env`（已被 Git 忽略），便于后续更新沿用；不要把密钥或令牌内容写入其中。

默认 `STU_MCP_INTERACTION=disabled`，不会启动远程桌面。无需账号的公开工具可直接用；学校登录需要下面的交互配置。
容器内的 MCP 监听全部接口，Compose 只发布宿主回环端口：

| 宿主地址 | 用途 |
| --- | --- |
| `127.0.0.1:8765/mcp` | 需要独立 Bearer 令牌的 MCP HTTP |
| `127.0.0.1:8766` | 需要临时能力链接的设置页 |
| `127.0.0.1:6080/vnc.html` | 启用虚拟显示后，需 VNC 密码的 noVNC |

若通过私有 HTTPS 反向代理连接 MCP，在 Compose 的 `command` 中保留 Dockerfile 全部启动参数并追加
`--public-url https://你的私有域名/mcp`；该参数声明允许的 Host/Origin，不会创建隧道或 HTTPS 证书。
设置页使用严格的回环 Host/Origin 校验，使用同端口 SSH 转发访问。

## 无桌面学校登录

先用同一镜像交互设置 VNC 密码，不把密码放到命令行或环境变量：

```sh
docker run --rm -it \
  --mount "type=bind,src=$STU_MCP_SECRETS_DIR,dst=/private" \
  --entrypoint /bin/sh stu-mcp:local \
  -c 'umask 077; exec x11vnc -storepasswd /private/vnc_auth'
export STU_MCP_INTERACTION=virtual-display
docker compose up -d
```

模板使用 Xvfb、Openbox、x11vnc 和 noVNC；学校浏览器仍为有界面的 Chromium。X11 启用认证且不监听 TCP，
VNC 仅监听容器回环并要求密码，浏览器不开放 CDP/调试端口。VNC 密码不替代安全隧道。

在自己的电脑建立转发，并保持命令运行：

```sh
ssh -N -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 -L 6080:127.0.0.1:6080 用户@服务器
```

在服务器终端读取设置页的临时链接：

```sh
docker compose exec stu-mcp cat /run/stu-mcp/setup-url
```

把链接打开在自己的浏览器；再打开 `http://127.0.0.1:6080/vnc.html`，输入 VNC 密码。在设置页选择学校登录，
然后到 noVNC 桌面完成扫码、验证码或账号输入。报修窗口也出现在这个桌面中，沿用提交前展示确认和单次提交守卫。
设置页能力链接保存在临时私有文件，不写进容器日志；不要分享它或包含该链接的截图。

## 运行与验证边界

- 任一必要组件退出时，入口脚本结束整个实例，由 Compose 的重启策略接管。关闭时先向已记录的子进程发 TERM，
  给约两秒清理机会，再向仍存活的这些 PID 发 KILL 并回收；不会扫描或终止其他进程。临时能力链接会重新生成。
- 会话与缓存保存在 `stu-mcp-data` 数据卷，主密钥只从宿主只读挂载。备份时分别保护两者。
- 断开 MCP 客户端不停止容器或签到后台；停止、重建整个容器会结束容器内进程，已有监听计划按原后台恢复规则处理。
- 重启会丢失内存中的报修草稿和确认；提交结果不确定时先只读查单，不能据此重提。
- noVNC、SSH/Tailscale 和校园内网是不同访问路径。学校 DNS、SSO、报修及来源请求均发生在容器所在服务器；
  连接 MCP 成功不证明服务器能访问校园内网。不自动改 DNS、路由、代理或 TLS 校验。
- 本轮已检查模板结构、端口/密钥隔离和 shell 语法，并进行合成入口测试；当前开发机无 Docker，
  尚未完成镜像构建、实际 noVNC 登录或学校业务验收。首次部署请逐项验证这些流程。
