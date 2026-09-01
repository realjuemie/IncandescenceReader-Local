"use strict";

(() => {
  const THEME_KEY = "xglow-theme";
  const TG_VARS = [
    "--tg-bg",
    "--tg-text",
    "--tg-hint",
    "--tg-link",
    "--tg-button",
    "--tg-button-text",
    "--tg-secondary-bg",
    "--tg-header-bg",
    "--tg-section-bg",
    "--tg-subtitle",
  ];
  const telegram = window.Telegram?.WebApp;
  const state = { active: Boolean(telegram?.initData), authenticated: false, role: "guest" };

  function temporaryShareToken() {
    if (!telegram?.initData) return "";
    const startParam = String(
      new URLSearchParams(window.location.search).get("tgWebAppStartParam") || "",
    );
    const match = /^share_([A-Za-z0-9_-]{32,256})$/.exec(startParam);
    return match ? match[1] : "";
  }

  function savedTheme() {
    try {
      const value = localStorage.getItem(THEME_KEY);
      if (value === "dark" || value === "light") return value;
    } catch (_) { /* storage unavailable */ }
    return "";
  }

  function systemScheme() {
    if (telegram?.initData) return telegram.colorScheme === "dark" ? "dark" : "light";
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } catch (_) {
      return "light";
    }
  }

  function currentScheme() {
    return savedTheme() || systemScheme();
  }

  function paintToggles(scheme) {
    const dark = scheme === "dark";
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-pressed", String(dark));
      button.setAttribute("aria-label", dark ? "切换为浅色模式" : "切换为深色模式");
      button.title = dark ? "浅色模式" : "深色模式";
      const icon = button.querySelector("[data-theme-icon]");
      const label = button.querySelector("[data-theme-label]");
      if (icon) icon.textContent = dark ? "☀" : "☾";
      if (label) label.textContent = dark ? "亮" : "暗";
    });
  }

  function applyTheme() {
    const scheme = currentScheme();
    const locked = Boolean(savedTheme());
    document.documentElement.dataset.theme = scheme;
    document.documentElement.style.colorScheme = scheme;
    if (telegram?.initData) {
      document.documentElement.dataset.telegramTheme = telegram.colorScheme === "dark" ? "dark" : "light";
      document.documentElement.classList.add("telegram-mini-app");
      document.body?.classList.add("telegram-mini-app");
    }
    let meta = document.querySelector('meta[name="color-scheme"]');
    if (!meta) {
      meta = document.createElement("meta");
      meta.setAttribute("name", "color-scheme");
      document.head.appendChild(meta);
    }
    meta.setAttribute("content", scheme);
    const root = document.documentElement.style;
    TG_VARS.forEach((name) => root.removeProperty(name));
    if (!locked && telegram?.initData) {
      const colors = telegram.themeParams || {};
      const map = {
        "--tg-bg": colors.bg_color,
        "--tg-text": colors.text_color,
        "--tg-hint": colors.hint_color,
        "--tg-link": colors.link_color,
        "--tg-button": colors.button_color,
        "--tg-button-text": colors.button_text_color,
        "--tg-secondary-bg": colors.secondary_bg_color,
        "--tg-header-bg": colors.header_bg_color,
        "--tg-section-bg": colors.section_bg_color,
        "--tg-subtitle": colors.subtitle_text_color,
      };
      Object.entries(map).forEach(([name, value]) => {
        if (value) root.setProperty(name, value);
      });
    }
    paintToggles(scheme);
    window.dispatchEvent(new CustomEvent("xglow:theme", { detail: { scheme, locked } }));
  }

  function toggleTheme() {
    const next = currentScheme() === "dark" ? "light" : "dark";
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* storage unavailable */ }
    applyTheme();
  }

  async function authenticate() {
    applyTheme();
    if (!telegram?.initData) return state;
    telegram.ready();
    telegram.expand();
    telegram.disableVerticalSwipes?.();
    telegram.onEvent?.("themeChanged", applyTheme);
    const shareToken = temporaryShareToken();
    if (shareToken && window.location.pathname === "/") {
      state.active = true;
      state.redirecting = true;
      window.location.replace(`/s/${encodeURIComponent(shareToken)}`);
      return state;
    }
    try {
      const response = await fetch("/api/telegram/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: telegram.initData }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || `Telegram auth ${response.status}`);
      Object.assign(state, payload, { active: true });
      document.body?.classList.toggle("telegram-pending", payload.role === "pending");
      window.dispatchEvent(new CustomEvent("xglow:telegramauth", { detail: state }));
    } catch (error) {
      state.error = error.message;
      window.dispatchEvent(new CustomEvent("xglow:telegramerror", { detail: state }));
    }
    return state;
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-theme-toggle]")) toggleTheme();
  });

  try {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
      if (!savedTheme() && !telegram?.initData) applyTheme();
    });
  } catch (_) { /* matchMedia unsupported */ }

  window.XGlowTheme = { apply: applyTheme, toggle: toggleTheme };
  window.XGlowTelegram = { state, ready: authenticate(), webApp: telegram || null };
})();
