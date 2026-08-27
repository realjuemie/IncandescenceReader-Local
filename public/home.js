"use strict";

const $ = (selector) => document.querySelector(selector);
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
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
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
    $("#home-refresh-time").textContent = `页面刷新于 ${formatClock(new Date())}`;
  } catch (error) {
    showToast(error.message, true);
  }
}

function renderMemberStatus(status) {
  const container = $("#home-member-status");
  container.replaceChildren();
  if (status.authenticated && status.member) {
    const name = document.createElement("span");
    name.textContent = `会员 ${status.member.username}`;
    const logout = document.createElement("button");
    logout.type = "button";
    logout.className = "member-status-action";
    logout.textContent = "退出";
    logout.addEventListener("click", async () => {
      await api("/api/member/logout", { method: "POST", body: {} });
      await loadDirectory();
    });
    const notifications = window.MemberNotifications.createButton(api, showToast);
    container.append(name, notifications, logout);
  } else {
    const login = document.createElement("a");
    login.href = "/login?redirect=%2F";
    login.textContent = "会员登录";
    container.append(login);
  }
}

function renderSummary(accounts) {
  const latest = accounts.map((item) => item.lastSyncedAt).filter(Boolean).sort().at(-1);
  const publicCount = accounts.filter((item) => item.isPublic).length;
  const privateCount = accounts.length - publicCount;
  const privateLabel = currentMember ? "会员专属" : "仅管理可见";
  $("#home-summary").textContent = accounts.length
    ? `${publicCount} 个公开账号${privateCount ? ` · ${privateCount} 个${privateLabel}` : ""} · ${latest ? `最近更新 ${relativeTime(latest)}` : "等待首次抓取"}`
    : "管理员尚未添加公开账号";
}

function renderAccounts(accounts) {
  const grid = $("#home-account-grid");
  grid.replaceChildren();
  if (!accounts.length) {
    const empty = document.createElement("div");
    empty.className = "home-empty";
    empty.innerHTML = "<strong>还没有可阅读的账号</strong><span>管理员添加账号并完成抓取后，会自动显示在这里。</span>";
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
    privacy.textContent = currentMember ? "会员专属" : "仅管理员可见";
    body.append(privacy);
  }
  const handle = document.createElement("div");
  handle.className = "home-card-handle";
  handle.textContent = `@${account.username}`;
  const bio = document.createElement("p");
  bio.textContent = account.bio || "暂无个人简介";
  const meta = document.createElement("div");
  meta.className = "home-card-meta";
  meta.innerHTML = `<span><strong>${formatCount(account.tweetCount || 0)}</strong> 条内容</span><span><strong>${formatCount(account.mediaCount || 0)}</strong> 个媒体</span>`;
  const updated = document.createElement("div");
  updated.className = "home-card-updated";
  updated.textContent = account.lastSyncedAt ? `最近更新 ${relativeTime(account.lastSyncedAt)}` : "尚未完成首次更新";
  const actions = document.createElement("div");
  actions.className = "home-card-actions";
  const reader = document.createElement("a");
  reader.className = "primary-button button-link";
  reader.href = `/reader?account=${account.id}`;
  reader.setAttribute("aria-label", `阅读 ${account.displayName} 的本站内容`);
  reader.innerHTML = '<span class="home-action-wide">阅读本站内容</span><span class="home-action-compact">阅读</span>';
  const official = document.createElement("a");
  official.className = "secondary-button button-link";
  official.href = `https://x.com/${encodeURIComponent(account.username)}`;
  official.target = "_blank";
  official.rel = "noopener noreferrer";
  official.setAttribute("aria-label", `打开 ${account.displayName} 的 X 官方主页`);
  official.innerHTML = '<span class="home-action-wide">X 官方主页 ↗</span><span class="home-action-compact">X 主页</span>';
  actions.append(reader, official);
  body.append(title, handle, bio, meta, updated, actions);
  article.append(cover, avatar, body);
  return article;
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

function formatCount(value) {
  const number = Number(value || 0);
  if (number >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (number >= 10000) return `${(number / 10000).toFixed(number >= 100000 ? 0 : 1)}万`;
  return new Intl.NumberFormat("zh-CN").format(number);
}

function formatClock(date) {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
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
window.setInterval(loadDirectory, 30000);
