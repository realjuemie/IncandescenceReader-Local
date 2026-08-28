"use strict";

const $ = (selector) => document.querySelector(selector);
const i18n = window.XGlowI18n;
const t = (key, variables) => i18n.t(key, variables);
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
  accountDrafts: new Map(),
  memberDrafts: new Map(),
  shareAccount: null,
  shareMinutes: 1440,
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
    throw new Error(i18n.localizeError(payload.error) || t("requestFailed", { status: response.status }));
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
  $("#admin-account-list").addEventListener("input", rememberAccountDraft);
  $("#sync-failure-list").addEventListener("click", handleAccountAction);
  $("#add-member-form").addEventListener("submit", addMember);
  $("#admin-member-list").addEventListener("click", handleMemberAction);
  $("#admin-member-list").addEventListener("input", rememberMemberDraft);
  $("#save-settings").addEventListener("click", saveSettings);
  $("#save-proxy").addEventListener("click", saveProxy);
  $("#test-proxy").addEventListener("click", testProxy);
  $("#save-bark").addEventListener("click", saveBark);
  $("#test-bark").addEventListener("click", testBark);
  $("#clear-bark-key").addEventListener("click", clearBarkKey);
  $("#sync-all").addEventListener("click", syncAll);
  $("#retry-failed").addEventListener("click", syncFailed);
}

function showAuth(setupRequired) {
  state.setupRequired = Boolean(setupRequired);
  $("#admin-app").hidden = true;
  $("#auth-view").hidden = false;
  $("#auth-title").textContent = state.setupRequired ? t("setupAdmin") : (i18n.locale === "en" ? "Administrator sign in" : "管理员登录");
  $("#auth-description").textContent = state.setupRequired
    ? t("setupDescription")
    : (i18n.locale === "en" ? "Sign in to manage X credentials, reading accounts, and automatic updates." : "登录后管理抓取凭证、阅读账号和自动更新。");
  $("#auth-submit").textContent = state.setupRequired ? t("createAdmin") : (i18n.locale === "en" ? "Sign in" : "登录");
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
    showAuthError(t("passwordMismatch"));
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
  const detail = String(value || t("syncFailed")).trim() || t("syncFailed");
  let summary = detail;
  if (/rate.?limit|too many requests|请求额度|频率受限|\b429\b/i.test(detail)) {
    summary = t("rateLimited");
  } else if (/timeout|timed out/i.test(detail)) {
    summary = t("xTimeout");
  } else if (/no active accounts|cookie|unauthori[sz]ed|forbidden|\b401\b|\b403\b/i.test(detail)) {
    summary = t("credentialInvalid");
  } else if (/not found|does not exist|could not find user/i.test(detail)) {
    summary = t("accountMissing");
  } else if (/protected|private account/i.test(detail)) {
    summary = t("protectedAccount");
  } else if (/proxy|connection refused|connection reset|network|dns/i.test(detail)) {
    summary = t("networkFailed");
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
  $("#sync-failure-count").textContent = t("failuresNeedAction", { count: failures.length });
  $("#retry-failed").disabled = Boolean(state.health?.sync?.running);
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
      ? t("failedAt", { relative: relativeTime(account.lastFailedAt), absolute: new Date(account.lastFailedAt).toLocaleString(i18n.localeTag()) })
      : t("failureTimeUnknown");
    copy.append(title, reason);
    if (issue.detail) {
      const technical = document.createElement("code");
      technical.textContent = t("technicalInfo", { detail: issue.detail });
      copy.append(technical);
    }
    copy.append(time);
    const retry = actionButton(t("retrySync"), "sync-account", account.id);
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
  $("#stat-account-total").textContent = t("accountMemberTotal", { accounts: state.accounts.length, members: state.members.length });
  $("#stat-sessions").textContent = String(scraper.activeSessions || 0);
  $("#stat-scraper-version").textContent = scraper.installed ? `twscrape v${scraper.version}` : t("componentMissing");
  $("#stat-schedule").textContent = state.settings?.scheduleEnabled ? t("scheduleMinutes", { minutes: state.settings.scheduleMinutes }) : t("scheduleOff");
  $("#stat-next-run").textContent = scheduler.nextRunAt ? t("nextRun", { time: relativeTime(scheduler.nextRunAt) }) : t("noSchedule");
  $("#stat-sync").textContent = sync.running ? t("running") : t("idle");
  const last = scheduler.lastResult;
  $("#stat-last-result").textContent = last ? t("lastResult", { ok: last.succeeded || 0, failed: last.failed || 0 }) : t("noTask");
  const healthPill = $("#scraper-health");
  if (!scraper.installed) {
    healthPill.textContent = t("componentMissing");
    healthPill.className = "pill bad";
  } else if (!scraper.activeSessions) {
    healthPill.textContent = t("noValidCredentials", { version: scraper.version });
    healthPill.className = "pill bad";
  } else {
    healthPill.textContent = t("availableCredentials", { version: scraper.version, count: scraper.activeSessions });
    healthPill.className = "pill good";
  }
}

async function inspectCookies() {
  const cookies = $("#session-cookies").value.trim();
  const status = $("#cookie-detection");
  if (!cookies) {
    status.textContent = i18n.locale === "en" ? "Waiting for Cookie input" : "等待粘贴 Cookie";
    status.className = "cookie-detection";
    return;
  }
  try {
    const result = await api("/api/admin/cookies/inspect", { method: "POST", body: { cookies } });
    status.textContent = result.ready
      ? t("cookiesFound", { format: result.format })
      : t("cookiesMissing", { items: result.missing.join(i18n.locale === "en" ? ", " : "、") });
    status.className = `cookie-detection ${result.ready ? "good" : "bad"}`;
  } catch (error) {
    status.textContent = error.message;
    status.className = "cookie-detection bad";
  }
}

async function addSession() {
  const label = $("#session-label").value.trim();
  const cookies = $("#session-cookies").value.trim();
  if (!cookies) return showToast(t("pasteCookie"), true);
  const button = $("#add-session");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = t("validatingX");
  try {
    const item = await api("/api/admin/scraper-sessions", {
      method: "POST", body: { label, cookies },
    });
    $("#session-label").value = "";
    $("#session-cookies").value = "";
    $("#cookie-detection").textContent = t("cookieValidated");
    $("#cookie-detection").className = "cookie-detection good";
    await reloadSessionsAndHealth();
    const username = item.validation?.username ? ` @${item.validation.username}` : "";
    showToast(t("credentialSaved", { username }));
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
    empty.textContent = t("noCredentials");
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
      detail.textContent = t("verifiedDetail", { username: item.verifiedUsername ? ` · @${item.verifiedUsername}` : "", time: item.verifiedAt ? ` · ${relativeTime(item.verifiedAt)}` : "", count: item.totalRequests });
    } else if (item.credentialState === "invalid") {
      detail.textContent = t("validationFailed");
    } else {
      detail.textContent = t("legacyCredential");
    }
    copy.append(name, detail);
    const actions = document.createElement("div");
    actions.className = "row-actions";
    actions.append(actionButton(t("validateAgain"), "validate-session", item.label), actionButton(t("deleteAction"), "delete-session", item.label, true));
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
      showToast(t("credentialValid", { label }));
    } else {
      if (!window.confirm(t("deleteCredential", { label }))) return;
      await api(`/api/admin/scraper-sessions/${encodeURIComponent(label)}`, { method: "DELETE" });
      showToast(t("credentialDeleted"));
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
    showToast(t("accountAdded", { username: account.username }));
  } catch (error) { showToast(error.message, true); }
}

function renderAccounts() {
  const list = $("#admin-account-list");
  list.replaceChildren();
  if (!state.accounts.length) {
    const empty = document.createElement("div");
    empty.className = "admin-empty";
    empty.textContent = t("noAccounts");
    list.append(empty);
    return;
  }
  for (const account of state.accounts) {
    const draft = state.accountDrafts.get(account.id);
    const selected = draft || {
      isPublic: account.isPublic,
      includeReplies: account.includeReplies,
      includeReposts: account.includeReposts,
    };
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
    title.textContent = `${account.displayName} @${account.username}${account.isPublic ? "" : t("adminOnlySuffix")}`;
    const meta = document.createElement("small");
    meta.textContent = t("accountMeta", {
      tweets: account.tweetCount || 0,
      media: account.mediaCount || 0,
      updated: account.lastSyncedAt ? t("updatedAt", { time: relativeTime(account.lastSyncedAt) }) : t("awaitingUpdate"),
    });
    const error = document.createElement("span");
    error.className = account.lastError ? "account-error" : "account-cursor";
    if (account.lastError) {
      error.textContent = t("syncFailure", { error: describeSyncError(account.lastError).summary });
      error.title = account.lastError;
    } else {
      error.textContent = account.lastTweetId ? t("cursor", { id: account.lastTweetId }) : t("firstSyncHint");
    }
    copy.append(title, meta, error);
    const options = document.createElement("div");
    options.className = "account-option-checks";
    options.innerHTML = `<label class="public-option"><input type="checkbox" data-option="public" ${selected.isPublic ? "checked" : ""}> ${t("publicDisplay")}</label><label><input type="checkbox" data-option="replies" ${selected.includeReplies ? "checked" : ""}> ${t("replies")}</label><label><input type="checkbox" data-option="reposts" ${selected.includeReposts ? "checked" : ""}> ${t("reposts")}</label>`;
    const actions = document.createElement("div");
    actions.className = "row-actions account-row-actions";
    actions.append(
      actionButton(t("saveSettings"), "save-account", account.id),
      actionButton(account.syncing ? t("syncing") : t("syncNow"), "sync-account", account.id),
      actionButton(t("temporaryShare"), "share-account", account.id),
      actionButton(t("deleteAction"), "delete-account", account.id, true),
    );
    const preview = document.createElement("a");
    preview.className = "text-button button-link";
    preview.href = `/reader?account=${account.id}`;
    preview.target = "_blank";
    preview.rel = "noopener noreferrer";
    preview.textContent = t("preview");
    actions.prepend(preview);
    if (account.syncing) actions.querySelector('[data-account-action="sync-account"]').disabled = true;
    card.dataset.accountId = String(account.id);
    card.append(avatar, copy, options, actions);
    list.append(card);
  }
}

function rememberAccountDraft(event) {
  const card = event.target.closest(".admin-account-card");
  if (!card || !event.target.matches('[data-option]')) return;
  state.accountDrafts.set(Number(card.dataset.accountId), {
    isPublic: card.querySelector('[data-option="public"]').checked,
    includeReplies: card.querySelector('[data-option="replies"]').checked,
    includeReposts: card.querySelector('[data-option="reposts"]').checked,
  });
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
    showToast(t("memberCreated", { username }));
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
    empty.textContent = t("noMembers");
    list.append(empty);
    return;
  }
  for (const member of state.members) {
    const draft = state.memberDrafts.get(member.id);
    const selectedAccountIds = draft?.accountIds || member.accountIds;
    const card = document.createElement("article");
    card.className = `admin-member-card${(draft?.active ?? member.active) ? "" : " inactive"}${draft ? " has-unsaved" : ""}`;
    card.dataset.memberId = String(member.id);

    const heading = document.createElement("div");
    heading.className = "admin-member-heading";
    const identity = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = member.username;
    const meta = document.createElement("small");
    meta.textContent = member.lastLoginAt
      ? t("lastLogin", { time: relativeTime(member.lastLoginAt) })
      : t("createdAt", { time: relativeTime(member.createdAt) });
    if (draft) {
      meta.textContent += ` · ${t("unsavedChanges")}`;
      meta.dataset.unsaved = "true";
    }
    identity.append(title, meta);
    const active = document.createElement("label");
    active.className = "member-active-control";
    const activeInput = document.createElement("input");
    activeInput.type = "checkbox";
    activeInput.dataset.memberActive = "";
    activeInput.checked = Boolean(draft?.active ?? member.active);
    active.append(activeInput, document.createTextNode(` ${t("allowLogin")}`));
    heading.append(identity, active);

    const access = document.createElement("div");
    access.className = "member-access-block";
    const accessTitle = document.createElement("strong");
    accessTitle.textContent = t("visibleAccounts");
    const choices = document.createElement("div");
    choices.className = "member-account-choices";
    if (!state.accounts.length) {
      const none = document.createElement("span");
      none.className = "member-no-accounts";
      none.textContent = t("addAccountsFirst");
      choices.append(none);
    }
    for (const account of state.accounts) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.dataset.memberAccountId = String(account.id);
      input.checked = selectedAccountIds.includes(account.id);
      const suffix = account.isPublic ? t("publicSuffix") : t("privateSuffix");
      label.append(input, document.createTextNode(` @${account.username}${suffix}`));
      choices.append(label);
    }
    access.append(accessTitle, choices);

    const footer = document.createElement("div");
    footer.className = "admin-member-footer";
    const password = document.createElement("input");
    password.type = "password";
    password.autocomplete = "new-password";
    password.placeholder = t("resetPasswordPlaceholder");
    password.dataset.memberPassword = "";
    password.value = draft?.password || "";
    const actions = document.createElement("div");
    actions.className = "row-actions";
    actions.append(
      memberActionButton(t("savePermissions"), "save-member", member.id),
      memberActionButton(t("deleteMember"), "delete-member", member.id, true),
    );
    footer.append(password, actions);
    card.append(heading, access, footer);
    list.append(card);
  }
}

function readMemberDraft(card) {
  return {
    active: card.querySelector("[data-member-active]").checked,
    accountIds: [...card.querySelectorAll("[data-member-account-id]:checked")]
      .map((input) => Number(input.dataset.memberAccountId)),
    password: card.querySelector("[data-member-password]").value,
  };
}

function rememberMemberDraft(event) {
  if (!event.target.matches("[data-member-active], [data-member-account-id], [data-member-password]")) return;
  const card = event.target.closest(".admin-member-card");
  if (!card) return;
  const id = Number(card.dataset.memberId);
  state.memberDrafts.set(id, readMemberDraft(card));
  card.classList.add("has-unsaved");
  const meta = card.querySelector(".admin-member-heading small");
  if (meta && !meta.dataset.unsaved) {
    meta.textContent += ` · ${t("unsavedChanges")}`;
    meta.dataset.unsaved = "true";
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
      const draft = readMemberDraft(card);
      const saved = await api(`/api/admin/members/${id}`, {
        method: "PATCH",
        body: {
          active: draft.active,
          accountIds: draft.accountIds,
          password: draft.password,
        },
      });
      state.members = state.members.map((item) => item.id === id ? saved : item);
      state.memberDrafts.delete(id);
      showToast(t("permissionsSaved", { username: member.username }));
    } else {
      const confirmation = window.prompt(t("confirmDeleteMember", { username: member.username }));
      if (confirmation !== member.username) return;
      await api(`/api/admin/members/${id}`, { method: "DELETE" });
      state.memberDrafts.delete(id);
      state.members = state.members.filter((item) => item.id !== id);
      showToast(t("memberDeleted", { username: member.username }));
    }
    renderMembers();
    renderStats();
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
  if (action === "share-account") {
    openShareDialog(account);
    return;
  }
  button.disabled = true;
  try {
    if (action === "sync-account") {
      const result = await api(`/api/admin/accounts/${id}/sync`, { method: "POST", body: {} });
      const notice = result.notification?.sent === false
        ? t("barkFailed", { error: result.notification.error })
        : "";
      showToast(
        t("syncAccountDone", { username: account.username, inserted: result.inserted, media: result.mediaDownloaded, notice }),
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
      state.accountDrafts.delete(id);
      showToast(t("accountSettingsSaved"));
    } else if (action === "delete-account") {
      const confirmation = window.prompt(t("confirmDeleteAccount", { username: account.username }));
      if (confirmation !== account.username) return;
      await api(`/api/admin/accounts/${id}`, { method: "DELETE" });
      state.accountDrafts.delete(id);
      showToast(t("accountDeleted", { username: account.username }));
    }
    await reloadAccounts();
  } catch (error) {
    const message = action === "sync-account"
      ? t("syncAccountFailed", { username: account.username, error: describeSyncError(error.message).summary })
      : error.message;
    showToast(message, true);
    await reloadAccounts().catch(() => {});
  } finally { button.disabled = false; }
}

function ensureShareDialog() {
  let dialog = $("#admin-share-dialog");
  if (dialog) return dialog;
  dialog = document.createElement("dialog");
  dialog.id = "admin-share-dialog";
  dialog.className = "member-notification-dialog admin-share-dialog";
  dialog.innerHTML = `
    <form class="member-notification-card" id="admin-share-form">
      <header>
        <div><div class="eyebrow">TEMPORARY ACCESS</div><h2>${t("temporaryShareTitle")}</h2></div>
        <button type="button" class="member-notification-close" aria-label="${t("close")}">×</button>
      </header>
      <p class="member-notification-intro" id="admin-share-intro"></p>
      <div class="admin-share-presets" aria-label="${t("popularDurations")}">
        <button type="button" data-share-preset="60">${t("durationHours", { count: 1 })}</button>
        <button type="button" data-share-preset="360">${t("durationHours", { count: 6 })}</button>
        <button type="button" data-share-preset="1440">${t("durationDays", { count: 1 })}</button>
        <button type="button" data-share-preset="4320">${t("durationDays", { count: 3 })}</button>
        <button type="button" data-share-preset="10080">${t("durationDays", { count: 7 })}</button>
      </div>
      <div class="admin-share-custom">
        <span class="admin-share-custom-label">${t("customDuration")}</span>
        <div class="admin-share-stepper">
          <button type="button" data-share-step="-1" aria-label="${t("decreaseDuration")}">−</button>
          <input type="number" id="admin-share-value" min="1" max="90" value="1" inputmode="numeric" aria-label="${t("validFor")}" required>
          <button type="button" data-share-step="1" aria-label="${t("increaseDuration")}">＋</button>
        </div>
        <div class="admin-share-unit-switch" role="group" aria-label="${t("timeUnit")}">
          <button type="button" data-share-unit="1">${t("minutes")}</button>
          <button type="button" data-share-unit="60">${t("hours")}</button>
          <button type="button" data-share-unit="1440">${t("days")}</button>
        </div>
      </div>
      <label class="admin-share-result" id="admin-share-result" hidden>${t("shareLink")}<input id="admin-share-url" readonly></label>
      <div class="member-notification-result" id="admin-share-status" role="status"></div>
      <footer class="member-password-footer">
        <button type="button" class="secondary-button" id="admin-share-cancel">${t("cancel")}</button>
        <button type="submit" class="primary-button" id="admin-share-create">${t("createAndCopy")}</button>
      </footer>
    </form>`;
  document.body.append(dialog);
  dialog.querySelector(".member-notification-close").addEventListener("click", () => dialog.close());
  dialog.querySelector("#admin-share-cancel").addEventListener("click", () => dialog.close());
  dialog.querySelector("#admin-share-form").addEventListener("submit", createTemporaryShare);
  dialog.querySelector(".admin-share-presets").addEventListener("click", (event) => {
    const preset = event.target.closest("[data-share-preset]");
    if (preset) setShareDuration(Number(preset.dataset.sharePreset));
  });
  dialog.querySelector(".admin-share-unit-switch").addEventListener("click", (event) => {
    const unit = event.target.closest("[data-share-unit]");
    if (unit) selectShareUnit(Number(unit.dataset.shareUnit));
  });
  dialog.querySelector(".admin-share-stepper").addEventListener("click", (event) => {
    const step = event.target.closest("[data-share-step]");
    if (!step) return;
    const input = dialog.querySelector("#admin-share-value");
    Number(step.dataset.shareStep) > 0 ? input.stepUp() : input.stepDown();
    updateShareDurationFromControls();
  });
  dialog.querySelector("#admin-share-value").addEventListener("input", updateShareDurationFromControls);
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  return dialog;
}

function shareDurationLimits(unit) {
  return unit === 1 ? [5, 129600] : (unit === 60 ? [1, 2160] : [1, 90]);
}

function setShareDuration(minutes) {
  const dialog = ensureShareDialog();
  state.shareMinutes = Math.min(129600, Math.max(5, Math.round(minutes)));
  const unit = state.shareMinutes % 1440 === 0 ? 1440 : (state.shareMinutes % 60 === 0 ? 60 : 1);
  const input = dialog.querySelector("#admin-share-value");
  const [minimum, maximum] = shareDurationLimits(unit);
  input.min = String(minimum);
  input.max = String(maximum);
  input.value = String(state.shareMinutes / unit);
  for (const button of dialog.querySelectorAll("[data-share-unit]")) {
    button.classList.toggle("active", Number(button.dataset.shareUnit) === unit);
  }
  for (const button of dialog.querySelectorAll("[data-share-preset]")) {
    button.classList.toggle("active", Number(button.dataset.sharePreset) === state.shareMinutes);
  }
}

function selectShareUnit(unit) {
  const dialog = ensureShareDialog();
  const [minimum, maximum] = shareDurationLimits(unit);
  const input = dialog.querySelector("#admin-share-value");
  input.min = String(minimum);
  input.max = String(maximum);
  input.value = String(Math.min(maximum, Math.max(minimum, Math.round(state.shareMinutes / unit))));
  for (const button of dialog.querySelectorAll("[data-share-unit]")) {
    button.classList.toggle("active", Number(button.dataset.shareUnit) === unit);
  }
  updateShareDurationFromControls();
  input.focus();
}

function updateShareDurationFromControls() {
  const dialog = ensureShareDialog();
  const unit = Number(dialog.querySelector("[data-share-unit].active")?.dataset.shareUnit || 1440);
  const input = dialog.querySelector("#admin-share-value");
  const [minimum, maximum] = shareDurationLimits(unit);
  const value = Math.min(maximum, Math.max(minimum, Number(input.value) || minimum));
  input.value = String(value);
  state.shareMinutes = Math.round(value * unit);
  for (const button of dialog.querySelectorAll("[data-share-preset]")) {
    button.classList.toggle("active", Number(button.dataset.sharePreset) === state.shareMinutes);
  }
}

function openShareDialog(account) {
  const dialog = ensureShareDialog();
  state.shareAccount = account;
  dialog.querySelector("#admin-share-intro").textContent = t("temporaryShareIntro", { username: account.username });
  dialog.querySelector("#admin-share-result").hidden = true;
  dialog.querySelector("#admin-share-url").value = "";
  dialog.querySelector("#admin-share-status").textContent = "";
  setShareDuration(1440);
  dialog.showModal();
  dialog.querySelector("#admin-share-value").focus();
}

async function createTemporaryShare(event) {
  event.preventDefault();
  if (!state.shareAccount) return;
  const dialog = ensureShareDialog();
  const button = dialog.querySelector("#admin-share-create");
  button.disabled = true;
  dialog.querySelector("#admin-share-status").textContent = t("creatingShare");
  try {
    const result = await api(`/api/admin/accounts/${state.shareAccount.id}/shares`, {
      method: "POST",
      body: { expiresInMinutes: state.shareMinutes },
    });
    const url = new URL(result.url, window.location.origin).href;
    const output = dialog.querySelector("#admin-share-url");
    output.value = url;
    dialog.querySelector("#admin-share-result").hidden = false;
    await copyText(url, output);
    const expiry = new Intl.DateTimeFormat(i18n.localeTag(), {
      dateStyle: "medium", timeStyle: "short",
    }).format(new Date(result.expiresAt));
    dialog.querySelector("#admin-share-status").textContent = t("shareCopiedUntil", { time: expiry });
    showToast(t("shareCopied"));
  } catch (error) {
    dialog.querySelector("#admin-share-status").textContent = error.message;
  } finally { button.disabled = false; }
}

async function copyText(value, fallbackInput) {
  try {
    await navigator.clipboard.writeText(value);
  } catch (_) {
    fallbackInput.focus();
    fallbackInput.select();
    if (!document.execCommand("copy")) throw new Error(t("copyFailed"));
  }
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
    ? t("keySavedPlaceholder")
    : t("keyCopyPlaceholder");
  $("#bark-group").value = settings.barkGroup || "XGlow";
  $("#site-base-url").value = settings.siteBaseUrl || "";
  $("#bark-key-state").textContent = settings.barkDeviceKeyConfigured
    ? t("keySavedHelp")
    : t("keyMissingHelp");
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
    return showToast(t("barkKeyRequired"), true);
  }
  button.disabled = true;
  try {
    state.settings = await api("/api/admin/settings", { method: "PUT", body });
    fillSettings();
    $("#bark-test-result").textContent = state.settings.barkEnabled
      ? t("barkEnabledSaved")
      : t("barkDisabledSaved");
    $("#bark-test-result").className = "good";
    showToast(t("barkSaved"));
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
    return showToast(t("unsavedKey"), true);
  }
  if (!state.settings?.barkDeviceKeyConfigured) {
    return showToast(t("saveKeyFirst"), true);
  }
  button.disabled = true;
  resultNode.textContent = t("sendingBarkTest");
  resultNode.className = "testing";
  try {
    const result = await api("/api/admin/bark/test", { method: "POST", body: {} });
    resultNode.textContent = t("barkTestDelivered", { status: result.status, elapsed: result.elapsedMs });
    resultNode.className = "good";
    showToast(t("barkTestSent"));
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
  if (!window.confirm(t("confirmClearBark"))) return;
  try {
    state.settings = await api("/api/admin/settings", {
      method: "PUT",
      body: { barkEnabled: false, barkClearDeviceKey: true },
    });
    fillSettings();
    $("#bark-test-result").textContent = t("barkKeyCleared");
    $("#bark-test-result").className = "good";
    showToast(t("barkClearedToast"));
  } catch (error) {
    showToast(error.message, true);
  }
}

async function testProxy() {
  const proxyUrl = $("#proxy-url").value.trim();
  const button = $("#test-proxy");
  const resultNode = $("#proxy-test-result");
  if (!proxyUrl) return showToast(t("proxyRequired"), true);
  button.disabled = true;
  resultNode.textContent = t("testingProxy");
  resultNode.className = "testing";
  try {
    const result = await api("/api/admin/proxy/test", {
      method: "POST", body: { proxyUrl },
    });
    resultNode.textContent = t("proxyConnected", { status: result.status, elapsed: result.elapsedMs });
    resultNode.className = "good";
    showToast(t("proxyWorks"));
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
      ? t("proxyEnabledSaved")
      : t("proxyDisabled");
    $("#proxy-test-result").className = "good";
    showToast(t("proxySaved"));
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
    showToast(t("schedulerSaved"));
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
    const notice = notificationFailures ? t("barkFailureCount", { count: notificationFailures }) : "";
    const failures = result.results.filter((item) => item.error);
    const failedAccounts = failures.map((item) => `@${item.username || item.accountId}`).join(i18n.locale === "en" ? ", " : "、");
    await loadDashboard();
    showToast(
      failures.length
        ? t("syncAllFailures", { ok: result.succeeded, failed: result.failed, accounts: failedAccounts, notice })
        : t("syncAllDone", { ok: result.succeeded, failed: result.failed, notice }),
      result.failed > 0 || notificationFailures > 0,
    );
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
}

async function syncFailed() {
  const failuresBeforeRetry = state.accounts.filter((account) => account.lastError);
  if (!failuresBeforeRetry.length) return;
  const button = $("#retry-failed");
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = t("retryingFailed", { count: failuresBeforeRetry.length });
  try {
    const result = await api("/api/admin/sync-failed", { method: "POST", body: {} });
    const failures = result.results.filter((item) => item.error);
    const failedAccounts = failures.map((item) => `@${item.username || item.accountId}`).join(i18n.locale === "en" ? ", " : "、");
    await loadDashboard();
    showToast(
      failures.length
        ? t("retryFailedResult", { ok: result.succeeded, failed: result.failed, accounts: failedAccounts })
        : t("retryFailedDone", { ok: result.succeeded }),
      failures.length > 0,
    );
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.textContent = originalLabel;
    button.disabled = false;
  }
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
    const memberListFocused = $("#admin-member-list").contains(document.activeElement);
    if (!state.memberDrafts.size && !memberListFocused) renderMembers();
  } catch (_) { /* polling failures do not interrupt administration */ }
}

function relativeTime(value) {
  const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
  const formatter = new Intl.RelativeTimeFormat(i18n.localeTag(), { numeric: "auto" });
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
window.addEventListener("xglow:localechange", () => {
  if (!$("#auth-view").hidden) {
    $("#auth-title").textContent = state.setupRequired ? t("setupAdmin") : (i18n.locale === "en" ? "Administrator sign in" : "管理员登录");
    $("#auth-description").textContent = state.setupRequired ? t("setupDescription") : (i18n.locale === "en" ? "Sign in to manage X credentials, reading accounts, and automatic updates." : "登录后管理抓取凭证、阅读账号和自动更新。");
    $("#auth-submit").textContent = state.setupRequired ? t("createAdmin") : (i18n.locale === "en" ? "Sign in" : "登录");
  }
  if (!$("#admin-app").hidden) renderDashboard();
});
