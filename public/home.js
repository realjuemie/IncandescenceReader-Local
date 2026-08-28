"use strict";

const $ = (selector) => document.querySelector(selector);
const i18n = window.XGlowI18n;
const t = (key, variables) => i18n.t(key, variables);
let toastTimer = null;
let currentMember = null;
const HOME_LAYOUT_KEY = "incandescence-home-layout";
let homeLayout = readSavedLayout();

function readSavedLayout() {
  try {
    return localStorage.getItem(HOME_LAYOUT_KEY) === "compact" ? "compact" : "banner";
  } catch (_) {
    return "banner";
  }
}

function setHomeLayout(layout, persist = true) {
  homeLayout = layout === "compact" ? "compact" : "banner";
  const grid = $("#home-account-grid");
  grid.dataset.layout = homeLayout;
  document.body.classList.toggle("home-compact-layout", homeLayout === "compact");
  document.querySelectorAll("[data-home-layout]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.homeLayout === homeLayout));
  });
  if (persist) {
    try { localStorage.setItem(HOME_LAYOUT_KEY, homeLayout); } catch (_) { /* storage unavailable */ }
  }
}

function setupLayoutToggle() {
  document.querySelectorAll("[data-home-layout]").forEach((button) => {
    button.addEventListener("click", () => setHomeLayout(button.dataset.homeLayout));
  });
  setHomeLayout(homeLayout, false);
}

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

async function loadDirectory() {
  try {
    const [response, memberStatus] = await Promise.all([
      api("/api/public/accounts"), api("/api/member/status"),
    ]);
    currentMember = memberStatus.member || null;
    const accounts = [...response.items].sort((left, right) => {
      const leftTime = left.lastSyncedAt ? new Date(left.lastSyncedAt).getTime() : 0;
      const rightTime = right.lastSyncedAt ? new Date(right.lastSyncedAt).getTime() : 0;
      return rightTime - leftTime || left.username.localeCompare(right.username);
    });
    renderSummary(accounts);
    renderAccounts(accounts);
    renderMemberStatus(memberStatus);
    $("#home-refresh-time").textContent = t("refreshedAt", { time: formatClock(new Date()) });
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderMemberStatus(status) {
  const container = $("#home-member-status");
  document.body.classList.toggle("home-member-authenticated", Boolean(status.authenticated && status.member));
  container.replaceChildren();
  if (status.authenticated && status.member) {
    const identity = window.MemberNotifications.createIdentityButton(
      status.member, api, showToast,
    );
    const logout = document.createElement("button");
    logout.type = "button";
    logout.className = "member-status-action";
    logout.textContent = t("signOut");
    logout.addEventListener("click", async () => {
      await api("/api/member/logout", { method: "POST", body: {} });
      await loadDirectory();
    });
    const notifications = window.MemberNotifications.createButton(api, showToast);
    container.append(identity, notifications, logout);
  } else {
    const login = document.createElement("a");
    login.href = "/login?redirect=%2F";
    login.textContent = t("memberSignIn");
    container.append(login);
  }
}

function renderSummary(accounts) {
  const latest = accounts.map((item) => item.lastSyncedAt).filter(Boolean).sort().at(-1);
  const publicCount = accounts.filter((item) => item.isPublic).length;
  const privateCount = accounts.length - publicCount;
  const privateLabel = currentMember ? t("memberOnly") : t("adminOnly");
  $("#home-summary").textContent = accounts.length
    ? t("publicSummary", {
      publicCount,
      privatePart: privateCount ? t("privateSummaryPart", { privateCount, label: privateLabel }) : "",
      latestPart: latest ? t("latestUpdate", { time: relativeTime(latest) }) : t("awaitingFirstSync"),
    })
    : t("noPublicAccounts");
}

function renderAccounts(accounts) {
  const grid = $("#home-account-grid");
  grid.replaceChildren();
  if (!accounts.length) {
    const empty = document.createElement("div");
    empty.className = "home-empty";
    const title = document.createElement("strong");
    title.textContent = t("noReadableAccounts");
    const help = document.createElement("span");
    help.textContent = t("noReadableAccountsHelp");
    empty.append(title, help);
    grid.append(empty);
    return;
  }
  for (const account of accounts) grid.append(createAccountCard(account));
}

function createAccountCard(account) {
  const article = document.createElement("article");
  article.className = "home-account-card";
  const cover = document.createElement("div");
  cover.className = "home-card-cover";
  if (account.bannerUrl) {
    const banner = document.createElement("img");
    banner.src = account.bannerUrl;
    banner.alt = "";
    banner.loading = "lazy";
    cover.append(banner);
  }
  const avatar = document.createElement("div");
  avatar.className = "home-card-avatar";
  if (account.avatarUrl) {
    const image = document.createElement("img");
    image.src = account.avatarUrl;
    image.alt = "";
    image.loading = "lazy";
    avatar.append(image);
  } else avatar.textContent = (account.displayName || account.username).slice(0, 1).toUpperCase();
  const body = document.createElement("div");
  body.className = "home-card-body";
  const title = document.createElement("h3");
  title.textContent = account.displayName;
  if (!account.isPublic) {
    const privacy = document.createElement("span");
    privacy.className = "home-private-badge";
    privacy.textContent = currentMember ? t("memberOnly") : t("adminOnly");
    body.append(privacy);
  }
  const handle = document.createElement("div");
  handle.className = "home-card-handle";
  handle.textContent = `@${account.username}`;
  const bio = document.createElement("p");
  bio.textContent = account.bio || t("noBio");
  const meta = document.createElement("div");
  meta.className = "home-card-meta";
  meta.innerHTML = `<span><strong>${formatCount(account.tweetCount || 0)}</strong> ${t("contentCount", { count: "" }).trim()}</span><span><strong>${formatCount(account.mediaCount || 0)}</strong> ${t("mediaCount", { count: "" }).trim()}</span>`;
  const updated = document.createElement("div");
  updated.className = "home-card-updated";
  updated.classList.toggle("empty", !account.lastSyncedAt);
  updated.textContent = account.lastSyncedAt ? t("latestUpdate", { time: relativeTime(account.lastSyncedAt) }) : t("notUpdated");
  const actions = document.createElement("div");
  actions.className = "home-card-actions";
  const reader = document.createElement("a");
  reader.className = "primary-button button-link";
  reader.href = `/reader?account=${account.id}`;
  reader.setAttribute("aria-label", t("readAccountAria", { name: account.displayName }));
  reader.innerHTML = `<span class="home-action-wide">${t("readLocal")}</span><span class="home-action-compact">${t("readShort")}</span>`;
  const official = document.createElement("a");
  official.className = "secondary-button button-link";
  official.href = `https://x.com/${encodeURIComponent(account.username)}`;
  official.target = "_blank";
  official.rel = "noopener noreferrer";
  official.setAttribute("aria-label", t("officialAria", { name: account.displayName }));
  official.innerHTML = `<span class="home-action-wide">${t("officialProfile")}</span><span class="home-action-compact">${t("officialShort")}</span>`;
  actions.append(reader, official);
  body.append(title, handle, bio, meta, updated, actions);
  article.append(cover, avatar, body);
  return article;
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

function formatCount(value) {
  const number = Number(value || 0);
  return new Intl.NumberFormat(i18n.localeTag(), { notation: "compact", maximumFractionDigits: 1 }).format(number);
}

function formatClock(date) {
  return new Intl.DateTimeFormat(i18n.localeTag(), { hour: "2-digit", minute: "2-digit" }).format(date);
}

function showToast(message, error = false) {
  const toast = $("#toast");
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  toastTimer = setTimeout(() => toast.classList.remove("show"), 4200);
}

setupLayoutToggle();
loadDirectory();
window.addEventListener("xglow:localechange", loadDirectory);
window.setInterval(loadDirectory, 30000);
