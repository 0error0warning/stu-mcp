# 容器部署

本页提供 v0.6.1 的可选本地构建模板，配套 CI 的镜像构建与离线启动检查。模板面向 Linux 服务器上的一个用户、一个 HTTP worker，
由 tini 直接启动 `stu-mcp`，不包含显示服务、远程桌面或额外管理网页进程。
默认镜像不安装 Playwright、Chromium、Xvfb 或远程桌面；各来源默认通过 HTTP 和本人 CLI 认证。
连接方式、授权边界和网络诊断见[服务器部署](server.md)。目前需本地构建镜像，没有已发布镜像地址。

## 初始化并启动

以普通用户操作，使镜像 UID/GID 与该用户一致，直接读取其私有密钥文件。不要以 root 运行模板，
也不要将密钥放宽成全局可读。密钥目录与数据卷分开保存。

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

`server-init` 只接受新目录，生成用途独立的 `master.key` 和 `http-token`，只显示路径，不显示内容。
已经初始化的实例跳过这一步；不覆盖或轮换原密钥。升级沿用同一 UID/GID、密钥目录和数据卷，
更换主密钥会令原加密数据无法解密。父目录原有文件和权限应保留。

可将 UID/GID 和目录路径保存到本地 `.env`（已被 Git 忽略），便于后续更新沿用；不要写入密钥或令牌内容。
主密钥和 HTTP 令牌只从宿主目录只读挂载，分别用于加密存储及 MCP 连接授权，不能互换，不能通过 MCP 或聊天传递。

## 连接自己的客户端

Compose 只发布 `127.0.0.1:8765`，MCP 地址为 `http://127.0.0.1:8765/mcp`。
容器内部监听全部接口是 Docker 端口映射所需，宿主发布仍限回环。
在自己的电脑建立并保持 SSH 转发：

```sh
ssh -N -L 8765:127.0.0.1:8765 用户@服务器
```

客户端通过其本地安全凭据设置提供独立 Bearer 令牌；不要把内容放进对话、仓库或命令参数。
使用私有 HTTPS 反向代理时，在 Compose 的 `command` 中保留 Dockerfile 全部启动参数并追加
`--public-url https://你的私有域名/mcp`。该选项只声明允许的 Host/Origin，不创建隧道或证书。

## 本人在容器终端完成认证

以下命令需要交互终端。敏感信息只在本人终端隐藏输入，不作为工具参数、标准输入管道、环境变量或 agent 配置。
不向 agent 提供回调地址、密码、动态码或令牌密钥。

### 对分易

```sh
docker compose exec -it stu-mcp stu-mcp login duifene
```

沿用原有微信授权和回调流程，按终端提示在微信内完成授权，再把回调粘贴到终端隐藏输入。
不需要容器图形桌面，也不需要对外发布签到网页端口。
CLI 不调用选课或 start、不新建监听计划；后台课程选择回显和已有仍有效的持续授权计划恢复沿用原规则。
登录不意味着用户新授权了自动签到。查看状态不会自行启动新的监听计划。

### WebVPN 自动重登

```sh
docker compose exec -it stu-mcp stu-mcp webvpn-auto configure
docker compose exec -it stu-mcp stu-mcp webvpn-auto status
docker compose exec -it stu-mcp stu-mcp webvpn-auto remove
```

`configure` 仅由本人隐藏输入学校账号、密码和**已经绑定的 TOTP 密钥或 otpauth 地址**。
这沿用原有按需自动重登能力，不在配置时验证登录、执行令牌绑定或识别验证码；保存会使旧 WebVPN 会话失效并清理旧 OA 缓存。
手机六位码不能代替长期 TOTP 密钥；单次登录可用 `docker compose exec -it stu-mcp stu-mcp login webvpn` 输入当前码，不必保存长期密钥。

受保护 OA 读取确需重新认证时才使用纯 HTTP 密码/TOTP。遇到 `randCode` 图形验证码、
首次令牌绑定或其他人工挑战应暂停，不反复提交凭据。`status` 只报告配置／失败状态，不显示凭据；
`remove` 关闭自动重登并移除保存的自动登录凭据。

### 教务、MySTU、雨课堂与报修

```sh
docker compose exec -it stu-mcp stu-mcp login mystu
docker compose exec -it stu-mcp stu-mcp login yuketang
docker compose exec -it stu-mcp stu-mcp login repair
docker compose exec -it stu-mcp stu-mcp login jw --allow-http-callback
```

账号密码隐藏输入；雨课堂官方二维码显示于该终端，由本人手机确认。设置页不是必需步骤，也不把二维码转发给 agent。

教务参数只允许本次官方 HTTP 票据回调。OA HTTP 8118 兼容需本人另行明确运行 `docker compose exec -it stu-mcp stu-mcp transport --oa-http on`，默认关闭；会话可能经明文 HTTP 传输，不能借用教务许可。两者均不允许密码/TOTP走 HTTP，不关闭证书校验。

报修独立会话保存在加密 Vault，草稿和确认只在进程内存；默认 HTTP 填写，完整预览、本轮明确确认、单次正式 POST 和回执核对规则仍全部适用。用法见[报修](repair.md)，协议及失败范围见[认证说明](authentication.md)。人工挑战会停止，不自动安装浏览器或桌面。

## 更新容器

容器内的 `stu-mcp update --check` 或 MCP `check_updates` 可以查询新版。
`stu-mcp update` / `update_self` 会提示在宿主重建，不在运行中的容器里安装覆盖代码。
目前没有公开镜像地址，不能用 `docker pull` 代替本地构建。

在宿主把模板源码更新到核对过的官方版本，沿用原 UID/GID、私密密钥目录、数据卷与端口设置，
再执行：

```sh
docker compose build
docker compose up -d
docker compose exec stu-mcp stu-mcp --version
```

重建会终止容器内的 MCP 和签到进程，先处理活动报修，未知提交结果只能只读核查。
容器启动后重新连接并调用 `get_capabilities` 核对运行版本；需要签到时再核实后台及已授权计划。
不要重新运行 `server-init` 或删除数据卷、密钥来更新。

## 数据与验证边界

- `stu-mcp-data` 数据卷分别持久保存 `campus` 和 `checkin`；密钥只读挂载在数据卷之外，备份时分别保护。
- MCP 客户端断开不停止容器或已授权签到后台。停止／重建整个容器会结束容器内进程；
  后台再次启动后的既有计划恢复规则不变，不因重新连接或登录创建新计划。
- 重启会丢失内存中的报修草稿和确认；提交结果不确定时先只读查单，不能据此重提。
- SSH/Tailscale 连接解决客户端到 MCP 的访问。学校 DNS、SSO 和来源请求发生在容器服务器；
  连接 MCP 成功不证明服务器能进入校园内网。不自动改 DNS、路由、代理或 TLS 校验。
- 已检查模板结构、端口／密钥隔离、真实 SDK 的回环交互及 HTTP 认证/业务的合成测试。
  CI 独立构建默认镜像，并在禁网容器中检查版本、核心导入、默认 HTTP、无 Playwright 及离线状态；结果见[发行验证](verification/2026-10-21-v0.6.0.md)。这不包含容器内学校认证或 SSH/Tailscale 跨机验收。
