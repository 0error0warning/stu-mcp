"use strict";
(() => {
  const token = location.hash.slice(1);
  const $ = id => document.getElementById(id);
  const NAMES = {school: "学校统一账号", jw: "教务系统", mystu: "MySTU", repair: "宿舍报修",
                 yuketang: "雨课堂", oa: "WebVPN"};
  const EXPIRED = new Set(["login_expired", "session_invalid", "session_changed"]);
  const SECRETS = ["vpn-user", "vpn-pass", "vpn-totp"];
  const rows = [...document.querySelectorAll(".row[data-service]")];

  let state = null;
  let watching = false;
  let pollTimer = null;
  let pollFailures = 0;
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
      const error = new Error(body.message || (response.status === 403
        ? "页面已失效，请重新运行 stu-mcp setup。" : "操作没有完成，请重试。"));
      error.httpStatus = response.status;
      error.status = body.status;
      if (body.status === "host_cli_required" && typeof body.command === "string"
          && /^stu-mcp login (school|jw|mystu|repair|yuketang|webvpn|duifene)$/.test(body.command)) {
        error.message += "\n" + body.command;
        $("login-command-text").textContent = body.command;
        $("login-command").hidden = false;
        $("jw-command-note").hidden = !["stu-mcp login school", "stu-mcp login jw"].includes(body.command);
        $("login-command").scrollIntoView({block: "nearest"});
      }
      throw error;
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
    const auth = id === "repair" ? state.repair?.auth?.status : source?.auth?.status;
    return {auth: auth || "needs_login", last: fresh ? fresh.status : null};
  }

  function renderCatalog() {
    const catalog = state.capability_catalog;
    const container = $("configuration-profiles");
    const gaps = $("unintegrated-services");
    container.replaceChildren();
    gaps.replaceChildren();
    if (!catalog) {
      container.append(el("p", "功能目录暂未读取，请检查运行中的 MCP 版本。", "hint"));
      return;
    }
    const loginIds = new Set(["school", "webvpn", "yuketang", "duifene"]);
    const serviceLabels = new Map(catalog.services.map(item => [item.service_id, item.label]));
    for (const profile of catalog.profiles) {
      const card = el("article", undefined, "card configuration");
      card.dataset.profile = profile.configuration_id;
      card.append(el("h3", profile.label));
      const features = el("ul");
      for (const feature of profile.features) {
        const label = profile.service_ids.length > 1 ? serviceLabels.get(feature.service_id) : null;
        features.append(el("li", label ? `${label}：${feature.label}` : feature.label));
      }
      card.append(features, el("p", profile.note, "note"),
                  el("p", profile.state.message, "profile-state"));
      if (loginIds.has(profile.configuration_id)) {
        const button = el("button", "查看登录命令", "act profile-button");
        button.type = "button";
        button.disabled = Boolean(runningJob());
        button.addEventListener("click", () => { closePanels(); login(profile.configuration_id); });
        card.append(button);
      } else if (profile.configuration_id === "takeout") {
        card.append(el("p", profile.setup_command, "note"));
      }
      if (profile.configuration_id === "school") {
        const list = el("ul", undefined, "profile-sessions");
        const names = {session_saved: "会话已保存，访问待核验", needs_login: "尚未登录",
                       login_expired: "会话已过期", session_invalid: "会话无法读取",
                       secure_storage_unavailable: "密钥库不可用"};
        for (const [id, item] of Object.entries(profile.state.services || {})) {
          const status = typeof item === "string" ? item : item.status;
          list.append(el("li", `${serviceLabels.get(id) || id}：${names[status] || "待核验"}`));
        }
        card.append(list);
      }
      container.append(card);
    }
    for (const service of catalog.services.filter(item => item.integration !== "implemented")) {
      const row = el("li");
      row.dataset.serviceId = service.service_id;
      row.append(el("strong", service.label + " · " +
        (service.integration === "navigation_only" ? "仅入口导航，业务未接入" : "业务未接入")));
      row.append(el("span", service.scope, "note"));
      gaps.append(row);
    }
  }

  // ---- accounts --------------------------------------------------------

  function oaView(job) {
    const mode = autoMode();
    const {auth, last} = sourceState("oa");
    if (job && job.service === "oa") return ["请在弹出的窗口中登录", "busy", "等待中"];
    if (mode === "enabled") return ["已保存账号，过期自动登录", "ok", "管理"];
    if (mode === "paused") return ["自动登录已暂停，需要更新账号", "warn", "更新"];
    if (mode === "broken") return ["保存的账号无法读取", "warn", "管理"];
    if (auth === "session_saved" && !EXPIRED.has(last)) return ["会话已保存，访问待核验", "ok", "管理"];
    if (auth === "session_saved" || EXPIRED.has(auth)) return ["登录已过期", "warn", "设置"];
    return [null, "", "设置"];
  }

  function accountView(id, job) {
    const {auth, last} = sourceState(id);
    if (job && job.service === id) {
      return [job.phase === "preparing_browser" ? "正在准备登录窗口…" : "请在弹出的窗口中登录", "busy", "等待中"];
    }
    if (auth === "session_saved" && !EXPIRED.has(last)) return ["会话已保存，访问待核验", "ok", "退出"];
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
    clearCredentials();
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
    else if (manual) note = "已保存登录会话。保存账号后可在过期时通过 HTTP 自动续期。";
    $("vpn-status").textContent = note;
    $("vpn-edit").textContent = mode === "none" ? "保存账号" : "更新账号";
    $("vpn-manage").hidden = !manage;
    $("vpn-form").hidden = manage;
    if (!manage) $("vpn-user").focus();
  }

  async function login(id, backend = "http") {
    try {
      await api("/api/login", {service: id, backend});
      watching = true;
      await load();
    } catch (error) {
      if (error.status === "host_cli_required") toast(error.message);
      else pollFailure(error);
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
    login("oa", "browser");
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
      clearCredentials();
      toast(error.message, true);
    } finally {
      data.username = data.password = data.totp = "";
      button.disabled = false;
    }
  });

  // ---- state -----------------------------------------------------------

  function pollFailure(error) {
    toast(error.message, true);
    if (watching && error.httpStatus !== 403 && ++pollFailures <= 5) schedulePoll();
  }

  function schedulePoll() {
    if (pollTimer) return;
    pollTimer = setTimeout(async () => {
      pollTimer = null;
      try { await load(); } catch (error) { pollFailure(error); }
    }, Math.min(12000, 1500 * 2 ** pollFailures));
  }

  async function load() {
    state = await api("/api/status");
    pollFailures = 0;
    $("version").textContent = state.version;
    renderRows();
    renderCatalog();
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
  window.addEventListener("focus", () => { if (state) load().catch(() => {}); });
  window.addEventListener("pagehide", clearCredentials);
  load().catch(error => toast(error.message, true));
})();
