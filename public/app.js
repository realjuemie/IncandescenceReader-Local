"use strict";

const $ = (selector) => document.querySelector(selector);
const state = {
  accounts: [], selectedId: null, cursor: null, kind: "all", query: "",
  year: "", month: "", availableMonths: [], loading: false,
  member: null, toastTimer: null, searchTimer: null, lightboxReturnFocus: null,
  nestedTweetIds: new Set(),
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
  if (!response.ok) throw new Error(payload.error || `请求失败 (${response.status})`);
  return payload;
}

function currentAccount() {
  return state.accounts.find((item) => item.id === state.selectedId) || null;
}

async function initialize() {
  bindEvents();
  try {
    const [response, memberStatus] = await Promise.all([
      api("/api/public/accounts"), api("/api/member/status"),
    ]);
    state.accounts = response.items;
    state.member = memberStatus.member || null;
    renderMemberStatus();
    const requested = Number(new URLSearchParams(location.search).get("account"));
    const remembered = Number(localStorage.getItem("reader-account-id"));
    if (state.accounts.some((item) => item.id === requested)) state.selectedId = requested;
    else if (state.accounts.some((item) => item.id === remembered)) state.selectedId = remembered;
    else state.selectedId = state.accounts[0]?.id || null;
    renderAccounts();
    await selectAccount(state.selectedId);
  } catch (error) {
    showToast(error.message, true);
  }
  window.setInterval(refreshPublicContent, 30000);
}

function bindEvents() {
  $("#load-more").addEventListener("click", () => loadTweets(true));
  $("#timeline-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-kind]");
    if (!button || button.dataset.kind === state.kind) return;
    state.kind = button.dataset.kind;
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    loadTweets(false);
  });
  $("#tweet-search").addEventListener("input", (event) => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(() => {
      state.query = event.target.value.trim();
      loadTweets(false);
    }, 280);
  });
  $("#filter-year").addEventListener("change", (event) => {
    state.year = event.target.value;
    state.month = "";
    renderDateFilters();
    loadTweets(false);
  });
  $("#filter-month").addEventListener("change", (event) => {
    state.month = event.target.value;
    renderDateFilters();
    loadTweets(false);
  });
  $("#reset-date-filter").addEventListener("click", () => {
    state.year = "";
    state.month = "";
    renderDateFilters();
    loadTweets(false);
  });
  $("#timeline").addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-lightbox-url]");
    if (trigger) openLightbox(trigger.dataset.lightboxUrl, trigger.dataset.lightboxAlt || "内容图片", trigger);
  });
  $("#lightbox-close").addEventListener("click", closeLightbox);
  $("#image-lightbox").addEventListener("click", (event) => {
    if (event.target === $("#image-lightbox")) closeLightbox();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("#image-lightbox").hidden) closeLightbox();
  });
  $("#open-sidebar").addEventListener("click", () => toggleSidebar(true));
  $("#close-sidebar").addEventListener("click", () => toggleSidebar(false));
  $("#sidebar-scrim").addEventListener("click", () => toggleSidebar(false));
}

function renderAccounts() {
  const list = $("#account-list");
  list.replaceChildren();
  for (const account of state.accounts) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `account-item${account.id === state.selectedId ? " active" : ""}`;
    button.append(createAvatar(account, "account-avatar"));
    const copy = document.createElement("span");
    copy.className = "account-copy";
    const name = document.createElement("strong");
    name.textContent = account.displayName;
    const handle = document.createElement("small");
    handle.textContent = `@${account.username} · ${account.tweetCount || 0} 条`;
    copy.append(name, handle);
    button.append(copy);
    if (!account.isPublic) {
      const privacy = document.createElement("span");
      privacy.className = "account-privacy";
      privacy.textContent = state.member ? "会员可见" : "仅管理";
      button.append(privacy);
    }
    button.addEventListener("click", () => selectAccount(account.id));
    list.append(button);
  }
}

function renderMemberStatus() {
  const container = $("#reader-member-status");
  container.replaceChildren();
  if (state.member) {
    const copy = document.createElement("span");
    copy.textContent = `会员 ${state.member.username}`;
    const logout = document.createElement("button");
    logout.type = "button";
    logout.textContent = "退出";
    logout.addEventListener("click", async () => {
      await api("/api/member/logout", { method: "POST", body: {} });
      location.reload();
    });
    const notifications = window.MemberNotifications.createButton(api, showToast);
    container.append(copy, notifications, logout);
  } else {
    const login = document.createElement("a");
    login.href = `/login?redirect=${encodeURIComponent(location.pathname + location.search)}`;
    login.textContent = "会员登录";
    container.append(login);
  }
}

async function selectAccount(accountId) {
  state.selectedId = accountId || null;
  if (state.selectedId) {
    localStorage.setItem("reader-account-id", String(state.selectedId));
    const url = new URL(location.href);
    url.searchParams.set("account", String(state.selectedId));
    history.replaceState(null, "", url);
  }
  renderAccounts();
  renderProfile();
  toggleSidebar(false);
  state.year = "";
  state.month = "";
  state.availableMonths = [];
  renderDateFilters();
  if (state.selectedId) {
    await loadAvailableMonths();
    await loadTweets(false);
  }
}

async function loadAvailableMonths() {
  try {
    const response = await api(`/api/public/accounts/${state.selectedId}/months`);
    state.availableMonths = response.items || [];
    renderDateFilters();
  } catch (error) {
    state.availableMonths = [];
    renderDateFilters();
    showToast(error.message, true);
  }
}

function renderDateFilters() {
  const yearSelect = $("#filter-year");
  const monthSelect = $("#filter-month");
  const years = [...new Set(state.availableMonths.map((item) => String(item.year)))];
  if (state.year && !years.includes(state.year)) {
    state.year = "";
    state.month = "";
  }
  yearSelect.replaceChildren(new Option("全部年份", ""));
  for (const year of years) {
    const count = state.availableMonths
      .filter((item) => String(item.year) === year)
      .reduce((total, item) => total + Number(item.count || 0), 0);
    yearSelect.add(new Option(`${year}年 · ${count}条`, year));
  }
  yearSelect.value = state.year;

  const available = state.year
    ? state.availableMonths.filter((item) => String(item.year) === state.year)
    : [];
  const validMonths = available.map((item) => String(item.month));
  if (state.month && !validMonths.includes(state.month)) state.month = "";
  monthSelect.replaceChildren(new Option("全部月份", ""));
  for (const item of available) {
    monthSelect.add(new Option(`${item.month}月 · ${item.count}条`, String(item.month)));
  }
  monthSelect.value = state.month;
  monthSelect.disabled = !state.year;
  $("#reset-date-filter").hidden = !state.year;
}

function renderProfile() {
  const account = currentAccount();
  $("#empty-state").hidden = Boolean(account);
  $("#reader").hidden = !account;
  if (!account) return;
  $("#profile-name").textContent = account.displayName;
  $("#profile-handle").textContent = `@${account.username}`;
  $("#profile-bio").textContent = account.bio || "暂无个人简介";
  $("#profile-avatar").replaceChildren(createAvatar(account));
  const banner = $("#profile-banner");
  if (account.bannerUrl) {
    banner.src = account.bannerUrl;
    banner.hidden = false;
  } else {
    banner.hidden = true;
    banner.removeAttribute("src");
  }
  const metrics = account.metrics || {};
  $("#profile-meta").innerHTML = [
    `<span><strong>${formatCount(account.tweetCount || 0)}</strong> 本站内容</span>`,
    `<span><strong>${formatCount(account.mediaCount || 0)}</strong> 本站媒体</span>`,
    metrics.followers != null ? `<span><strong>${formatCount(metrics.followers)}</strong> 关注者</span>` : "",
  ].join("");
  $("#public-updated").textContent = account.lastSyncedAt ? `更新于 ${relativeTime(account.lastSyncedAt)}` : "等待首次更新";
}

function createAvatar(account, className = "") {
  if (account.avatarUrl) {
    const image = document.createElement("img");
    image.src = account.avatarUrl;
    image.alt = "";
    if (className) image.className = className;
    return image;
  }
  const fallback = document.createElement("span");
  fallback.className = className ? `avatar-fallback ${className}` : "avatar-fallback";
  fallback.textContent = (account.displayName || account.username || "?").slice(0, 1).toUpperCase();
  return fallback;
}

async function loadTweets(append) {
  if (!state.selectedId || state.loading) return;
  state.loading = true;
  $("#timeline-loading").hidden = false;
  $("#load-more").hidden = true;
  if (!append) {
    state.cursor = null;
    state.nestedTweetIds.clear();
    $("#timeline").replaceChildren();
  }
  const params = new URLSearchParams({ limit: "30", kind: state.kind });
  if (state.query) params.set("q", state.query);
  if (state.year) params.set("year", state.year);
  if (state.month) params.set("month", state.month);
  if (append && state.cursor) params.set("cursor", state.cursor);
  try {
    const page = await api(`/api/public/accounts/${state.selectedId}/tweets?${params}`);
    for (const tweet of page.items) {
      if (!tweet.repliedTo?.id) continue;
      state.nestedTweetIds.add(String(tweet.repliedTo.id));
      document.querySelector(`[data-tweet-id="${tweet.repliedTo.id}"]`)?.remove();
    }
    for (const tweet of page.items) {
      if (state.nestedTweetIds.has(String(tweet.id))) continue;
      $("#timeline").append(renderTweet(tweet));
    }
    state.cursor = page.nextCursor;
    $("#load-more").hidden = !state.cursor;
    if (!$("#timeline").children.length) {
      const empty = document.createElement("div");
      empty.className = "timeline-empty";
      empty.textContent = state.query || state.year
        ? "当前搜索或时间范围内没有内容"
        : "这个账号还没有已抓取的内容";
      $("#timeline").append(empty);
    }
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.loading = false;
    $("#timeline-loading").hidden = true;
  }
}

function renderTweet(tweet) {
  const article = document.createElement("article");
  article.className = tweet.isReply ? "tweet-card reply-tweet-card" : "tweet-card";
  article.dataset.tweetId = String(tweet.id);
  if (!tweet.isReply) {
    const parts = renderTweetEntry(tweet);
    article.append(parts.avatar, parts.main);
    return article;
  }

  const frame = document.createElement("div");
  frame.className = "reply-frame";
  if (tweet.repliedTo) {
    const parent = renderTweetEntry(tweet.repliedTo);
    const parentEntry = document.createElement("div");
    parentEntry.className = "reply-thread-entry reply-parent-entry";
    parentEntry.append(parent.avatar, parent.main);
    frame.append(parentEntry);
  }
  const reply = renderTweetEntry(tweet, { stripReplyTarget: true });
  reply.main.prepend(renderReplyContext(tweet));
  const replyEntry = document.createElement("div");
  replyEntry.className = "reply-thread-entry reply-current-entry";
  replyEntry.append(reply.avatar, reply.main);
  frame.append(replyEntry);
  article.append(frame);
  return article;
}

function renderTweetEntry(tweet, { stripReplyTarget = false } = {}) {
  const avatar = document.createElement("div");
  avatar.className = "tweet-avatar";
  avatar.append(createAvatar({
    avatarUrl: tweet.authorAvatarUrl,
    username: tweet.authorUsername,
    displayName: tweet.authorName,
  }));
  const main = document.createElement("div");
  main.className = "tweet-main";
  const head = document.createElement("div");
  head.className = "tweet-head";
  const name = document.createElement("a");
  name.className = "tweet-author-link";
  name.href = `https://x.com/${encodeURIComponent(tweet.authorUsername)}`;
  name.target = "_blank";
  name.rel = "noopener noreferrer";
  name.textContent = tweet.authorName;
  const handle = document.createElement("a");
  handle.className = "tweet-handle";
  handle.href = name.href;
  handle.target = "_blank";
  handle.rel = "noopener noreferrer";
  handle.textContent = `@${tweet.authorUsername}`;
  const time = document.createElement("a");
  time.className = "tweet-time";
  time.href = tweet.sourceUrl;
  time.target = "_blank";
  time.rel = "noopener noreferrer";
  time.textContent = `· ${formatDate(tweet.createdAt)}`;
  head.append(name, handle, time);
  if (tweet.isRepost) head.append(createBadge("转发"));
  else if (tweet.isQuote) head.append(createBadge("引用"));
  const text = document.createElement("div");
  text.className = "tweet-text";
  let displayText = String(tweet.text || "");
  if (stripReplyTarget && tweet.replyToUsername) {
    displayText = displayText.replace(
      new RegExp(`^@${tweet.replyToUsername}\\s*`, "i"), "",
    );
  }
  appendLinkedText(text, displayText, tweet.links || []);
  main.append(head, text);
  if (tweet.media?.length) main.append(renderMedia(tweet.media));
  if (tweet.quoted) main.append(renderQuote(tweet.quoted));
  main.append(renderMetrics(tweet.metrics || {}));
  return { avatar, main };
}

function renderReplyContext(tweet) {
  const context = document.createElement("div");
  context.className = "reply-context";
  context.append(document.createTextNode("回复给 "));
  if (tweet.replyToUsername) {
    const target = document.createElement("a");
    target.href = `https://x.com/${encodeURIComponent(tweet.replyToUsername)}`;
    target.target = "_blank";
    target.rel = "noopener noreferrer";
    target.textContent = `@${tweet.replyToUsername}`;
    context.append(target);
  } else {
    context.append(document.createTextNode("对话中的用户"));
  }
  return context;
}

function createBadge(label) {
  const badge = document.createElement("span");
  badge.className = "tweet-badge";
  badge.textContent = label;
  return badge;
}

function appendLinkedText(container, value, links) {
  const linkMap = new Map();
  for (const link of links) if (link.shortUrl) linkMap.set(link.shortUrl, link);
  const text = String(value || "");
  const regex = /(https?:\/\/[^\s]+|@[A-Za-z0-9_]{1,15})/g;
  let index = 0;
  for (const match of text.matchAll(regex)) {
    appendTextWithBreaks(container, text.slice(index, match.index));
    const raw = match[0];
    const mapped = linkMap.get(raw);
    const anchor = document.createElement("a");
    const mention = raw.startsWith("@") && !mapped;
    anchor.href = mention ? `https://x.com/${encodeURIComponent(raw.slice(1))}` : (mapped?.url || raw);
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    anchor.textContent = mapped?.display || raw;
    if (mention) anchor.className = "mention-link";
    container.append(anchor);
    index = match.index + raw.length;
  }
  appendTextWithBreaks(container, text.slice(index));
}

function appendTextWithBreaks(container, value) {
  String(value || "").split("\n").forEach((part, index) => {
    if (index) container.append(document.createElement("br"));
    container.append(document.createTextNode(part));
  });
}

function renderMedia(media) {
  const grid = document.createElement("div");
  grid.className = `media-grid count-${Math.min(media.length, 4)}`;
  for (const item of media.slice(0, 4)) {
    const wrap = document.createElement("div");
    wrap.className = "media-item";
    if (!item.url) {
      const error = document.createElement("div");
      error.className = "media-error";
      error.textContent = "媒体暂时不可用";
      wrap.append(error);
    } else if (item.type === "photo") {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "media-image-button";
      button.dataset.lightboxUrl = item.url;
      button.dataset.lightboxAlt = item.alt || "内容图片";
      button.setAttribute("aria-label", "放大查看图片");
      const image = document.createElement("img");
      image.src = item.url;
      image.alt = item.alt || "内容图片";
      image.loading = "lazy";
      button.append(image);
      wrap.append(button);
    } else {
      wrap.append(createIsolatedVideo(item, media.length === 1));
    }
    grid.append(wrap);
  }
  return grid;
}

function createIsolatedVideo(item, contain) {
  const host = document.createElement("div");
  host.className = `media-video-shell${contain ? " media-video-contain" : ""}`;

  // Keep third-party video download overlays out of the reader layout. Some
  // browser extensions inject fixed-position panels beside every visible
  // <video>; a closed shadow root preserves native controls without exposing
  // the element as part of the page DOM they scan.
  const root = host.attachShadow({ mode: "closed" });
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = "/video-player.css?v=4.10.2";

  const video = document.createElement("video");
  video.poster = item.previewUrl || "";
  video.controls = false;
  video.loop = item.type === "animated_gif";
  video.muted = item.type === "animated_gif";
  video.autoplay = item.type === "animated_gif";
  video.playsInline = true;
  video.preload = "none";
  video.setAttribute("controlslist", "nodownload");

  let started = false;
  const startPlayback = async () => {
    if (started) return;
    started = true;
    host.classList.add("media-video-started");
    video.controls = item.type !== "animated_gif";
    video.src = item.url;
    video.load();
    try { await video.play(); } catch (_) { /* native controls remain available */ }
  };

  const launch = document.createElement("button");
  launch.type = "button";
  launch.className = "video-launch";
  launch.setAttribute("aria-label", item.type === "animated_gif" ? "播放动图" : "播放视频");
  const launchIcon = document.createElement("span");
  launchIcon.className = "video-launch-icon";
  launchIcon.textContent = "▶";
  const launchText = document.createElement("span");
  launchText.className = "video-launch-text";
  launchText.textContent = item.type === "animated_gif" ? "动图" : "播放";
  launch.append(launchIcon, launchText);
  launch.addEventListener("click", startPlayback);

  const error = document.createElement("div");
  error.className = "video-error";
  error.textContent = "视频暂时无法播放";
  video.addEventListener("error", () => host.classList.add("media-video-error"));
  const controlsSlot = document.createElement("slot");
  root.append(stylesheet, video, controlsSlot, error);
  host.append(launch);

  // Animated posts retain their familiar autoplay behavior, but only when
  // they actually enter the viewport. Normal videos never request their MP4
  // until the visitor explicitly presses play.
  if (item.type === "animated_gif" && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      observer.disconnect();
      startPlayback();
    }, { rootMargin: "80px 0px", threshold: 0.05 });
    observer.observe(host);
  } else if (item.type === "animated_gif") {
    startPlayback();
  }
  return host;
}

function openLightbox(url, alt, trigger) {
  state.lightboxReturnFocus = trigger || null;
  const lightbox = $("#image-lightbox");
  const image = $("#lightbox-image");
  const caption = $("#lightbox-caption");
  image.src = url;
  image.alt = alt;
  caption.textContent = alt;
  caption.hidden = !alt || alt === "内容图片";
  lightbox.hidden = false;
  document.body.classList.add("lightbox-open");
  $("#lightbox-close").focus();
}

function closeLightbox() {
  const lightbox = $("#image-lightbox");
  if (lightbox.hidden) return;
  lightbox.hidden = true;
  $("#lightbox-image").removeAttribute("src");
  document.body.classList.remove("lightbox-open");
  state.lightboxReturnFocus?.focus();
  state.lightboxReturnFocus = null;
}

function renderQuote(quote) {
  const card = document.createElement("div");
  card.className = "quote-card";
  const link = document.createElement("a");
  link.href = quote.sourceUrl;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const strong = document.createElement("strong");
  strong.textContent = quote.authorName;
  link.append(strong, document.createTextNode(` @${quote.authorUsername}`));
  const text = document.createElement("p");
  appendLinkedText(text, quote.text, []);
  card.append(link, text);
  return card;
}

function renderMetrics(metrics) {
  const row = document.createElement("div");
  row.className = "tweet-metrics";
  for (const [icon, value] of [["↩", metrics.replies], ["↻", metrics.reposts], ["♡", metrics.likes], ["◉", metrics.views]]) {
    if (value == null) continue;
    const item = document.createElement("span");
    item.textContent = `${icon} ${formatCount(value)}`;
    row.append(item);
  }
  return row;
}

async function refreshPublicContent() {
  try {
    const previousId = state.selectedId;
    const previousSync = currentAccount()?.lastSyncedAt;
    const [response, memberStatus] = await Promise.all([
      api("/api/public/accounts"), api("/api/member/status"),
    ]);
    state.accounts = response.items;
    state.member = memberStatus.member || null;
    renderMemberStatus();
    if (!state.accounts.some((item) => item.id === state.selectedId)) state.selectedId = state.accounts[0]?.id || null;
    renderAccounts();
    renderProfile();
    if (state.selectedId !== previousId) {
      state.year = "";
      state.month = "";
      state.availableMonths = [];
      renderDateFilters();
      if (state.selectedId) {
        await loadAvailableMonths();
        await loadTweets(false);
      }
    } else if (currentAccount()?.lastSyncedAt && currentAccount().lastSyncedAt !== previousSync) {
      await loadAvailableMonths();
      await loadTweets(false);
    }
  } catch (_) { /* polling failures do not interrupt reading */ }
}

function toggleSidebar(open) {
  $("#sidebar").classList.toggle("open", open);
  $("#sidebar-scrim").classList.toggle("show", open);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
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

function showToast(message, error = false) {
  const toast = $("#toast");
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.classList.add("show");
  state.toastTimer = setTimeout(() => toast.classList.remove("show"), 4200);
}

initialize();
