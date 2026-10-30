"use strict";
(() => {
  const token = location.hash.slice(1);
  const $ = id => document.getElementById(id);
  const SECRET_FIELDS = ["login-user", "login-pass", "login-token", "login-code", "login-callback", "login-captcha"];
  const FORMS = ["credentials-form", "code-form", "qr-panel", "callback-form", "captcha-form"];
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
  let disconnecting = false;
  let pendingStart = null;

  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const runningJob = () => state?.jobs.find(job => job.status === "running");
  const profiles = () => state?.capability_catalog?.profiles || [];
  const profile = id => profiles().find(item => item.configuration_id === id);
  const services = id => (state?.capability_catalog?.services || []).filter(item =>
    profile(id)?.service_ids.includes(item.service_id));
  const configured = id => ["session_saved", "sessions_saved"].includes(profile(id)?.state.status);
  const hasLogin = id => Object.values(profile(id)?.state.services || {}).some(item =>
    ["session_saved", "login_expired", "session_invalid"].includes(item.status))
    || id === "webvpn" && state?.webvpn_auto_login?.configured;
  const editVPN = () => ["paused", "disabled"].includes(state?.webvpn_auto_login?.status);
  const featureText = id => id === "school" ? services(id).map(item => item.label).join(" · ")
    : (profile(id)?.features || []).map(item => item.label).join(" · ");
  const statusText = status => ({session_saved: "已配置", sessions_saved: "已配置", needs_login: "未配置",
    partially_configured: "部分功能需要登录", login_expired: "需要重新登录", session_invalid: "需要重新登录",
    secure_storage_unavailable: "无法保存登录信息"})[status] || "暂时无法读取配置";

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
    $("login-captcha-image").removeAttribute("src");
    $("callback-link").removeAttribute("href");
    $("token-field").hidden = true;
    challenge = null;
    renderedChallenge = null;
  }
  function errorMessage(message) {
    $("login-error").textContent = message || "";
    $("login-error").hidden = !message;
  }
  function panel(service) {
    activeService = service;
    $("login-title").textContent = profile(service)?.label || "登录";
    $("login-panel").hidden = false;
    $("login-panel").scrollIntoView({block: "nearest", behavior: "smooth"});
  }

  function renderAccounts() {
    const busy = starting || disconnecting || Boolean(pendingStart) || Boolean(runningJob());
    for (const button of document.querySelectorAll("[data-login]")) {
      const id = button.dataset.login;
      const current = profile(id);
      button.disabled = busy || !current;
      $(id + "-features").textContent = featureText(id);
      let status = statusText(current?.state.status);
      let action = configured(id) ? "重新登录" : "配置";
      if (id === "school" && current?.state.status === "partially_configured") action = "继续配置";
      if (id === "yuketang") action = configured(id) ? "重新扫码" : "扫码登录";
      if (id === "duifene") {
        status = state.checkin?.logged_in === true ? "已配置" : state.checkin?.logged_in === false ? "未授权"
          : state.checkin?.status === "service_not_started" ? "尚未连接" : "暂时无法读取配置";
        action = state.checkin?.logged_in ? "重新授权" : "授权";
      }
      if (id === "webvpn") {
        const auto = state.webvpn_auto_login;
        if (auto?.configured) {
          status = editVPN() ? "自动登录未开启，请更新配置"
            : configured(id) ? "已配置 · 自动登录已开启" : "已保存令牌，可自动登录";
          action = configured(id) || editVPN() ? "更新配置" : "连接";
        }
      }
      $(id + "-state").textContent = status;
      button.textContent = action;
    }
    for (const button of document.querySelectorAll("[data-logout]")) {
      button.hidden = !hasLogin(button.dataset.logout);
      button.disabled = busy;
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
    $("cli-commands").textContent = profiles().filter(item => item.setup_ui.available)
      .map(item => item.setup_command).join("\n");
  }

  function renderResults(results) {
    $("login-results").replaceChildren();
    for (const item of (results || []).filter(item => !item.ok)) {
      const service = services(activeService).find(entry => entry.login_id === item.service);
      const label = service?.label || profile(activeService)?.label || "登录";
      const row = el("li", `${label}：${item.status === "not_attempted" ? "暂未连接" : "未完成"}`, "warn");
      if (item.message) row.append(el("span", item.message, "result-message"));
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
      const results = result.results || job.results || [];
      renderResults(results);
      $("login-status").textContent = result.ok ? "配置完成，可以返回 Agent 使用。"
        : result.status === "school_login_partial" ? "部分功能已配置，以下项目暂未完成。"
        : result.status === "operation_cancelled" ? "已取消，已完成的配置保留。" : "本次配置未完成。";
      const successful = services(job.service).filter(service => results.some(item =>
        item.ok && item.service === service.login_id));
      $("login-features").textContent = result.ok ? "已配置功能：" + featureText(job.service)
        : successful.length ? "已配置功能：" + successful.map(item => item.label).join(" · ") : "";
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
      $("login-status").textContent = job.phase === "cancelling" ? "正在取消…"
        : job.phase === "callback_submitted" ? "正在核对授权结果，请勿重复提交。" : "正在认证，请稍候…";
      return;
    }
    if (renderedChallenge === next.id) return;
    clearChallenge();
    renderedChallenge = next.id;
    challenge = next;
    errorMessage(null);
    if (next.kind === "credentials" || next.kind === "webvpn_credentials") {
      $("login-status").textContent = job.service === "school" ? "一次登录，连接已接入的学校服务。"
        : job.service === "med_jw" ? "请填写医学院教务本地口令，可能与医学院统一认证密码不同。"
        : job.service === "smartcard" ? "此站使用普通连接，请填写独立的一卡通查询密码。" : "";
      $("login-user-label").textContent = job.service === "smartcard" ? "学（工）号" : "学校账号";
      $("login-pass-label").textContent = job.service === "smartcard" ? "一卡通查询密码"
        : job.service === "med_jw" ? "医学院教务本地口令" : "密码";
      $("token-field").hidden = next.kind !== "webvpn_credentials";
      $("login-submit").textContent = "登录";
      $("credentials-form").hidden = false;
      $("login-user").focus();
    } else if (next.kind === "captcha") {
      $("login-status").textContent = "输入图片中的验证码";
      const medical = job.service === "med_jw";
      $("captcha-label").textContent = medical ? "图片中的字母和数字" : "图片中的四位数字";
      $("login-captcha").inputMode = medical ? "text" : "numeric";
      $("login-captcha").pattern = medical ? "[A-Za-z0-9]{4,5}" : "[0-9]{4}";
      $("login-captcha").maxLength = medical ? 5 : 4;
      if (typeof next.image === "string" && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(next.image)) {
        $("login-captcha-image").src = next.image;
        $("captcha-form").hidden = false;
        $("login-captcha").focus();
      } else errorMessage("验证码暂时无法显示，请取消后重试。");
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
    if (starting || disconnecting || pendingStart || runningJob()) return;
    starting = true;
    clearTimeout(toastTimer);
    $("toast").className = "toast";
    pendingStart = {service, previousIds: new Set(state.jobs.map(job => job.id))};
    clearChallenge();
    errorMessage(null);
    renderResults([]);
    $("login-features").textContent = "";
    panel(service);
    $("login-status").textContent = "正在准备登录…";
    renderAccounts();
    try {
      const result = await api("/api/login", {service, ...options});
      activeJobId = result.id;
      pendingStart = null;
      pollFailures = 0;
      await load();
    } catch (error) {
      if (error.httpStatus && error.httpStatus < 500) pendingStart = null;
      errorMessage(error.message);
      if (error.httpStatus !== 403) {
        // The task may exist even if its start response was lost. Read, never repost.
        try { await load(); } catch (_) { /* keep the original error visible */ }
      }
      if (pendingStart) errorMessage("暂时无法核实登录是否启动，请重新打开页面查看，先不要重复登录。");
    }
    finally { starting = false; if (state) renderAccounts(); }
  }

  for (const button of document.querySelectorAll("[data-login]")) {
    button.disabled = true;
    button.addEventListener("click", () => {
      const service = button.dataset.login;
      const reauthenticate = ["school", "webvpn"].includes(service) &&
        (configured(service) || service === "webvpn" && editVPN());
      begin(service, reauthenticate ? {reauthenticate: true} : {});
    });
  }

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
    const fields = {username: $("login-user").value, password: $("login-pass").value};
    if (challenge?.kind === "webvpn_credentials") fields.totp = $("login-token").value;
    submitInput(fields, event.currentTarget);
  });
  $("login-token").addEventListener("input", () => {
    $("login-submit").textContent = $("login-token").value.trim() ? "保存并登录" : "登录";
  });
  $("code-form").addEventListener("submit", event => {
    event.preventDefault(); submitInput({code: $("login-code").value}, event.currentTarget);
  });
  $("captcha-form").addEventListener("submit", event => {
    event.preventDefault(); submitInput({code: $("login-captcha").value}, event.currentTarget);
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

  for (const button of document.querySelectorAll("[data-logout]")) {
    button.addEventListener("click", async () => {
      if (starting || disconnecting || pendingStart || runningJob()) return;
      disconnecting = true;
      clearChallenge();
      renderAccounts();
      try {
        await api("/api/logout", {service: button.dataset.logout});
        $("login-panel").hidden = true;
        await load();
        toast("已退出账号");
      } catch (error) {
        toast(error.message, true);
        if (error.httpStatus !== 403) {
          try { await load(); } catch (_) { /* never repeat a possibly completed logout */ }
        }
      }
      finally { disconnecting = false; if (state) renderAccounts(); }
    });
  }

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
    const recovered = pendingStart && state.jobs.find(item => item.service === pendingStart.service
      && !pendingStart.previousIds.has(item.id));
    if (recovered) { activeJobId = recovered.id; pendingStart = null; }
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
    $("login-captcha-image").removeAttribute("src");
    if (activeJobId) api("/api/login/cancel", {id: activeJobId}, {keepalive: true}).catch(() => {});
  });
  load().catch(error => toast(error.message, true));
})();
