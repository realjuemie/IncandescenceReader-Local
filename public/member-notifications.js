"use strict";

(() => {
  const i18n = window.XGlowI18n;
  const t = (key, variables) => i18n.t(key, variables);
  let notificationDialog = null;
  let passwordDialog = null;
  let currentApi = null;
  let currentToast = null;
  let settings = null;

  function createButton(api, showToast) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "member-status-action";
    button.textContent = t("notification");
    button.addEventListener("click", () => open(api, showToast));
    return button;
  }

  function createIdentityButton(member, api, showToast) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "member-status-action member-id-action";
    button.textContent = i18n.locale === "en" ? `ID: ${member.username}` : `ID：${member.username}`;
    button.title = t("changePasswordTitle");
    button.setAttribute("aria-label", t("memberIdAria", { id: member.username }));
    button.addEventListener("click", () => openPassword(member, api, showToast));
    return button;
  }

  function ensureDialog() {
    if (notificationDialog) return notificationDialog;
    notificationDialog = document.createElement("dialog");
    notificationDialog.className = "member-notification-dialog";
    notificationDialog.innerHTML = `
      <form method="dialog" class="member-notification-card" id="member-notification-form">
        <header>
          <div><span class="eyebrow">PERSONAL ALERTS</span><h2>${i18n.locale === "en" ? "My notifications" : "我的通知"}</h2></div>
          <button type="button" class="member-notification-close" aria-label="${i18n.locale === "en" ? "Close" : "关闭"}">×</button>
        </header>
        <p class="member-notification-intro">${t("personalAlertIntro")}</p>
        <label class="member-notification-toggle"><input type="checkbox" id="member-bark-enabled"> ${t("enableMyAlerts")}</label>
        <label class="member-notification-toggle member-telegram-toggle"><input type="checkbox" id="member-telegram-enabled"> ${i18n.locale === "en" ? "Send the same alerts through Telegram" : "同时通过 Telegram 接收这些通知"}</label>
        <div class="member-telegram-status-row"><p class="member-telegram-state" id="member-telegram-state"></p><button type="button" class="text-button" id="member-telegram-test">${i18n.locale === "en" ? "Test Telegram" : "测试 Telegram"}</button></div>
        <div class="member-notification-fields">
          <label>${i18n.locale === "en" ? "Bark server URL" : "Bark 服务器地址"}<input type="url" id="member-bark-server" autocomplete="off" spellcheck="false" placeholder="https://api.day.app"></label>
          <label>Device Key<input type="password" id="member-bark-key" autocomplete="new-password" spellcheck="false" placeholder="${t("copyFromBark")}"></label>
          <label>${i18n.locale === "en" ? "Notification group" : "通知分组"}<input type="text" id="member-bark-group" maxlength="64" placeholder="XGlow"></label>
        </div>
        <fieldset class="member-notification-accounts">
          <legend>${t("chooseAlertAccounts")}</legend>
          <div id="member-bark-accounts"></div>
        </fieldset>
        <div class="member-notification-result" id="member-bark-result" role="status"></div>
        <footer>
          <button type="button" class="danger-button" id="member-bark-clear">${i18n.locale === "en" ? "Clear key" : "清除密钥"}</button>
          <span></span>
          <button type="button" class="secondary-button" id="member-bark-test">${t("test")}</button>
          <button type="submit" class="primary-button" id="member-bark-save">${t("save")}</button>
        </footer>
      </form>`;
    document.body.append(notificationDialog);
    notificationDialog.addEventListener("click", (event) => {
      if (event.target === notificationDialog) notificationDialog.close();
    });
    notificationDialog.querySelector(".member-notification-close").addEventListener(
      "click", () => notificationDialog.close(),
    );
    notificationDialog.querySelector("#member-notification-form").addEventListener("submit", save);
    notificationDialog.querySelector("#member-bark-test").addEventListener("click", test);
    notificationDialog.querySelector("#member-telegram-test").addEventListener("click", testTelegram);
    notificationDialog.querySelector("#member-bark-clear").addEventListener("click", clearKey);
    return notificationDialog;
  }

  async function open(api, showToast) {
    currentApi = api;
    currentToast = showToast;
    const modal = ensureDialog();
    setResult(t("loadingNotifications"));
    modal.showModal();
    try {
      settings = await currentApi("/api/member/notifications");
      fill();
    } catch (error) {
      setResult(error.message, true);
    }
  }

  function fill() {
    notificationDialog.querySelector("#member-bark-enabled").checked = Boolean(settings.enabled);
    const telegramToggle = notificationDialog.querySelector("#member-telegram-enabled");
    telegramToggle.checked = Boolean(settings.telegramEnabled);
    telegramToggle.disabled = !settings.telegramBound;
    const telegramState = notificationDialog.querySelector("#member-telegram-state");
    telegramState.textContent = settings.telegramBound
      ? (i18n.locale === "en"
        ? `Bound to Telegram ${settings.telegramUserId}${settings.telegramUsername ? ` (@${settings.telegramUsername})` : ""}`
        : `已绑定 Telegram ${settings.telegramUserId}${settings.telegramUsername ? `（@${settings.telegramUsername}）` : ""}`)
      : (i18n.locale === "en" ? "Open this site from the Telegram Mini App to bind your identity." : "请从 Telegram Mini App 打开本站完成身份绑定。 ");
    notificationDialog.querySelector("#member-telegram-test").hidden = !settings.telegramBound;
    notificationDialog.querySelector("#member-bark-server").value = settings.serverUrl || "https://api.day.app";
    const key = notificationDialog.querySelector("#member-bark-key");
    key.value = "";
    key.placeholder = settings.deviceKeyConfigured ? t("savedKeyShort") : t("copyFromBark");
    notificationDialog.querySelector("#member-bark-group").value = settings.group || "XGlow";
    const selected = new Set(settings.accountIds || []);
    const accounts = notificationDialog.querySelector("#member-bark-accounts");
    accounts.replaceChildren();
    for (const account of settings.availableAccounts || []) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = String(account.id);
      input.checked = selected.has(account.id);
      const privacy = account.isPublic ? t("public") : t("memberOnly");
      const suffix = i18n.locale === "en" ? ` (${privacy})` : `（${privacy}）`;
      label.append(input, document.createTextNode(` ${account.displayName} · @${account.username}${suffix}`));
      accounts.append(label);
    }
    if (!(settings.availableAccounts || []).length) {
      const empty = document.createElement("p");
      empty.textContent = t("noSubscriptions");
      accounts.append(empty);
    }
    notificationDialog.querySelector("#member-bark-clear").hidden = !settings.deviceKeyConfigured;
    setResult(settings.deviceKeyConfigured ? t("keySavedSubscriptions") : t("enterBarkKey"), false);
  }

  async function save(event) {
    event.preventDefault();
    const button = notificationDialog.querySelector("#member-bark-save");
    const key = notificationDialog.querySelector("#member-bark-key").value.trim();
    const body = {
      enabled: notificationDialog.querySelector("#member-bark-enabled").checked,
      telegramEnabled: notificationDialog.querySelector("#member-telegram-enabled").checked,
      serverUrl: notificationDialog.querySelector("#member-bark-server").value.trim(),
      group: notificationDialog.querySelector("#member-bark-group").value.trim(),
      accountIds: [...notificationDialog.querySelectorAll("#member-bark-accounts input:checked")]
        .map((input) => Number(input.value)),
    };
    if (key) body.deviceKey = key;
    button.disabled = true;
    setResult(t("saving"));
    try {
      settings = await currentApi("/api/member/notifications", { method: "PUT", body });
      fill();
      setResult(settings.enabled ? t("memberAlertsEnabled") : t("memberAlertsDisabled"), false);
      currentToast?.(t("memberAlertsSaved"));
    } catch (error) {
      setResult(error.message, true);
      currentToast?.(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function test() {
    const key = notificationDialog.querySelector("#member-bark-key").value.trim();
    if (key) return setResult(t("unsavedMemberKey"), true);
    if (!settings?.deviceKeyConfigured) return setResult(t("saveMemberKeyFirst"), true);
    const button = notificationDialog.querySelector("#member-bark-test");
    button.disabled = true;
    setResult(t("sendingTest"));
    try {
      const result = await currentApi("/api/member/notifications/test", { method: "POST", body: {} });
      setResult(t("testDelivered", { status: result.status, elapsed: result.elapsedMs }), false);
    } catch (error) {
      setResult(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function testTelegram() {
    if (!settings?.telegramBound) return setResult(i18n.locale === "en" ? "Bind Telegram first." : "请先绑定 Telegram。", true);
    const button = notificationDialog.querySelector("#member-telegram-test");
    button.disabled = true;
    setResult(i18n.locale === "en" ? "Sending Telegram test…" : "正在发送 Telegram 测试…");
    try {
      await currentApi("/api/member/notifications/test", {
        method: "POST", body: { channel: "telegram" },
      });
      setResult(i18n.locale === "en" ? "Telegram test delivered." : "Telegram 测试通知已送达。", false);
    } catch (error) {
      setResult(error.message, true);
    } finally { button.disabled = false; }
  }

  async function clearKey() {
    if (!settings?.deviceKeyConfigured || !window.confirm(t("confirmClearMemberKey"))) return;
    const selected = [...notificationDialog.querySelectorAll("#member-bark-accounts input:checked")]
      .map((input) => Number(input.value));
    try {
      settings = await currentApi("/api/member/notifications", {
        method: "PUT",
        body: {
          enabled: false,
          telegramEnabled: notificationDialog.querySelector("#member-telegram-enabled").checked,
          serverUrl: notificationDialog.querySelector("#member-bark-server").value.trim(),
          group: notificationDialog.querySelector("#member-bark-group").value.trim(),
          accountIds: selected,
          clearDeviceKey: true,
        },
      });
      fill();
      setResult(t("memberKeyCleared"), false);
    } catch (error) {
      setResult(error.message, true);
    }
  }

  function setResult(message, error = false) {
    if (!notificationDialog) return;
    const node = notificationDialog.querySelector("#member-bark-result");
    node.textContent = message || "";
    node.classList.toggle("bad", error);
  }

  function ensurePasswordDialog() {
    if (passwordDialog) return passwordDialog;
    passwordDialog = document.createElement("dialog");
    passwordDialog.className = "member-notification-dialog member-password-dialog";
    passwordDialog.innerHTML = `
      <form class="member-notification-card" id="member-password-form">
        <header>
          <div><span class="eyebrow">MEMBER SECURITY</span><h2>${t("changeMemberPassword")}</h2></div>
          <button type="button" class="member-notification-close" aria-label="${i18n.locale === "en" ? "Close" : "关闭"}">×</button>
        </header>
        <p class="member-notification-intro">${t("currentMemberIntro")}<strong id="member-password-id"></strong>${t("passwordChangeWarning")}</p>
        <div class="member-notification-fields member-password-fields">
          <label>${t("currentPassword")}<input type="password" id="member-current-password" autocomplete="current-password" maxlength="256" required></label>
          <label>${t("newPassword")}<input type="password" id="member-new-password" autocomplete="new-password" minlength="8" maxlength="256" required></label>
          <label>${t("confirmNewPassword")}<input type="password" id="member-confirm-password" autocomplete="new-password" minlength="8" maxlength="256" required></label>
        </div>
        <div class="member-notification-result" id="member-password-result" role="status"></div>
        <footer class="member-password-footer">
          <button type="button" class="secondary-button" id="member-password-cancel">${t("cancel")}</button>
          <button type="submit" class="primary-button" id="member-password-save">${t("updatePassword")}</button>
        </footer>
      </form>`;
    document.body.append(passwordDialog);
    passwordDialog.addEventListener("click", (event) => {
      if (event.target === passwordDialog) passwordDialog.close();
    });
    passwordDialog.querySelector(".member-notification-close").addEventListener(
      "click", () => passwordDialog.close(),
    );
    passwordDialog.querySelector("#member-password-cancel").addEventListener(
      "click", () => passwordDialog.close(),
    );
    passwordDialog.querySelector("#member-password-form").addEventListener(
      "submit", savePassword,
    );
    return passwordDialog;
  }

  function openPassword(member, api, showToast) {
    currentApi = api;
    currentToast = showToast;
    const modal = ensurePasswordDialog();
    modal.querySelector("#member-password-id").textContent = member.username;
    modal.querySelector("#member-current-password").value = "";
    modal.querySelector("#member-new-password").value = "";
    modal.querySelector("#member-confirm-password").value = "";
    setPasswordResult("");
    modal.showModal();
    modal.querySelector("#member-current-password").focus();
  }

  async function savePassword(event) {
    event.preventDefault();
    const currentPassword = passwordDialog.querySelector("#member-current-password").value;
    const newPassword = passwordDialog.querySelector("#member-new-password").value;
    const confirmation = passwordDialog.querySelector("#member-confirm-password").value;
    if (newPassword !== confirmation) {
      setPasswordResult(t("newPasswordMismatch"), true);
      return;
    }
    const button = passwordDialog.querySelector("#member-password-save");
    button.disabled = true;
    setPasswordResult(t("updatingPassword"));
    try {
      await currentApi("/api/member/password", {
        method: "PUT",
        body: { currentPassword, newPassword },
      });
      passwordDialog.close();
      currentToast?.(t("passwordUpdated"));
    } catch (error) {
      setPasswordResult(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  function setPasswordResult(message, error = false) {
    if (!passwordDialog) return;
    const node = passwordDialog.querySelector("#member-password-result");
    node.textContent = message || "";
    node.classList.toggle("bad", error);
  }

  window.addEventListener("xglow:localechange", () => {
    notificationDialog?.remove();
    passwordDialog?.remove();
    notificationDialog = null;
    passwordDialog = null;
  });

  window.MemberNotifications = { createButton, createIdentityButton };
})();
