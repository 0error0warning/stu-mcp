(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  let state = null;
  let online = false;
  let pending = false;
  let quitting = false;
  let timer = null;
  let toastTimer = null;
  let renderedEvents = "";
  let selectedCourses = new Set();
  let coursesSignature = "";
  let selectionDirty = false;
  let durationDirty = false;
  let selectionRevision = null;
  let showLogin = location.hash === "#login";
  const clock = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false});
  const shortClock = new Intl.DateTimeFormat("zh-CN", {timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", hour12: false});
  const time = value => value ? clock.format(new Date(value * 1000)) : "";

  function toast(text) {
    clearTimeout(toastTimer);
    $("toast").textContent = text;
    $("toast").classList.add("show");
    toastTimer = setTimeout(() => $("toast").classList.remove("show"), 4300);
  }

  async function api(path, data) {
    const abort = new AbortController();
    const timeout = setTimeout(() => abort.abort(), data ? 40000 : 8000);
    try {
      const response = await fetch(path, {
        method: data ? "POST" : "GET", credentials: "same-origin", cache: "no-store",
        headers: {"X-STU-Client": "local-ui", ...(data ? {"Content-Type": "application/json"} : {})},
        body: data ? JSON.stringify(data) : undefined, signal: abort.signal,
      });
      let result;
      try { result = await response.json(); } catch { throw new Error("本地服务暂时没有响应。"); }
      if (!response.ok || !result.ok) throw new Error(result.message || "操作未完成，请重试。");
      return result;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("连接超时，请重试。");
      if (error instanceof TypeError) throw new Error("服务已断开，请重新运行启动文件。");
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function accountPanel(show) {
    $("account-panel").hidden = !show;
    $("account-button").setAttribute("aria-expanded", String(show));
    if (!show) $("wechat-link").value = "";
  }

  function menu(show) {
    $("menu").hidden = !show;
    $("menu-button").setAttribute("aria-expanded", String(show));
  }

  function coursePanel(show) {
    $("course-list").hidden = !show;
    $("course-picker").setAttribute("aria-expanded", String(show));
  }

  function renderCourses(busy, connected, active) {
    const courses = state.courses || [];
    const signature = JSON.stringify([connected, courses]);
    const changed = signature !== coursesSignature;
    const externallyChanged = selectionRevision !== state.selection_revision;
    if (externallyChanged) {
      selectionRevision = state.selection_revision;
      durationDirty = false;
    }
    if (changed || externallyChanged || active || !selectionDirty) {
      const chosen = new Set(state.selected_courses || []);
      selectedCourses = new Set(courses.filter(course => chosen.has(course.id)).map(course => course.id));
      selectionDirty = false;
    }
    if (changed) {
      coursesSignature = signature;
      $("course-options").replaceChildren();
      for (const course of courses) {
        const row = document.createElement("label");
        row.className = "check-row";
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.value = course.id;
        const name = document.createElement("span");
        name.append(document.createTextNode(course.name));
        const error = document.createElement("small");
        error.hidden = true;
        name.append(error);
        row.append(checkbox, name);
        $("course-options").append(row);
      }
    }
    const locked = busy || !connected || active;
    $("course-picker").disabled = locked || !courses.length;
    $("all-courses").disabled = locked;
    $("all-courses").checked = courses.length > 0 && selectedCourses.size === courses.length;
    $("all-courses").indeterminate = selectedCourses.size > 0 && selectedCourses.size < courses.length;
    for (const row of $("course-options").children) {
      const checkbox = row.querySelector("input");
      checkbox.checked = selectedCourses.has(checkbox.value);
      checkbox.disabled = locked;
      const error = row.querySelector("small");
      error.textContent = state.course_statuses?.[checkbox.value]?.error || "";
      error.hidden = !error.textContent;
    }
    const selected = courses.filter(course => selectedCourses.has(course.id));
    $("course-summary").textContent = !connected ? "请先登录" : !courses.length ? "暂无课程" : !selected.length ? "请选择" : selected.length === 1 ? selected[0].name : selected.length === courses.length ? `全部 ${selected.length} 门` : `已选 ${selected.length} 门`;
    if (active || !durationDirty) $("duration").value = String(state.duration_minutes ?? 90);
    $("duration").disabled = busy || active;
    $("monitor-button").disabled = busy || !connected || !selected.length;
    if (active || !connected) coursePanel(false);
  }

  function renderEvents() {
    const events = (state.events || []).slice(-5).reverse();
    const signature = JSON.stringify(events);
    if (signature === renderedEvents) return;
    renderedEvents = signature;
    $("events").replaceChildren();
    $("records-section").hidden = events.length === 0;
    for (const event of events) {
      const row = document.createElement("li");
      row.className = "event";
      if (["success", "error", "warning"].includes(event.level)) row.classList.add(event.level);
      const timestamp = document.createElement("time");
      timestamp.textContent = shortClock.format(new Date(event.at * 1000));
      timestamp.dateTime = new Date(event.at * 1000).toISOString();
      const text = document.createElement("p");
      text.textContent = event.text;
      row.append(timestamp, text);
      $("events").append(row);
    }
  }

  function render() {
    if (!state) return;
    const busy = pending || state.busy || state.stopping || !online;
    const connected = Boolean(state.logged_in);
    const active = Boolean(state.monitoring && online);
    $("account-label").textContent = state.busy ? "恢复登录中" : state.auth_state === "unknown" ? "暂时无法验证" : connected ? "已登录" : "未登录";
    $("account-label").classList.toggle("connected", connected);
    $("account-button").textContent = connected ? "管理" : "登录";
    $("account-button").disabled = busy;
    $("connect-content").hidden = connected;
    $("connected-content").hidden = !connected;
    $("connect-button").disabled = busy;
    $("disconnect").disabled = busy;
    $("copy-link").disabled = busy;
    $("quit").disabled = pending || quitting;
    const failed = active ? Object.values(state.course_statuses || {}).filter(course => course.error).length : 0;
    const notice = !online ? quitting ? "服务已退出。" : "无法连接本地服务，请重新打开页面或启动文件。" : state.error || (failed ? `${failed} 门课程查询失败，正在重试。` : "");
    $("notice").hidden = !notice;
    $("notice").textContent = notice;

    renderCourses(busy, connected, active);
    $("monitor-button").classList.toggle("running", active);
    $("monitor-label").textContent = state.stopping ? "正在暂停" : pending ? "处理中" : active ? "暂停监听" : "开始监听";
    $("monitor-icon").hidden = pending;
    $("monitor-spinner").hidden = !pending;
    $("monitor-status").hidden = false;
    $("task-status").classList.toggle("active", active && state.status === "monitoring");
    const count = (state.selected_courses || []).length;
    $("task-label").textContent = !online ? quitting ? "服务未启动" : "查询异常" : state.status === "monitoring" ? state.cooldown_seconds > 0 ? "监听中 · 限流等待" : state.continuous ? `持续监听 · ${count} 门` : `监听中 · ${count} 门` : state.status_label;
    $("live-detail").hidden = !state.last_read_at && !state.last_confirmed_at;
    $("read-detail").hidden = !state.last_read_at;
    $("confirmed-detail").hidden = !state.last_confirmed_at;
    $("last-read").textContent = time(state.last_read_at);
    $("last-confirmed").textContent = time(state.last_confirmed_at);
    updateDeadline();
    renderEvents();
  }

  function updateDeadline() {
    if (state?.monitoring && online && state.until) {
      $("due-label").textContent = `${shortClock.format(new Date(state.until * 1000))} 自动暂停`;
    } else $("due-label").textContent = "";
  }

  function schedule() {
    clearTimeout(timer);
    if (quitting || document.hidden) return;
    timer = setTimeout(load, state?.monitoring || state?.busy || state?.stopping ? 2200 : online ? 7000 : 12000);
  }

  async function load() {
    try {
      state = await api("/api/state");
      online = true;
      render();
      if (showLogin && !state.busy) {
        showLogin = false;
        if (state.needs_login) accountPanel(true);
      }
    } catch (error) {
      const wasOnline = online;
      online = false;
      if (state) render();
      else {
        $("notice").hidden = false;
        $("notice").textContent = error.message;
      }
      if (wasOnline && !quitting) toast(error.message);
    } finally { schedule(); }
  }

  async function action(path, data, message) {
    if (pending) return false;
    pending = true;
    render();
    try {
      await api(path, data);
      if (message) toast(message);
      await load();
      return true;
    } catch (error) {
      toast(error.message);
      return false;
    } finally { pending = false; render(); }
  }

  $("menu-button").addEventListener("click", () => menu($("menu").hidden));
  document.addEventListener("click", event => { if (!event.target.closest(".menu-wrap")) menu(false); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") { menu(false); accountPanel(false); coursePanel(false); } });
  $("course-picker").addEventListener("click", () => coursePanel($("course-list").hidden));
  $("all-courses").addEventListener("change", event => {
    selectedCourses = new Set(event.target.checked ? (state.courses || []).map(course => course.id) : []);
    selectionDirty = true;
    render();
  });
  $("course-options").addEventListener("change", event => {
    if (event.target.type !== "checkbox") return;
    if (event.target.checked) selectedCourses.add(event.target.value);
    else selectedCourses.delete(event.target.value);
    selectionDirty = true;
    render();
  });
  $("duration").addEventListener("change", () => { durationDirty = true; });
  $("account-button").addEventListener("click", () => accountPanel($("account-panel").hidden));
  $("close-account").addEventListener("click", () => accountPanel(false));
  $("copy-link").addEventListener("click", async () => {
    if (!state?.auth_url) return;
    try {
      await navigator.clipboard.writeText(state.auth_url);
      toast("已复制，发到电脑微信的文件传输助手后点开");
      $("wechat-link").focus();
    } catch {
      $("public-link").hidden = false;
      $("public-link").value = state.auth_url;
      $("public-link").select();
      toast("请手动复制授权链接");
    }
  });
  $("connect-form").addEventListener("submit", async event => {
    event.preventDefault();
    let link = $("wechat-link").value.trim();
    $("wechat-link").value = "";
    const ok = await action("/api/connect", {link}, "登录成功");
    link = "";
    if (ok) accountPanel(false);
  });
  $("monitor-form").addEventListener("submit", async event => {
    event.preventDefault();
    if (!state?.logged_in) { accountPanel(true); return; }
    if (state.monitoring) await action("/api/pause", {}, "已暂停");
    else await action("/api/start", {course_ids: [...selectedCourses], minutes: Number($("duration").value)}, "已开始监听");
  });
  $("disconnect").addEventListener("click", async () => {
    if (await action("/api/disconnect", {}, "已退出登录")) accountPanel(false);
  });
  $("quit").addEventListener("click", async () => {
    menu(false);
    if (pending || !confirm("退出服务并停止监听？")) return;
    pending = true;
    render();
    try {
      await api("/api/quit", {});
      quitting = true;
      online = false;
      clearTimeout(timer);
    } catch (error) { toast(error.message); }
    finally { pending = false; render(); }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !quitting) load();
    else clearTimeout(timer);
  });
  window.addEventListener("pagehide", () => { $("wechat-link").value = ""; clearTimeout(timer); });
  load();
})();
