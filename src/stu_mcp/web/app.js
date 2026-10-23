"use strict";
(() => {
  const token = location.hash.slice(1);
  const $ = id => document.getElementById(id);
  const NAMES = {school: "学校统一账号", jw: "教务", mystu: "MySTU", repair: "宿舍报修",
                 yuketang: "雨课堂", webvpn: "WebVPN", oa: "WebVPN", duifene: "对分易"};
  const SECRET_FIELDS = ["login-user", "login-pass", "login-code", "login-callback", "vpn-user", "vpn-pass", "vpn-totp"];
  const FORMS = ["school-options", "credentials-form", "code-form", "qr-panel", "callback-form"];
  let state = null;
  let activeJobId = null;
  let activeService = null;
  let challenge = null;
  let renderedChallenge = null;
  let pollTimer = null;
  let pollFailures = 0;
  let toastTimer = null;
  let lastFinishedId = null;
  let starting = false;

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const runningJob = () => state?.jobs.find(job => job.status === "running");
  const sourceState = id => id === "repair" ? state?.repair?.auth?.status
    : state?.sources.find(source => source.source === (id === "webvpn" ? "oa" : id))?.auth?.status;
  const statusText = status => ({session_saved: "会话已保存", needs_login: "尚未登录", login_expired: "需要重新登录",
    session_invalid: "会话不可用", secure_storage_unavailable: "安全存储不可用"})[status] || "尚未核验";

  async function api(path, data, options = {}) {
    const response = await fetch(path, {
      method: data === undefined ? "GET" : "POST", keepalive: Boolean(options.keepalive),
      headers: {"X-STU-Setup": token, "Content-Type": "application/json"},
      body: data === undefined ? undefined : JSON.stringify(data),
    });
    let body = {};
    try { body = await response.json(); } catch (_) { /* bounded generic error below */ }
    if (!response.ok || body.ok === false) {
      const error = new Error(body.message || (response.status === 403
        ? "设置页已失效，请重新打开。" : "操作未完成，请重试。"));
      error.httpStatus = response.status;
      error.status = body.status;
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
    toastTimer = setTimeout(() => { node.className = "toast"; }, bad ? 6000 : 3500);
  }
  function clearCredentials() { for (const id of SECRET_FIELDS) $(id).value = ""; }
  function clearChallenge() {
    for (const id of FORMS) $(id).hidden = true;
    clearCredentials();
    $("login-qr").removeAttribute("src");
    $("callback-link").removeAttribute("href");
    challenge = null;
    renderedChallenge = null;
  }
  function errorMessage(message) {
    $("login-error").textContent = message || "";
    $("login-error").hidden = !message;
  }
  function panel(service) {
    activeService = service;
    $("login-title").textContent = NAMES[service] || "登录";
    $("login-panel").hidden = false;
    $("login-panel").scrollIntoView({block: "nearest", behavior: "smooth"});
  }

  function renderAccounts() {
    for (const button of document.querySelectorAll("[data-login]")) button.disabled = starting || Boolean(runningJob());
    const school = ["jw", "mystu", "repair"].map(id => `${NAMES[id]}：${statusText(sourceState(id))}`);
    $("school-state").textContent = school.join(" · ");
    $("yuketang-state").textContent = statusText(sourceState("yuketang"));
    $("webvpn-state").textContent = statusText(sourceState("webvpn"));
    const checkin = state.checkin;
    $("duifene-state").textContent = checkin?.logged_in ? "会话已保存" :
      checkin?.status === "service_not_started" ? "服务尚未启动" : checkin?.status === "not_logged_in" ? "尚未登录" : "按需授权";
    const sessions = $("school-sessions");
    sessions.replaceChildren();
    for (const id of ["jw", "mystu", "repair", "yuketang", "webvpn"]) {
      const row = el("div", undefined, "session-row");
      row.append(el("span", `${NAMES[id]} · ${statusText(sourceState(id))}`));
      const login = el("button", "重新登录", "ghost");
      login.type = "button";
      login.disabled = starting || Boolean(runningJob());
      login.addEventListener("click", () => choose(id, true));
      row.append(login);
      if (sourceState(id) === "session_saved") {
        const out = el("button", "退出", "ghost danger");
        out.type = "button";
        out.addEventListener("click", async () => {
          out.disabled = true;
          try { await api("/api/logout", {service: id === "webvpn" ? "oa" : id}); await load(); }
          catch (error) { toast(error.message, true); out.disabled = false; }
        });
        row.append(out);
      }
      sessions.append(row);
    }
  }

  function renderCatalog() {
    const catalog = state.capability_catalog;
    const details = $("capability-details");
    const gaps = $("unintegrated-services");
    details.replaceChildren();
    gaps.replaceChildren();
    if (!catalog) return;
    for (const service of catalog.services.filter(item => item.integration === "implemented")) {
      details.append(el("p", `${service.label}：${service.scope}`));
    }
    gaps.append(el("li", "以下服务尚无业务接入，配置同类账号也不会启用。", "note"));
    for (const service of catalog.services.filter(item => item.integration !== "implemented")) {
      const item = el("li", `${service.label} · ${service.integration === "navigation_only" ? "仅入口导航" : "未接入"}`);
      item.dataset.serviceId = service.service_id;
      gaps.append(item);
    }
  }

  function renderResults(results) {
    $("login-results").replaceChildren();
    for (const item of results || []) {
      const label = item.ok ? item.skipped ? "保留已有会话" : "会话已保存"
        : item.status === "not_attempted" ? "本次未继续" : "未完成";
      const row = el("li", `${NAMES[item.service] || item.service || "登录"}：${label}`, item.ok ? "ok" : "warn");
      if (!item.ok && item.message) row.append(el("span", item.message, "result-message"));
      $("login-results").append(row);
    }
  }

  function renderJob(job) {
    if (!job) return;
    const showPanel = activeJobId !== job.id || $("login-panel").hidden;
    activeJobId = job.id;
    if (showPanel) panel(job.service);
    if (job.status === "finished") {
      activeJobId = null;
      clearChallenge();
      const result = job.result || {};
      renderResults(result.results || job.results || (result.ok ? [{...result, service: job.service}] : []));
      $("login-status").textContent = result.ok ? "配置完成，可以返回 Agent 使用。"
        : result.status === "school_login_partial" ? "部分业务未完成，请查看各项结果。"
        : result.status === "operation_cancelled" ? "已停止后续认证，已完成的会话保留。" : "本次配置未完成。";
      errorMessage(result.ok || result.status === "operation_cancelled" ? null : result.message || result.group_error?.message);
      $("login-cancel").textContent = "关闭";
      if (lastFinishedId !== job.id) {
        lastFinishedId = job.id;
        if (result.ok) toast("配置完成");
      }
      return;
    }
    renderResults(job.results);
    $("login-cancel").textContent = "取消";
    const next = job.challenge;
    if (!next) {
      clearChallenge();
      $("login-status").textContent = job.phase === "cancelling" ? "正在停止后续认证，已完成的会话保留。"
        : job.phase === "callback_submitted" ? "正在核对授权结果，请勿重复提交。" : "正在认证，请稍候…";
      return;
    }
    if (renderedChallenge === next.id) return;
    clearChallenge();
    renderedChallenge = next.id;
    challenge = next;
    errorMessage(null);
    if (next.kind === "credentials") {
      $("login-status").textContent = "输入账号和密码";
      $("credentials-form").hidden = false;
      $("login-user").focus();
    } else if (next.kind === "code") {
      $("login-status").textContent = "输入令牌当前显示的动态口令";
      $("code-form").hidden = false;
      $("login-code").focus();
    } else if (next.kind === "qr") {
      $("login-status").textContent = "等待手机确认";
      if (typeof next.image === "string" && /^data:image\/(svg\+xml|png);base64,[A-Za-z0-9+/=]+$/.test(next.image)) {
        $("login-qr").src = next.image;
        $("qr-panel").hidden = false;
      } else errorMessage("二维码暂时无法显示，请取消后重试。");
    } else if (next.kind === "callback") {
      $("login-status").textContent = "完成微信授权";
      const url = next.authorization_url;
      if (typeof url === "string" && url.startsWith("https://open.weixin.qq.com/connect/oauth2/authorize?")) {
        $("callback-link").href = url;
        $("callback-form").hidden = false;
        $("login-callback").focus();
      } else errorMessage("授权入口暂时无法显示，请取消后重试。");
    }
  }

  async function begin(service, options = {}) {
    if (starting || runningJob()) return;
    starting = true;
    clearChallenge();
    errorMessage(null);
    renderResults([]);
    panel(service);
    $("login-status").textContent = "正在准备登录…";
    renderAccounts();
    try {
      const result = await api("/api/login", {service, backend: "http", ...options});
      activeJobId = result.id;
      pollFailures = 0;
      await load();
    } catch (error) {
      errorMessage(error.message);
      if (error.httpStatus !== 403) {
        // The task may exist even if its start response was lost. Read, never repost.
        try { await load(); } catch (_) { /* keep the original error visible */ }
      }
    }
    finally { starting = false; if (state) renderAccounts(); }
  }

  function choose(service, reauthenticate = false) {
    if (runningJob() || starting) return;
    clearChallenge();
    clearCredentials();
    $("panel-oa").hidden = true;
    errorMessage(null);
    renderResults([]);
    if (service === "school" || service === "jw") {
      panel(service);
      $("login-status").textContent = "选择本次要连接的业务";
      $("school-options").hidden = false;
      $("school-options").dataset.reauthenticate = String(reauthenticate);
      for (const input of document.querySelectorAll('input[name="services"]')) {
        input.checked = service === "school" || input.value === "jw";
        input.disabled = service !== "school";
      }
      $("school-http").checked = false;
      const existing = Boolean(state.transport.jw_http_compat);
      $("school-http-choice").hidden = existing;
      $("school-http-note").hidden = existing;
    } else begin(service);
  }
  for (const button of document.querySelectorAll("[data-login]")) {
    button.disabled = true;
    button.addEventListener("click", () => choose(button.dataset.login));
  }
  $("school-options").addEventListener("submit", event => {
    event.preventDefault();
    const services = [...document.querySelectorAll('input[name="services"]:checked')].map(input => input.value);
    if (!services.length) return errorMessage("请至少选择一项业务。");
    if (services.includes("jw") && !state.transport.jw_http_compat && !$("school-http").checked) {
      return errorMessage("连接教务需允许本次官方 HTTP 回调；也可以取消勾选教务。");
    }
    const options = {};
    if (activeService === "school") {
      options.services = services;
      options.reauthenticate = $("school-options").dataset.reauthenticate === "true";
    }
    if (services.includes("jw") && $("school-http").checked) options.allow_http_callback = true;
    begin(activeService, options);
  });

  async function submitInput(fields, form) {
    if (!activeJobId || !challenge) return;
    const data = {id: activeJobId, challenge_id: challenge.id, ...fields};
    const buttons = [...form.querySelectorAll("button")];
    buttons.forEach(button => { button.disabled = true; });
    clearCredentials();
    try {
      await api("/api/login/input", data);
      clearChallenge();
      $("login-status").textContent = "正在认证，请稍候…";
      await load();
    } catch (error) {
      errorMessage(error.message);
      if (error.httpStatus !== 403) {
        // A consumed prompt must not cause credentials or callbacks to be sent twice.
        try { await load(); } catch (_) { /* bounded status polling may recover */ }
      }
    }
    finally {
      for (const field of Object.keys(fields)) { fields[field] = ""; data[field] = ""; }
      buttons.forEach(button => { button.disabled = false; });
    }
  }
  $("credentials-form").addEventListener("submit", event => {
    event.preventDefault();
    submitInput({username: $("login-user").value, password: $("login-pass").value}, event.currentTarget);
  });
  $("code-form").addEventListener("submit", event => {
    event.preventDefault(); submitInput({code: $("login-code").value}, event.currentTarget);
  });
  $("callback-form").addEventListener("submit", event => {
    event.preventDefault(); submitInput({callback: $("login-callback").value}, event.currentTarget);
  });
  $("login-cancel").addEventListener("click", async () => {
    clearChallenge();
    if (activeJobId) {
      try { await api("/api/login/cancel", {id: activeJobId}); await load(); }
      catch (error) { errorMessage(error.message); }
    } else { $("login-panel").hidden = true; activeService = null; }
  });

  $("vpn-auto-open").addEventListener("click", () => {
    const open = $("panel-oa").hidden;
    clearCredentials();
    $("panel-oa").hidden = !open;
    const mode = state.webvpn_auto_login.status;
    $("vpn-status").textContent = mode === "enabled" ? "自动重登已启用" : mode === "paused" ? "自动重登已暂停" : "按需开启自动重登";
  });
  $("vpn-cancel").addEventListener("click", () => { clearCredentials(); $("panel-oa").hidden = true; });
  $("cli-open").addEventListener("click", () => { $("cli-panel").hidden = !$("cli-panel").hidden; });
  $("vpn-form").addEventListener("submit", async event => {
    event.preventDefault();
    const data = {enabled: true, username: $("vpn-user").value, password: $("vpn-pass").value,
                  totp: $("vpn-totp").value, encoding: "auto"};
    $("vpn-save").disabled = true;
    clearCredentials();
    try { await api("/api/webvpn-auto", data); $("panel-oa").hidden = true; toast("自动重登配置已保存"); await load(); }
    catch (error) { toast(error.message, true); }
    finally { data.username = data.password = data.totp = ""; $("vpn-save").disabled = false; }
  });
  $("vpn-logout").addEventListener("click", async () => {
    clearCredentials();
    try { await api("/api/logout", {service: "oa"}); $("panel-oa").hidden = true; await load(); toast("已断开 WebVPN"); }
    catch (error) { toast(error.message, true); }
  });

  function schedulePoll() {
    if (pollTimer || document.hidden) return;
    pollTimer = setTimeout(async () => {
      pollTimer = null;
      try { await load(); } catch (error) { pollFailure(error); }
    }, Math.min(12000, 1500 * 2 ** pollFailures));
  }
  function pollFailure(error) {
    if (error.httpStatus === 403) { clearChallenge(); errorMessage(error.message); return; }
    if (++pollFailures <= 5) schedulePoll();
    else { clearChallenge(); errorMessage("暂时无法读取登录进度，请重新打开页面核对，先不要重复登录。"); }
  }
  async function load() {
    state = await api("/api/status");
    pollFailures = 0;
    $("version").textContent = state.version;
    renderAccounts();
    renderCatalog();
    const job = runningJob() || state.jobs.find(item => item.id === activeJobId);
    if (job) renderJob(job);
    if (runningJob()) schedulePoll();
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && state) load().catch(pollFailure); });
  window.addEventListener("focus", () => { if (state) load().catch(pollFailure); });
  window.addEventListener("pagehide", () => {
    clearCredentials();
    $("login-qr").removeAttribute("src");
    if (activeJobId) api("/api/login/cancel", {id: activeJobId}, {keepalive: true}).catch(() => {});
  });
  load().catch(error => toast(error.message, true));
})();
