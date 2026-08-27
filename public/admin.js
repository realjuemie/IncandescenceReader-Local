"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  setupRequired: false,
  accounts: [],
  members: [],
  sessions: [],
  settings: null,
  health: null,
  toastTimer: null,
  inspectTimer: null,
  pollingStarted: false,
};

async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (options.body && typeof options.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) {
    if (response.status === 401 && !path.endsWith("/login")) showAuth(false);
    throw new Error(payload.error || `请求失败 (${response.status})`);
  }
  return payload;
}

async function initialize() {
  bindEvents();
  try {
    const status = await api("/api/admin/status");
    state.setupRequired = status.setupRequired;
    if (status.authenticated) await enterDashboard();
    else showAuth(status.setupRequired);
  } catch (error) {
    showAuth(false);
    showAuthError(error.message);
  }
}

function bindEvents() {
  $("#auth-form").addEventListener("submit", authenticate);
  $("#logout").addEventListener("click", logout);
  $("#session-cookies").addEventListener("input", () => {
    clearTimeout(state.inspectTimer);
    state.inspectTimer = setTimeout(inspectCookies, 320);
  });
  $("#add-session").addEventListener("click", addSession);
  $("#session-list").addEventListener("click", handleSessionAction);
  $("#add-account-form").addEventListener("submit", addAccount);
  $("#admin-account-list").addEventListener("click", handleAccountAction);
  $("#sync-failure-list").addEventListener("click", handleAccountAction);
  $("#add-member-form").addEventListener("submit", addMember);
  $("#admin-member-list").addEventListener("click", handleMemberAction);
  $("#save-settings").addEventListener("click", saveSettings);
  $("#save-proxy").addEventListener("click", saveProxy);
  $("#test-proxy").addEventListener("click", testProxy);
  $("#save-bark").addEventListener("click", saveBark);
  $("#test-bark").addEventListener("click", testBark);
  $("#clear-bark-key").addEventListener("click", clearBarkKey);
  $("#sync-all").addEventListener("click", syncAll);
}

function showAuth(setupRequired) {
  state.setupRequired = Boolean(setupRequired);
  $("#admin-app").hidden = true;
  $("#auth-view").hidden = false;
  $("#auth-title").textContent = state.setupRequired ? "设置管理员密码" : "管理员登录";
  $("#auth-description").textContent = state.setupRequired
    ? "这是首次启动。请创建一个仅用于本站管理后台的密码。"
    : "登录后管理抓取凭证、阅读账号和自动更新。";
  $("#auth-submit").textContent = state.setupRequired ? "创建密码并进入后台" : "登录";
  $("#confirm-password-row").hidden = !state.setupRequired;
  $("#admin-password").autocomplete = state.setupRequired ? "new-password" : "current-password";
  $("#admin-password").value = "";
  $("#admin-password-confirm").value = "";
  showAuthError("");
}

async function authenticate(event) {
  event.preventDefault();
  const password = $("#admin-password").value;
  if (state.setupRequired && password !== $("#admin-password-confirm").value) {
    showAuthError("两次输入的密码不一致");
    return;
  }
  const button = $("#auth-submit");
  button.disabled = true;
  showAuthError("");
  try {
    const endpoint = state.setupRequired ? "/api/admin/setup" : "/api/admin/login";
    await api(endpoint, { method: "POST", body: { password } });
    await enterDashboard();
  } catch (error) {
    showAuthError(error.message);
  } finally {
    button.disabled = false;
  }
}

async function enterDashboard() {
  await loadDashboard();
  $("#auth-view").hidden = true;
  $("#admin-app").hidden = false;
  if (!state.pollingStarted) {
    state.pollingStarted = true;
    window.setInterval(refreshStatus, 12000);
  }
}

async function logout() {
  try { await api("/api/admin/logout", { method: "POST", body: {} }); }
  finally { showAuth(false); }
}

async function loadDashboard() {
  const [accounts, sessions, settings, health, members] = await Promise.all([
    api("/api/admin/accounts"),
    api("/api/admin/scraper-sessions"),
    api("/api/admin/settings"),
    api("/api/admin/health"),
    api("/api/admin/members"),
  ]);
  state.accounts = accounts.items;
  state.sessions = sessions.items;
  state.settings = settings;
  state.health = health;
  state.members = members.items;
  renderDashboard();
}

function renderDashboard() {
  renderStats();
  renderSyncFailures();
  renderSessions();
  renderAccounts();
  renderMembers();
  fillSettings();
}

function describeSyncError(value) {
  const detail = String(value || "同步失败").trim() || "同步失败";
  let summary = detail;
  if (/rate.?limit|too many requests|\b429\b/i.test(detail)) {
    summary = "X 请求频率受限，请稍后再试";
  } else if (/timeout|timed out/i.test(detail)) {
    summary = "连接 X 超时，请检查网络或代理";
  } else if (/no active accounts|cookie|unauthori[sz]ed|forbidden|\b401\b|\b403\b/i.test(detail)) {
    summary = "抓取凭证不可用或已经失效";
  } else if (/not found|does not exist|could not find user/i.test(detail)) {
    summary = "X 账号不存在、已改名或暂时无法找到";
  } else if (/protected|private account/i.test(detail)) {
    summary = "该账号受保护，当前凭证无权读取";
  } else if (/proxy|connection refused|connection reset|network|dns/i.test(detail)) {
    summary = "网络或代理连接失败";
  }
  return { summary, detail: summary === detail ? "" : detail };
}

function renderSyncFailures() {
  const panel = $("#sync-failure-panel");
  const list = $("#sync-failure-list");
  const failures = state.accounts.filter((account) => account.lastError);
  panel.hidden = failures.length === 0;
  list.replaceChildren();
  if (!failures.length) return;
  $("#sync-failure-count").textContent = `${failures.length} 个账号需要处理`;
  for (const account of failures) {
    const item = document.createElement("article");
    item.className = "sync-failure-item";
    const marker = document.createElement("div");
    marker.className = "sync-failure-marker";
    marker.textContent = "!";
    const copy = document.createElement("div");
    copy.className = "sync-failure-copy";
    const title = document.createElement("strong");
    title.textContent = `${account.displayName}  @${account.username}`;
    const issue = describeSyncError(account.lastError);
    const reason = document.createElement("p");
    reason.textContent = issue.summary;
    const time = document.createElement("small");
    time.textContent = account.lastFailedAt
      ? `失败于 ${relativeTime(account.lastFailedAt)} · ${new Date(account.lastFailedAt).toLocaleString("zh-CN")}`
      : "失败时间未知";
    copy.append(title, reason);
    if (issue.detail) {
      const technical = document.createElement("code");
      technical.textContent = `技术信息：${issue.detail}`;
      copy.append(technical);
    }
    copy.append(time);
    const retry = actionButton("重新更新", "sync-account", account.id);
    retry.className = "secondary-button sync-failure-retry";
    item.append(marker, copy, retry);
    list.append(item);
  }
}

function renderStats() {
  const scraper = state.health?.scraper || {};
  const scheduler = state.health?.scheduler || {};
  const sync = state.health?.sync || {};
  const publicAccounts = state.accounts.filter((item) => item.isPublic).length;
  $("#stat-accounts").textContent = String(publicAccounts);
  $("#stat-account-total").textContent = `共 ${state.accounts.length} 个 · ${state.members.length} 个会员`;
  $("#stat-sessions").textContent = String(scraper.activeSessions || 0);
  $("#stat-scraper-version").textContent = scraper.installed ? `twscrape v${scraper.version}` : "组件未安装";
  $("#stat-schedule").textContent = state.settings?.scheduleEnabled ? `${state.settings.scheduleMinutes} 分钟` : "未开启";
  $("#stat-next-run").textContent = scheduler.nextRunAt ? `下次 ${relativeTime(scheduler.nextRunAt)}` : "暂无计划";
  $("#stat-sync").textContent = sync.running ? "运行中" : "空闲";
  const last = scheduler.lastResult;
  $("#stat-last-result").textContent = last ? `上次成功 ${last.succeeded || 0} / 失败 ${last.failed || 0}` : "无任务";
  const healthPill = $("#scraper-health");
  if (!scraper.installed) {
    healthPill.textContent = "组件未安装";
    healthPill.className = "pill bad";
  } else if (!scraper.activeSessions) {
    healthPill.textContent = `v${scraper.version} · 无有效凭证`;
    healthPill.className = "pill bad";
  } else {
    healthPill.textContent = `v${scraper.version} · ${scraper.activeSessions} 个可用`;
    healthPill.className = "pill good";
  }
}

async function inspectCookies() {
  const cookies = $("#session-cookies").value.trim();
  const status = $("#cookie-detection");
  if (!cookies) {
    status.textContent = "等待粘贴 Cookie";
    status.className = "cookie-detection";
    return;
  }
  try {
    const result = await api("/api/admin/cookies/inspect", { method: "POST", body: { cookies } });
    status.textContent = result.ready
      ? `✓ ${result.format}：已自动找到 auth_token 和 ct0`
      : `还缺少：${result.missing.join("、")}`;
    status.className = `cookie-detection ${result.ready ? "good" : "bad"}`;
  } catch (error) {
    status.textContent = error.message;
    status.className = "cookie-detection bad";
  }
}

async function addSession() {
  const label = $("#session-label").value.trim();
  const cookies = $("#session-cookies").value.trim();
  if (!cookies) return showToast("请先粘贴 Cookie", true);
  const button = $("#add-session");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "正在向 X 验证…";
  try {
    const item = await api("/api/admin/scraper-sessions", {
      method: "POST", body: { label, cookies },
    });
    $("#session-label").value = "";
    $("#session-cookies").value = "";
    $("#cookie-detection").textContent = "验证通过，原始 Cookie 已从表单清除";
    $("#cookie-detection").className = "cookie-detection good";
    await reloadSessionsAndHealth();
    const username = item.validation?.username ? ` @${item.validation.username}` : "";
    showToast(`凭证验证有效并已保存${username}`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

function renderSessions() {
  const list = $("#session-list");
  list.replaceChildren();
  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "尚无抓取凭证。粘贴完整 Cookie 后，系统会自动提取并验证。";
    list.append(empty);
    return;
  }
  for (const item of state.sessions) {
    const row = document.createElement("article");
    row.className = "admin-session-row";
    const dot = document.createElement("span");
    dot.className = `status-dot ${item.credentialState === "valid" && item.active ? "active" : ""}`;
    const copy = document.createElement("div");
    copy.className = "session-copy";
    const name = document.createElement("strong");
    name.textContent = item.label;
    const detail = document.createElement("small");
    if (item.credentialState === "valid") {
      detail.textContent = `已验证${item.verifiedUsername ? ` · @${item.verifiedUsername}` : ""}${item.verifiedAt ? ` · ${relativeTime(item.verifiedAt)}` : ""} · 已请求 ${item.totalRequests} 次`;
    } else if (item.credentialState === "invalid") {
      detail.textContent = "验证失败，请导入新的 Cookie";
    } else {
      detail.textContent = "旧凭证尚未在线验证";
    }
    copy.append(name, detail);
    const actions = document.createElement("div");
    actions.className = "row-actions";
    actions.append(actionButton("重新验证", "validate-session", item.label), actionButton("删除", "delete-session", item.label, true));
    row.append(dot, copy, actions);
    list.append(row);
  }
}

async function handleSessionAction(event) {
  const button = event.target.closest("[data-session-action]");
  if (!button) return;
  const label = button.dataset.label;
  button.disabled = true;
  try {
    if (button.dataset.sessionAction === "validate-session") {
      await api(`/api/admin/scraper-sessions/${encodeURIComponent(label)}/validate`, { method: "POST", body: {} });
      showToast(`“${label}”验证有效`);
    } else {
      if (!window.confirm(`删除抓取凭证“${label}”？`)) return;
      await api(`/api/admin/scraper-sessions/${encodeURIComponent(label)}`, { method: "DELETE" });
      showToast("抓取凭证已删除");
    }
    await reloadSessionsAndHealth();
  } catch (error) {
    showToast(error.message, true);
    await reloadSessionsAndHealth().catch(() => {});
  } finally {
    button.disabled = false;
  }
}

async function reloadSessionsAndHealth() {
  const [sessions, health] = await Promise.all([
    api("/api/admin/scraper-sessions"), api("/api/admin/health"),
  ]);
  state.sessions = sessions.items;
  state.health = health;
  renderSessions();
  renderStats();
}

async function addAccount(event) {
  event.preventDefault();
  const input = $("#new-username");
  const username = input.value.trim();
  if (!username) return;
  try {
    const account = await api("/api/admin/accounts", { method: "POST", body: { username } });
    input.value = "";
    await reloadAccounts();
    showToast(`已添加 @${account.username}，可执行首次更新`);
  } catch (error) { showToast(error.message, true); }
}

function renderAccounts() {
  const list = $("#admin-account-list");
  list.replaceChildren();
  if (!state.accounts.length) {
    const empty = document.createElement("div");
    empty.className = "admin-empty";
    empty.textContent = "尚未添加阅读用户。";
    list.append(empty);
    return;
  }
  for (const account of state.accounts) {
    const card = document.createElement("article");
    card.className = `admin-account-card${account.isPublic ? "" : " private-account"}${account.lastError ? " has-sync-error" : ""}`;
    const avatar = document.createElement("div");
    avatar.className = "admin-account-avatar";
    if (account.avatarUrl) {
      const image = document.createElement("img");
      image.src = account.avatarUrl;
      image.alt = "";
      avatar.append(image);
    } else avatar.textContent = (account.displayName || account.username).slice(0, 1).toUpperCase();
    const copy = document.createElement("div");
    copy.className = "admin-account-copy";
    const title = document.createElement("strong");
    title.textContent = `${account.displayName} @${account.username}${account.isPublic ? "" : " · 仅管理可见"}`;
    const meta = document.createElement("small");
    meta.textContent = `${account.tweetCount || 0} 条内容 · ${account.mediaCount || 0} 个媒体 · ${account.lastSyncedAt ? `更新于 ${relativeTime(account.lastSyncedAt)}` : "尚未更新"}`;
    const error = document.createElement("span");
    error.className = account.lastError ? "account-error" : "account-cursor";
    if (account.lastError) {
      error.textContent = `抓取失败：${describeSyncError(account.lastError).summary}`;
      error.title = account.lastError;
    } else {
      error.textContent = account.lastTweetId ? `增量游标 ${account.lastTweetId}` : "首次更新会读取最近内容";
    }
    copy.append(title, meta, error);
    const options = document.createElement("div");
    options.className = "account-option-checks";
    options.innerHTML = `<label class="public-option"><input type="checkbox" data-option="public" ${account.isPublic ? "checked" : ""}> 公开展示</label><label><input type="checkbox" data-option="replies" ${account.includeReplies ? "checked" : ""}> 回复</label><label><input type="checkbox" data-option="reposts" ${account.includeReposts ? "checked" : ""}> 转发</label>`;
    const actions = document.createElement("div");
    actions.className = "row-actions account-row-actions";
    actions.append(
      actionButton("保存设置", "save-account", account.id),
      actionButton(account.syncing ? "更新中…" : "立即更新", "sync-account", account.id),
      actionButton("删除", "delete-account", account.id, true),
    );
    const preview = document.createElement("a");
    preview.className = "text-button button-link";
    preview.href = `/reader?account=${account.id}`;
    preview.target = "_blank";
    preview.rel = "noopener noreferrer";
    preview.textContent = "预览";
    actions.prepend(preview);
    if (account.syncing) actions.querySelector('[data-account-action="sync-account"]').disabled = true;
    card.dataset.accountId = String(account.id);
    card.append(avatar, copy, options, actions);
    list.append(card);
  }
}

function actionButton(text, action, value, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = danger ? "text-button danger-text" : "text-button";
  button.textContent = text;
  if (action.includes("session")) {
    button.dataset.sessionAction = action;
    button.dataset.label = String(value);
  } else {
    button.dataset.accountAction = action;
    button.dataset.id = String(value);
  }
  return button;
}

function memberActionButton(text, action, memberId, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = danger ? "text-button danger-text" : "text-button";
  button.textContent = text;
  button.dataset.memberAction = action;
  button.dataset.id = String(memberId);
  return button;
}

async function addMember(event) {
  event.preventDefault();
  const username = $("#new-member-username").value.trim();
  const password = $("#new-member-password").value;
  if (!username || !password) return;
  const button = event.submitter;
  button.disabled = true;
  try {
    await api("/api/admin/members", {
      method: "POST",
      body: { username, password, accountIds: [] },
    });
    $("#new-member-username").value = "";
    $("#new-member-password").value = "";
    await reloadMembers();
    showToast(`会员 ${username} 已创建，请为其分配可查看用户`);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function renderMembers() {
  const list = $("#admin-member-list");
  list.replaceChildren();
  if (!state.members.length) {
    const empty = document.createElement("div");
    empty.className = "admin-empty";
    empty.textContent = "尚未创建会员。会员登录后只能看到公开用户和分配给自己的非公开用户。";
    list.append(empty);
    return;
  }
  for (const member of state.members) {
    const card = document.createElement("article");
    card.className = `admin-member-card${member.active ? "" : " inactive"}`;
    card.dataset.memberId = String(member.id);

    const heading = document.createElement("div");
    heading.className = "admin-member-heading";
    const identity = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = member.username;
    const meta = document.createElement("small");
    meta.textContent = member.lastLoginAt
      ? `上次登录 ${relativeTime(member.lastLoginAt)}`
      : `创建于 ${relativeTime(member.createdAt)}`;
    identity.append(title, meta);
    const active = document.createElement("label");
    active.className = "member-active-control";
    const activeInput = document.createElement("input");
    activeInput.type = "checkbox";
    activeInput.dataset.memberActive = "";
    activeInput.checked = Boolean(member.active);
    active.append(activeInput, document.createTextNode(" 允许登录"));
    heading.append(identity, active);

    const access = document.createElement("div");
    access.className = "member-access-block";
    const accessTitle = document.createElement("strong");
    accessTitle.textContent = "可查看的用户";
    const choices = document.createElement("div");
    choices.className = "member-account-choices";
    if (!state.accounts.length) {
      const none = document.createElement("span");
      none.className = "member-no-accounts";
      none.textContent = "请先添加抓取用户";
      choices.append(none);
    }
    for (const account of state.accounts) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.memberAccountId = String(account.id);
      input.checked = member.accountIds.includes(account.id);
      const suffix = account.isPublic ? "（公开）" : "（非公开）";
      label.append(input, document.createTextNode(` @${account.username}${suffix}`));
      choices.append(label);
    }
    access.append(accessTitle, choices);

    const footer = document.createElement("div");
    footer.className = "admin-member-footer";
    const password = document.createElement("input");
    password.type = "password";
    password.autocomplete = "new-password";
    password.placeholder = "留空不改密码；输入新密码可重置";
    password.dataset.memberPassword = "";
    const actions = document.createElement("div");
    actions.className = "row-actions";
    actions.append(
      memberActionButton("保存权限", "save-member", member.id),
      memberActionButton("删除会员", "delete-member", member.id, true),
    );
    footer.append(password, actions);
    card.append(heading, access, footer);
    list.append(card);
  }
}

async function handleMemberAction(event) {
  const button = event.target.closest("[data-member-action]");
  if (!button) return;
  const id = Number(button.dataset.id);
  const member = state.members.find((item) => item.id === id);
  if (!member) return;
  const card = button.closest(".admin-member-card");
  button.disabled = true;
  try {
    if (button.dataset.memberAction === "save-member") {
      const accountIds = [...card.querySelectorAll("[data-member-account-id]:checked")]
        .map((input) => Number(input.dataset.memberAccountId));
      await api(`/api/admin/members/${id}`, {
        method: "PATCH",
        body: {
          active: card.querySelector("[data-member-active]").checked,
          accountIds,
          password: card.querySelector("[data-member-password]").value,
        },
      });
      showToast(`会员 ${member.username} 的权限已保存`);
    } else {
      const confirmation = window.prompt(`删除会员 ${member.username}？请输入会员名确认：`);
      if (confirmation !== member.username) return;
      await api(`/api/admin/members/${id}`, { method: "DELETE" });
      showToast(`会员 ${member.username} 已删除`);
    }
    await reloadMembers();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function reloadMembers() {
  const response = await api("/api/admin/members");
  state.members = response.items;
  renderMembers();
  renderStats();
}

async function handleAccountAction(event) {
  const button = event.target.closest("[data-account-action]");
  if (!button) return;
  const id = Number(button.dataset.id);
  const account = state.accounts.find((item) => item.id === id);
  if (!account) return;
  const action = button.dataset.accountAction;
  button.disabled = true;
  try {
    if (action === "sync-account") {
      const result = await api(`/api/admin/accounts/${id}/sync`, { method: "POST", body: {} });
      const notice = result.notification?.sent === false
        ? `；Bark 失败：${result.notification.error}`
        : "";
      showToast(
        `@${account.username} 更新完成：新增 ${result.inserted} 条，媒体 ${result.mediaDownloaded} 个${notice}`,
        Boolean(notice),
      );
    } else if (action === "save-account") {
      const card = button.closest(".admin-account-card");
      await api(`/api/admin/accounts/${id}`, {
        method: "PATCH",
        body: {
          includeReplies: card.querySelector('[data-option="replies"]').checked,
          includeReposts: card.querySelector('[data-option="reposts"]').checked,
          isPublic: card.querySelector('[data-option="public"]').checked,
        },
      });
      showToast("用户设置已保存");
    } else {
      const confirmation = window.prompt(`这会删除 @${account.username} 的数据库记录和本地媒体。请输入账号名确认：`);
      if (confirmation !== account.username) return;
      await api(`/api/admin/accounts/${id}`, { method: "DELETE" });
      showToast(`@${account.username} 已删除`);
    }
    await reloadAccounts();
  } catch (error) {
    const message = action === "sync-account"
      ? `@${account.username} 更新失败：${describeSyncError(error.message).summary}`
      : error.message;
    showToast(message, true);
    await reloadAccounts().catch(() => {});
  } finally { button.disabled = false; }
}

async function reloadAccounts() {
  const response = await api("/api/admin/accounts");
  state.accounts = response.items;
  renderAccounts();
  renderSyncFailures();
  renderMembers();
  renderStats();
}

function fillSettings() {
  const settings = state.settings || {};
  $("#schedule-enabled").checked = Boolean(settings.scheduleEnabled);
  $("#schedule-minutes").value = settings.scheduleMinutes || 30;
  $("#initial-limit").value = settings.initialFetchLimit || 100;
  $("#incremental-limit").value = settings.incrementalScanLimit || 500;
  $("#media-concurrency").value = settings.mediaConcurrency || 3;
  $("#max-media-mb").value = settings.maxMediaMb || 250;
  $("#proxy-enabled").checked = Boolean(settings.proxyEnabled);
  $("#proxy-url").value = settings.proxyUrl || "";
  $("#bark-enabled").checked = Boolean(settings.barkEnabled);
  $("#bark-server-url").value = settings.barkServerUrl || "https://api.day.app";
  $("#bark-device-key").value = "";
  $("#bark-device-key").placeholder = settings.barkDeviceKeyConfigured
    ? "已安全保存，留空不修改"
    : "从 Bark App 复制 Device Key";
  $("#bark-group").value = settings.barkGroup || "Incandescence";
  $("#site-base-url").value = settings.siteBaseUrl || "";
  $("#bark-key-state").textContent = settings.barkDeviceKeyConfigured
    ? "Device Key 已保存且不会回传到网页。站点地址建议填写手机可访问的局域网地址。"
    : "Device Key 尚未保存。站点地址建议填写其他设备可以访问的局域网地址。";
}

async function saveBark() {
  const button = $("#save-bark");
  const key = $("#bark-device-key").value.trim();
  const body = {
    barkEnabled: $("#bark-enabled").checked,
    barkServerUrl: $("#bark-server-url").value.trim(),
    barkGroup: $("#bark-group").value.trim(),
    siteBaseUrl: $("#site-base-url").value.trim(),
  };
  if (key) body.barkDeviceKey = key;
  if (body.barkEnabled && !key && !state.settings?.barkDeviceKeyConfigured) {
    return showToast("开启 Bark 推送前请填写 Device Key", true);
  }
  button.disabled = true;
  try {
    state.settings = await api("/api/admin/settings", { method: "PUT", body });
    fillSettings();
    $("#bark-test-result").textContent = state.settings.barkEnabled
      ? "设置已保存；仅在后续增量抓到新内容时推送"
      : "设置已保存，Bark 推送当前关闭";
    $("#bark-test-result").className = "good";
    showToast("Bark 通知设置已保存");
  } catch (error) {
    $("#bark-test-result").textContent = error.message;
    $("#bark-test-result").className = "bad";
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function testBark() {
  const button = $("#test-bark");
  const resultNode = $("#bark-test-result");
  if ($("#bark-device-key").value.trim()) {
    return showToast("Device Key 有未保存的修改，请先保存通知设置", true);
  }
  if (!state.settings?.barkDeviceKeyConfigured) {
    return showToast("请先填写并保存 Bark Device Key", true);
  }
  button.disabled = true;
  resultNode.textContent = "正在发送 Bark 测试通知…";
  resultNode.className = "testing";
  try {
    const result = await api("/api/admin/bark/test", { method: "POST", body: {} });
    resultNode.textContent = `测试推送已送达 · HTTP ${result.status} · ${result.elapsedMs} ms`;
    resultNode.className = "good";
    showToast("Bark 测试通知已发送");
  } catch (error) {
    resultNode.textContent = error.message;
    resultNode.className = "bad";
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function clearBarkKey() {
  if (!state.settings?.barkDeviceKeyConfigured) return;
  if (!window.confirm("清除已保存的 Bark Device Key 并关闭推送？")) return;
  try {
    state.settings = await api("/api/admin/settings", {
      method: "PUT",
      body: { barkEnabled: false, barkClearDeviceKey: true },
    });
    fillSettings();
    $("#bark-test-result").textContent = "Bark Device Key 已清除";
    $("#bark-test-result").className = "good";
    showToast("Bark 密钥已清除");
  } catch (error) {
    showToast(error.message, true);
  }
}

async function testProxy() {
  const proxyUrl = $("#proxy-url").value.trim();
  const button = $("#test-proxy");
  const resultNode = $("#proxy-test-result");
  if (!proxyUrl) return showToast("请填写代理地址", true);
  button.disabled = true;
  resultNode.textContent = "正在通过代理连接 X…";
  resultNode.className = "testing";
  try {
    const result = await api("/api/admin/proxy/test", {
      method: "POST", body: { proxyUrl },
    });
    resultNode.textContent = `连接成功 · HTTP ${result.status} · ${result.elapsedMs} ms`;
    resultNode.className = "good";
    showToast("代理可以访问 X");
  } catch (error) {
    resultNode.textContent = error.message;
    resultNode.className = "bad";
    showToast(error.message, true);
  } finally { button.disabled = false; }
}

async function saveProxy() {
  const button = $("#save-proxy");
  button.disabled = true;
  try {
    state.settings = await api("/api/admin/settings", {
      method: "PUT",
      body: {
        proxyEnabled: $("#proxy-enabled").checked,
        proxyUrl: $("#proxy-url").value.trim(),
      },
    });
    fillSettings();
    $("#proxy-test-result").textContent = state.settings.proxyEnabled
      ? "代理设置已保存；后续网络请求将使用此代理"
      : "代理已关闭";
    $("#proxy-test-result").className = "good";
    showToast("代理设置已保存");
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
}

async function saveSettings() {
  const button = $("#save-settings");
  button.disabled = true;
  try {
    state.settings = await api("/api/admin/settings", {
      method: "PUT",
      body: {
        scheduleEnabled: $("#schedule-enabled").checked,
        scheduleMinutes: Number($("#schedule-minutes").value),
        initialFetchLimit: Number($("#initial-limit").value),
        incrementalScanLimit: Number($("#incremental-limit").value),
        mediaConcurrency: Number($("#media-concurrency").value),
        maxMediaMb: Number($("#max-media-mb").value),
      },
    });
    fillSettings();
    renderStats();
    showToast("自动更新设置已保存");
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
}

async function syncAll() {
  const button = $("#sync-all");
  button.disabled = true;
  try {
    const result = await api("/api/admin/sync-all", { method: "POST", body: {} });
    const notificationFailures = result.results.filter(
      (item) => item.notification?.sent === false,
    ).length;
    const notice = notificationFailures ? `，Bark 失败 ${notificationFailures}` : "";
    const failures = result.results.filter((item) => item.error);
    const failedAccounts = failures.map((item) => `@${item.username || item.accountId}`).join("、");
    await loadDashboard();
    showToast(
      failures.length
        ? `更新完成：成功 ${result.succeeded}，失败 ${result.failed}（${failedAccounts}）；详情已列在页面顶部${notice}`
        : `更新完成：成功 ${result.succeeded}，失败 ${result.failed}${notice}`,
      result.failed > 0 || notificationFailures > 0,
    );
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
}

async function refreshStatus() {
  if ($("#admin-app").hidden) return;
  try {
    const [health, accounts, sessions, members] = await Promise.all([
      api("/api/admin/health"),
      api("/api/admin/accounts"),
      api("/api/admin/scraper-sessions"),
      api("/api/admin/members"),
    ]);
    state.health = health;
    state.accounts = accounts.items;
    state.sessions = sessions.items;
    state.members = members.items;
    renderStats();
    renderSyncFailures();
    renderAccounts();
    renderSessions();
    renderMembers();
  } catch (_) { /* polling failures do not interrupt administration */ }
}

function relativeTime(value) {
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });
  if (Math.abs(seconds) < 60) return formatter.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return formatter.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return formatter.format(hours, "hour");
  return formatter.format(Math.round(hours / 24), "day");
}

function showAuthError(message) {
  $("#auth-error").textContent = message || "";
}

function showToast(message, error = false) {
  const toast = $("#toast");
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 4600);
}

initialize();
