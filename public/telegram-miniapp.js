"use strict";

(() => {
  const telegram = window.Telegram?.WebApp;
  const state = { active: Boolean(telegram?.initData), authenticated: false, role: "guest" };

  function temporaryShareToken() {
    if (!telegram?.initData) return "";
    // Telegram keeps initDataUnsafe.start_param for the lifetime of the WebView.
    // Only the launch URL carries tgWebAppStartParam, so using the query value
    // prevents a later visit to "/" from reopening the temporary share.
    const startParam = String(
      new URLSearchParams(window.location.search).get("tgWebAppStartParam") || "",
    );
    const match = /^share_([A-Za-z0-9_-]{32,256})$/.exec(startParam);
    return match ? match[1] : "";
  }

  function applyTheme() {
    if (!telegram) return;
    document.documentElement.dataset.telegramTheme = telegram.colorScheme || "light";
    document.documentElement.classList.add("telegram-mini-app");
    document.body?.classList.add("telegram-mini-app");
    const colors = telegram.themeParams || {};
    if (colors.bg_color) document.documentElement.style.setProperty("--tg-bg", colors.bg_color);
    if (colors.text_color) document.documentElement.style.setProperty("--tg-text", colors.text_color);
    if (colors.hint_color) document.documentElement.style.setProperty("--tg-hint", colors.hint_color);
  }

  async function authenticate() {
    if (!telegram?.initData) return state;
    telegram.ready();
    telegram.expand();
    telegram.disableVerticalSwipes?.();
    applyTheme();
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

  window.XGlowTelegram = { state, ready: authenticate(), webApp: telegram || null };
})();
