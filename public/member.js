"use strict";

const $ = (selector) => document.querySelector(selector);
const i18n = window.XGlowI18n;
const t = (key, variables) => i18n.t(key, variables);

async function api(path, options = {}) {
  const init = { ...options, headers: { ...(options.headers || {}) } };
  if (options.body && typeof options.body !== "string") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, init);
  let payload = {};
  try { payload = await response.json(); } catch (_) { /* empty response */ }
  if (!response.ok) throw new Error(i18n.localizeError(payload.error) || t("requestFailed", { status: response.status }));
  return payload;
}

function safeRedirect() {
  const value = new URLSearchParams(location.search).get("redirect") || "/";
  return value.startsWith("/") && !value.startsWith("//") ? value : "/";
}

async function initialize() {
  $("#member-login-form").addEventListener("submit", login);
  $("#member-logout").addEventListener("click", logout);
  $("#member-continue").href = safeRedirect();
  try {
    const status = await api("/api/member/status");
    renderStatus(status);
  } catch (error) {
    showError(error.message);
  }
}

function renderStatus(status) {
  const authenticated = Boolean(status.authenticated && status.member);
  $("#member-login-form").hidden = authenticated;
  $("#member-current").hidden = !authenticated;
  if (authenticated) $("#member-current-name").textContent = status.member.username;
}

async function login(event) {
  event.preventDefault();
  const button = $("#member-login-submit");
  button.disabled = true;
  showError("");
  try {
    await api("/api/member/login", {
      method: "POST",
      body: {
        username: $("#member-username").value.trim(),
        password: $("#member-password").value,
      },
    });
    location.assign(safeRedirect());
  } catch (error) {
    showError(error.message);
    button.disabled = false;
  }
}

async function logout() {
  await api("/api/member/logout", { method: "POST", body: {} });
  $("#member-password").value = "";
  renderStatus({ authenticated: false, member: null });
}

function showError(message) {
  $("#member-login-error").textContent = message || "";
}

initialize();
