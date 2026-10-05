"use strict";
(() => {
  const token = location.hash.slice(1);
  const $ = id => document.getElementById(id);
  const NAMES = {jw: "教务系统", mystu: "MySTU", yuketang: "雨课堂", oa: "WebVPN"};
  const SHORT = {"deepseek-harness": "DeepSeek Harness", "doubao-work": "豆包工作",
                 "generic": "其他 MCP 客户端", "generic-cli": "其他 agent"};
  const PRIMARY = ["claude-code", "codex", "cursor"];
  const EXPIRED = new Set(["login_expired", "session_invalid", "session_changed"]);
  const SECRETS = ["vpn-user", "vpn-pass", "vpn-totp"];
  const rows = [...document.querySelectorAll(".row[data-service]")];

  let state = null;
  let clients = [];
  let chosen = null;
  let showAll = false;
  let watching = false;
  let pollTimer = null;
  let toastTimer = null;
  let disarmTimer = null;

  for (const button of document.querySelectorAll(".act")) button.disabled = true;

  async function api(path, data) {
    const response = await fetch(path, {
      method: data === undefined ? "GET" : "POST",
      headers: {"X-STU-Setup": token, "Content-Type": "application/json"},
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    let body = {};
    try { body = await response.json(); } catch (_) { /* non-JSON error page */ }
    if (!response.ok || body.ok === false) {
      throw new Error(body.message || (response.status === 403
        ? "页面已失效，请重新运行 stu-mcp setup。" : "操作没有完成，请重试。"));
    }
    return body;
  }

  function toast(message, bad = false) {
    const node = $("toast");
    node.textContent = message;
    node.setAttribute("role", bad ? "alert" : "status");
    node.className = "toast show" + (bad ? " bad" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.className = "toast" + (bad ? " bad" : ""); }, bad ? 6000 : 3500);
  }

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  const runningJob = () => state.jobs.find(job => job.status === "running");
  // "disabled" means a removed or half-written config: treat it like none.
  const autoMode = () => {
    const status = state.webvpn_auto_login.status;
    if (status === "enabled" || status === "paused") return status;
    return status === "not_configured" || status === "disabled" ? "none" : "broken";
  };

  function sourceState(id) {
    const source = state.sources.find(item => item.source === id);
    const fresh = state.freshness.find(item => item.source === id);
    return {auth: source ? source.auth.status : "needs_login", last: fresh ? fresh.status : null};
  }

  // ---- accounts --------------------------------------------------------

  function oaView(job) {
    const mode = autoMode();
    const {auth, last} = sourceState("oa");
    if (job && job.service === "oa") return ["请在弹出的窗口中登录", "busy", "等待中"];
    if (mode === "enabled") return ["已保存账号，过期自动登录", "ok", "管理"];
    if (mode === "paused") return ["自动登录已暂停，需要更新账号", "warn", "更新"];
    if (mode === "broken") return ["保存的账号无法读取", "warn", "管理"];
    if (auth === "session_saved" && !EXPIRED.has(last)) return ["已登录", "ok", "管理"];
    if (auth === "session_saved" || EXPIRED.has(auth)) return ["登录已过期", "warn", "设置"];
    return [null, "", "设置"];
  }

  function accountView(id, job) {
    const {auth, last} = sourceState(id);
    if (job && job.service === id) {
      return [job.phase === "preparing_browser" ? "正在准备登录窗口…" : "请在弹出的窗口中登录", "busy", "等待中"];
    }
    if (auth === "session_saved" && !EXPIRED.has(last)) return ["已登录", "ok", "退出"];
    if (auth === "session_saved" || EXPIRED.has(auth)) return ["登录已过期", "warn", "重新登录"];
    if (auth === "secure_storage_unavailable") return ["无法访问系统钥匙串", "bad", "登录"];
    return [null, "", "登录"];
  }

  function renderRows() {
    const job = runningJob();
    for (const row of rows) {
      const id = row.dataset.service;
      const [text, tone, label] = id === "oa" ? oaView(job) : accountView(id, job);
      const meta = row.querySelector(".meta");
      const button = row.querySelector(".act");
      const open = button.getAttribute("aria-expanded") === "true";
      meta.textContent = text || row.dataset.desc;
      meta.className = "meta" + (tone ? " " + tone : "");
      button.textContent = open ? "取消" : label;
      // Accent means "needs you"; signed-in actions stay neutral.
      button.classList.toggle("quiet", open || label === "退出" || label === "管理");
      button.classList.toggle("out", !open && label === "退出");
      button.classList.toggle("wait", Boolean(job) && job.service === id);
      button.disabled = Boolean(job);
    }
  }

  function closePanels() {
    for (const panel of document.querySelectorAll(".panel")) panel.hidden = true;
    for (const button of document.querySelectorAll(".act[aria-controls]")) button.setAttribute("aria-expanded", "false");
    disarm();
    if (state) renderRows();
  }

  function openPanel(id) {
    const panel = $(id);
    const wasOpen = !panel.hidden;
    closePanels();
    if (wasOpen) return false;
    panel.hidden = false;
    document.querySelector(`[aria-controls="${id}"]`).setAttribute("aria-expanded", "true");
    renderRows();
    return true;
  }

  function showVpnPanel() {
    const mode = autoMode();
    const {auth, last} = sourceState("oa");
    const manual = auth === "session_saved" && !EXPIRED.has(last);
    const manage = mode !== "none" || manual;
    let note = "";
    if (mode === "enabled") note = "账号存在系统钥匙串里，会话过期时自动重新登录。";
    else if (mode === "paused") note = "上次自动登录没有成功，已暂停。请更新账号，或改用浏览器登录。";
    else if (mode === "broken") note = "保存的账号无法读取，请重新填写或断开。";
    else if (manual) note = "已通过浏览器登录，过期后需要再登录一次。保存账号后可以自动续期。";
    $("vpn-status").textContent = note;
    $("vpn-edit").textContent = mode === "none" ? "保存账号" : "更新账号";
    $("vpn-manage").hidden = !manage;
    $("vpn-form").hidden = manage;
    if (!manage) $("vpn-user").focus();
  }

  async function login(id) {
    try {
      await api("/api/login", {service: id});
      watching = true;
      await load();
    } catch (error) {
      toast(error.message, true);
    }
  }

  async function logout(id, message) {
    try {
      await api("/api/logout", {service: id});
      toast(message);
      closePanels();
      await load();
    } catch (error) {
      toast(error.message, true);
    }
  }

  for (const row of rows) {
    row.querySelector(".act").addEventListener("click", () => {
      const id = row.dataset.service;
      if (id === "oa") {
        if (openPanel("panel-oa")) showVpnPanel();
        return;
      }
      if (row.querySelector(".act").getAttribute("aria-expanded") === "true") {
        closePanels();
        return;
      }
      const {auth, last} = sourceState(id);
      if (auth === "session_saved" && !EXPIRED.has(last)) {
        logout(id, `已退出${NAMES[id]}`);
      } else if (id === "jw" && !state.transport.jw_http_compat) {
        openPanel("panel-jw");
      } else {
        closePanels();
        login(id);
      }
    });
  }

  $("jw-continue").addEventListener("click", async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api("/api/transport", {jw_http_compat: true});
      state.transport.jw_http_compat = true;
      closePanels();
      await login("jw");
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });

  $("vpn-edit").addEventListener("click", () => {
    $("vpn-manage").hidden = true;
    $("vpn-form").hidden = false;
    $("vpn-user").focus();
  });

  $("vpn-alt").addEventListener("click", () => {
    clearCredentials();
    closePanels();
    login("oa");
  });

  function disarm() {
    clearTimeout(disarmTimer);
    const button = $("vpn-logout");
    delete button.dataset.armed;
    button.textContent = "断开";
  }

  $("vpn-logout").addEventListener("click", event => {
    const button = event.currentTarget;
    if (!button.dataset.armed) {
      button.dataset.armed = "1";
      button.textContent = "确认断开？";
      disarmTimer = setTimeout(disarm, 4000);
      return;
    }
    disarm();
    logout("oa", "已断开 WebVPN，保存的账号已删除");
  });

  function clearCredentials() {
    for (const id of SECRETS) $(id).value = "";
  }

  $("vpn-form").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("vpn-save");
    const data = {enabled: true, username: $("vpn-user").value, password: $("vpn-pass").value,
                  totp: $("vpn-totp").value, encoding: "auto"};
    button.disabled = true;
    try {
      await api("/api/webvpn-auto", data);
      clearCredentials();
      toast("已保存，会话过期时会自动登录");
      closePanels();
      await load();
    } catch (error) {
      $("vpn-pass").value = "";
      $("vpn-totp").value = "";
      toast(error.message, true);
    } finally {
      data.username = data.password = data.totp = "";
      button.disabled = false;
    }
  });

  // ---- agent -----------------------------------------------------------

  const nameOf = spec => SHORT[spec.id] || spec.label;

  function renderClients() {
    const box = $("clients");
    box.replaceChildren();
    const detected = new Set(state.clients);
    const visible = showAll ? clients
      : clients.filter(c => PRIMARY.includes(c.id) || detected.has(c.id) || c.id === chosen);
    for (const spec of visible) {
      const chip = el("button", nameOf(spec), "chip");
      chip.type = "button";
      chip.setAttribute("aria-pressed", String(spec.id === chosen));
      if (detected.has(spec.id)) chip.title = "已在这台电脑上找到";
      chip.addEventListener("click", () => {
        chosen = spec.id;
        $("result").hidden = true;
        renderClients();
      });
      box.append(chip);
    }
    if (visible.length < clients.length) {
      const more = el("button", "更多", "chip more");
      more.type = "button";
      more.addEventListener("click", () => { showAll = true; renderClients(); });
      box.append(more);
    }
    const spec = clients.find(c => c.id === chosen);
    const connect = $("connect");
    connect.disabled = !spec;
    connect.textContent = !spec ? "选择一个客户端"
      : spec.mode === "skill" ? "生成技能包"
      : spec.mode === "export" ? "显示配置"
      : `添加到 ${nameOf(spec)}`;
  }

  function showResult(ok, title, detail, extra = []) {
    const box = $("result");
    box.className = "result " + (ok ? "ok" : "bad");
    box.replaceChildren(el("p", title));
    if (detail) box.append(el("p", detail));
    box.append(...extra);
    box.hidden = false;
  }

  function actionRow(label, handler) {
    const wrap = el("div", undefined, "actions");
    const button = el("button", label, "primary");
    button.type = "button";
    button.addEventListener("click", () => handler(button));
    wrap.append(button);
    return wrap;
  }

  async function downloadSkill(button) {
    button.disabled = true;
    try {
      const response = await fetch("/api/skill", {headers: {"X-STU-Setup": token}});
      if (!response.ok) throw new Error("技能包下载失败，请重新生成。");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "stu-campus.zip";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      toast(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  $("connect").addEventListener("click", async event => {
    const button = event.currentTarget;
    const spec = clients.find(c => c.id === chosen);
    if (!spec) return;
    button.disabled = true;
    $("result").hidden = true;
    try {
      const result = await api("/api/connect", {client: spec.id});
      if (result.status === "exported") {
        const text = JSON.stringify(result.config, null, 2);
        showResult(true, "把这段配置加到客户端的 MCP 设置里", result.next_step, [
          el("pre", text),
          actionRow("复制", () => navigator.clipboard.writeText(text)
            .then(() => toast("已复制"), () => toast("复制失败，请手动选择", true))),
        ]);
      } else if (result.status === "skill_exported") {
        showResult(true, "技能包已生成", result.next_step, [actionRow("下载技能包", downloadSkill)]);
      } else if (result.status === "already_connected") {
        showResult(true, `${nameOf(spec)} 已经接入`, result.next_step);
      } else {
        showResult(true, `已添加到 ${nameOf(spec)}`, result.next_step);
      }
    } catch (error) {
      showResult(false, "没有添加成功", error.message);
    } finally {
      button.disabled = false;
    }
  });

  // ---- state -----------------------------------------------------------

  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = setTimeout(async () => {
      pollTimer = null;
      try { await load(); } catch (error) { toast(error.message, true); }
    }, 1500);
  }

  async function load() {
    state = await api("/api/status");
    $("version").textContent = state.version;
    if (!clients.length) {
      clients = state.available_clients;
      chosen = clients.some(c => c.id === state.clients[0]) ? state.clients[0] : null;
    }
    renderRows();
    renderClients();
    if (runningJob()) {
      watching = true;
      schedulePoll();
    } else if (watching) {
      watching = false;
      const done = state.jobs.find(job => job.status === "finished");
      if (done) {
        const result = done.result || {};
        toast(result.ok ? `${NAMES[done.service]} 已登录` : result.message || "登录没有完成", !result.ok);
      }
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state) load().catch(() => {});
  });
  window.addEventListener("pagehide", clearCredentials);
  load().catch(error => toast(error.message, true));
})();
