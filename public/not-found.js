"use strict";

(() => {
  if (!location.pathname.startsWith("/reader")) return;
  const render = () => {
    const i18n = window.XGlowI18n;
    document.title = i18n.locale === "en" ? "XGlow · Account unavailable" : "X拾光 · 账号不存在";
    document.querySelector("#not-found-title").textContent = i18n.t("readerAccountNotFound");
    document.querySelector("#not-found-description").textContent = i18n.t("readerAccountNotFoundHelp");
  };
  render();
  window.addEventListener("xglow:localechange", render);
})();
