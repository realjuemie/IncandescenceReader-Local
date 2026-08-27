"use strict";

(() => {
  let dialog = null;
  let currentApi = null;
  let currentToast = null;
  let settings = null;

  function createButton(api, showToast) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "member-status-action";
    button.textContent = "通知";
    button.addEventListener("click", () => open(api, showToast));
    return button;
  }

  function ensureDialog() {
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.className = "member-notification-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="member-notification-card" id="member-notification-form">
        <header>
          <div><span class="eyebrow">PERSONAL ALERTS</span><h2>我的 Bark 通知</h2></div>
          <button class="member-notification-close" value="cancel" aria-label="关闭">×</button>
        </header>
        <p class="member-notification-intro">只向你的 Bark 推送所选账号的新内容。Device Key 仅保存在本站，不会回传到网页。</p>
        <label class="member-notification-toggle"><input type="checkbox" id="member-bark-enabled"> 开启我的通知</label>
        <div class="member-notification-fields">
          <label>Bark 服务器地址<input type="url" id="member-bark-server" autocomplete="off" spellcheck="false" placeholder="https://api.day.app"></label>
          <label>Device Key<input type="password" id="member-bark-key" autocomplete="new-password" spellcheck="false" placeholder="从 Bark App 复制"></label>
          <label>通知分组<input type="text" id="member-bark-group" maxlength="64" placeholder="Incandescence"></label>
        </div>
        <fieldset class="member-notification-accounts">
          <legend>选择需要通知的账号</legend>
          <div id="member-bark-accounts"></div>
        </fieldset>
        <div class="member-notification-result" id="member-bark-result" role="status"></div>
        <footer>
          <button type="button" class="text-button danger-text" id="member-bark-clear">清除密钥</button>
          <span></span>
          <button type="button" class="secondary-button" id="member-bark-test">测试</button>
          <button type="submit" class="primary-button" id="member-bark-save">保存</button>
        </footer>
      </form>`;
    document.body.append(dialog);
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.querySelector("#member-notification-form").addEventListener("submit", save);
    dialog.querySelector("#member-bark-test").addEventListener("click", test);
    dialog.querySelector("#member-bark-clear").addEventListener("click", clearKey);
    return dialog;
  }

  async function open(api, showToast) {
    currentApi = api;
    currentToast = showToast;
    const modal = ensureDialog();
    setResult("正在读取通知设置…");
    modal.showModal();
    try {
      settings = await currentApi("/api/member/notifications");
      fill();
    } catch (error) {
      setResult(error.message, true);
    }
  }

  function fill() {
    dialog.querySelector("#member-bark-enabled").checked = Boolean(settings.enabled);
    dialog.querySelector("#member-bark-server").value = settings.serverUrl || "https://api.day.app";
    const key = dialog.querySelector("#member-bark-key");
    key.value = "";
    key.placeholder = settings.deviceKeyConfigured ? "已安全保存，留空不修改" : "从 Bark App 复制";
    dialog.querySelector("#member-bark-group").value = settings.group || "Incandescence";
    const selected = new Set(settings.accountIds || []);
    const accounts = dialog.querySelector("#member-bark-accounts");
    accounts.replaceChildren();
    for (const account of settings.availableAccounts || []) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = String(account.id);
      input.checked = selected.has(account.id);
      const privacy = account.isPublic ? "公开" : "会员专属";
      label.append(input, document.createTextNode(` ${account.displayName} · @${account.username}（${privacy}）`));
      accounts.append(label);
    }
    if (!(settings.availableAccounts || []).length) {
      const empty = document.createElement("p");
      empty.textContent = "当前没有可订阅的账号。";
      accounts.append(empty);
    }
    dialog.querySelector("#member-bark-clear").hidden = !settings.deviceKeyConfigured;
    setResult(settings.deviceKeyConfigured ? "Device Key 已保存，可直接修改订阅账号。" : "请先填写 Bark Device Key。", false);
  }

  async function save(event) {
    event.preventDefault();
    const button = dialog.querySelector("#member-bark-save");
    const key = dialog.querySelector("#member-bark-key").value.trim();
    const body = {
      enabled: dialog.querySelector("#member-bark-enabled").checked,
      serverUrl: dialog.querySelector("#member-bark-server").value.trim(),
      group: dialog.querySelector("#member-bark-group").value.trim(),
      accountIds: [...dialog.querySelectorAll("#member-bark-accounts input:checked")]
        .map((input) => Number(input.value)),
    };
    if (key) body.deviceKey = key;
    button.disabled = true;
    setResult("正在保存…");
    try {
      settings = await currentApi("/api/member/notifications", { method: "PUT", body });
      fill();
      setResult(settings.enabled ? "已开启所选账号的新内容通知。" : "设置已保存，通知当前关闭。", false);
      currentToast?.("个人 Bark 通知设置已保存");
    } catch (error) {
      setResult(error.message, true);
      currentToast?.(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function test() {
    const key = dialog.querySelector("#member-bark-key").value.trim();
    if (key) return setResult("Device Key 有未保存的修改，请先保存。", true);
    if (!settings?.deviceKeyConfigured) return setResult("请先填写并保存 Device Key。", true);
    const button = dialog.querySelector("#member-bark-test");
    button.disabled = true;
    setResult("正在发送测试通知…");
    try {
      const result = await currentApi("/api/member/notifications/test", { method: "POST", body: {} });
      setResult(`测试通知已送达 · HTTP ${result.status} · ${result.elapsedMs} ms`, false);
    } catch (error) {
      setResult(error.message, true);
    } finally {
      button.disabled = false;
    }
  }

  async function clearKey() {
    if (!settings?.deviceKeyConfigured || !window.confirm("清除你的 Bark Device Key 并关闭通知？")) return;
    const selected = [...dialog.querySelectorAll("#member-bark-accounts input:checked")]
      .map((input) => Number(input.value));
    try {
      settings = await currentApi("/api/member/notifications", {
        method: "PUT",
        body: {
          enabled: false,
          serverUrl: dialog.querySelector("#member-bark-server").value.trim(),
          group: dialog.querySelector("#member-bark-group").value.trim(),
          accountIds: selected,
          clearDeviceKey: true,
        },
      });
      fill();
      setResult("Device Key 已清除，个人通知已关闭。", false);
    } catch (error) {
      setResult(error.message, true);
    }
  }

  function setResult(message, error = false) {
    if (!dialog) return;
    const node = dialog.querySelector("#member-bark-result");
    node.textContent = message || "";
    node.classList.toggle("bad", error);
  }

  window.MemberNotifications = { createButton };
})();
