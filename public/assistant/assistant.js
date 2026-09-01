"use strict";

(() => {
  const reduceMotion = () =>
    Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
  const finePointer = () =>
    Boolean(window.matchMedia?.("(hover: hover) and (pointer: fine)")?.matches);

  function hrefFor(kind, value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (/^https?:\/\//i.test(text)) return text;
    if (kind === "email") return `mailto:${text}`;
    if (kind === "telegram") {
      const handle = text.replace(/^@/, "");
      if (/^[A-Za-z0-9_]{4,64}$/.test(handle)) return `https://t.me/${handle}`;
      return text.startsWith("t.me/") ? `https://${text}` : "";
    }
    if (kind === "home") {
      if (text.includes("://") || text.startsWith("mailto:")) return text;
      if (/^[\w.-]+\.[a-z]{2,}([/:].*)?$/i.test(text)) return `https://${text}`;
      return "";
    }
    if (kind === "x") {
      const handle = text.replace(/^@/, "");
      if (/^[A-Za-z0-9_]{1,32}$/.test(handle) && !text.includes(".")) {
        return `https://x.com/${handle}`;
      }
      return hrefFor("home", text);
    }
    return "";
  }

  function contactFrom(payload) {
    const items = [];
    if (payload.telegram) {
      items.push({
        label: "Telegram",
        value: payload.telegram,
        href: hrefFor("telegram", payload.telegram),
      });
    }
    if (payload.email) {
      items.push({
        label: "邮箱",
        value: payload.email,
        href: hrefFor("email", payload.email),
      });
    }
    if (payload.home) {
      items.push({
        label: "主页",
        value: payload.home.replace(/^https?:\/\//i, ""),
        href: hrefFor("home", payload.home),
      });
    }
    if (payload.x) {
      items.push({
        label: "X",
        value: payload.x,
        href: hrefFor("x", payload.x),
      });
    }
    if (payload.wechat) {
      items.push({ label: "微信", value: payload.wechat });
    }
    for (const extra of payload.custom || []) {
      if (!extra.value) continue;
      items.push({
        label: extra.label || "联系",
        value: extra.value,
        href: extra.href || hrefFor("home", extra.value),
      });
    }
    return {
      name: payload.name || "作者",
      tagline: payload.tagline || "",
      items,
    };
  }

  function relativeAgo(value) {
    const then = new Date(value).getTime();
    if (!then) return "";
    const minutes = Math.max(1, Math.round((Date.now() - then) / 60000));
    if (minutes < 60) return `${minutes} 分钟前`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours} 小时前`;
    return `${Math.round(hours / 24)} 天前`;
  }

  function pick(list) {
    if (!list.length) return null;
    return list[Math.floor(Math.random() * list.length)];
  }

  function setIn(el, on) {
    if (on) {
      el.hidden = false;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => el.classList.add("is-in"));
      });
      return;
    }
    el.classList.remove("is-in");
    window.setTimeout(() => {
      if (!el.classList.contains("is-in")) el.hidden = true;
    }, reduceMotion() ? 0 : 420);
  }

  function paintSheet(sheet, contact) {
    sheet.querySelector("h2").textContent = contact.name;
    const intro = sheet.querySelector("p");
    intro.hidden = !contact.tagline;
    intro.textContent = contact.tagline;
    const rows = sheet.querySelector(".xglow-assistant-rows");
    rows.replaceChildren();
    contact.items.forEach((item) => {
      const node = document.createElement(item.href ? "a" : "div");
      node.className = "xglow-assistant-row";
      if (item.href) {
        node.href = item.href;
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      }
      const label = document.createElement("small");
      label.textContent = item.label;
      const value = document.createElement("b");
      value.textContent = item.value;
      node.append(label, value);
      rows.appendChild(node);
    });
  }

  async function fetchHitokoto() {
    const response = await fetch("/api/public/hitokoto", { cache: "no-store" });
    if (!response.ok) throw new Error("hitokoto");
    const data = await response.json();
    const line = String(data.text || "").trim();
    if (!line) throw new Error("empty");
    return line;
  }

  async function fetchUpdateLine() {
    const response = await fetch("/api/public/accounts", { cache: "no-store" });
    if (!response.ok) return "";
    const payload = await response.json();
    const accounts = (payload.items || []).filter((item) => item.lastSyncedAt);
    if (!accounts.length) return "";
    const account = pick(accounts);
    const name = account.displayName || account.username || "有人";
    const ago = relativeAgo(account.lastSyncedAt);
    let media = 0;
    let posts = 0;
    try {
      const tweetsRes = await fetch(
        `/api/public/accounts/${encodeURIComponent(account.id)}/tweets?limit=8`,
        { cache: "no-store" },
      );
      if (tweetsRes.ok) {
        const page = await tweetsRes.json();
        for (const tweet of page.items || []) {
          posts += 1;
          media += Array.isArray(tweet.media) ? tweet.media.length : 0;
        }
      }
    } catch (_) { /* use totals */ }
    if (media) return `${name} ${ago}更新了 ${media} 个媒体`;
    if (posts) return `${name} ${ago}更新了 ${posts} 条内容`;
    if (account.mediaCount) return `${name} ${ago}有更新，目前 ${account.mediaCount} 个媒体`;
    return `${name} ${ago}有内容更新`;
  }

  function mount(contact) {
    if (document.querySelector(".xglow-assistant")) return;
    if (!window.GrokCharacter) return;

    const root = document.createElement("aside");
    root.className = "xglow-assistant";
    root.setAttribute("aria-label", "拾光小助手");
    root.innerHTML = `
      <section class="xglow-assistant-sheet" hidden>
        <h2></h2>
        <p></p>
        <div class="xglow-assistant-rows"></div>
      </section>
      <div class="xglow-assistant-bubble" hidden role="status"></div>
      <button class="xglow-assistant-bot" type="button" aria-label="拾光小助手">
        <svg viewBox="-15 -15 259 259" role="img" aria-hidden="true"></svg>
      </button>
    `;
    document.body.appendChild(root);

    const sheet = root.querySelector(".xglow-assistant-sheet");
    const bubble = root.querySelector(".xglow-assistant-bubble");
    const botBtn = root.querySelector(".xglow-assistant-bot");
    const svg = root.querySelector("svg");
    paintSheet(sheet, contact);

    const mini = document.documentElement.classList.contains("telegram-mini-app");
    const narrow = Boolean(window.matchMedia?.("(max-width: 720px)")?.matches);
    const bot = new window.GrokCharacter(svg, {
      shape: "blob",
      color: "black",
      scheme: "light",
      sizePx: mini ? 48 : narrow ? 54 : 80,
      loginWrap: true,
      followPointer: finePointer() && !mini,
      mode: "onboarding",
      state: "curious",
    });
    bot.moodN = 1;
    bot.setState("curious", { resetEyes: true });

    let hideTimer = 0;
    let talkTimer = 0;
    let sheetOpen = false;
    let lastLine = "";
    let preferUpdate = Math.random() < 0.45;

    function hideAll() {
      sheetOpen = false;
      setIn(sheet, false);
      setIn(bubble, false);
    }

    function autoHide(ms) {
      window.clearTimeout(hideTimer);
      hideTimer = window.setTimeout(hideAll, ms);
    }

    function say(text) {
      const line = String(text || "").trim();
      if (!line || sheetOpen) return;
      lastLine = line;
      setIn(sheet, false);
      bubble.textContent = line;
      setIn(bubble, true);
      const hold = Math.min(9000, 2800 + line.length * 70);
      autoHide(hold);
    }

    function showContact() {
      sheetOpen = true;
      setIn(bubble, false);
      setIn(sheet, true);
      autoHide(5000);
    }

    function paintBot() {
      const dark = document.documentElement.dataset.theme === "dark";
      bot.setColor("black", dark ? "dark" : "light");
      bot.setInk(dark ? "#f3efe6" : "#111111");
      bot.setEyeColor(dark ? "#1a1916" : "#f3efe6");
      svg.style.colorScheme = dark ? "dark" : "light";
    }

    async function nextLine() {
      const tryUpdate = preferUpdate;
      preferUpdate = !preferUpdate;
      const tasks = tryUpdate
        ? [fetchUpdateLine, fetchHitokoto]
        : [fetchHitokoto, fetchUpdateLine];
      for (const task of tasks) {
        try {
          const line = await task();
          if (line && line !== lastLine) return line;
        } catch (_) { /* next source */ }
      }
      return "";
    }

    function scheduleTalk(delay) {
      window.clearTimeout(talkTimer);
      talkTimer = window.setTimeout(async () => {
        if (!document.hidden && !sheetOpen && !bubble.classList.contains("is-in")) {
          const line = await nextLine();
          if (line) say(line);
        }
        scheduleTalk(18000 + Math.floor(Math.random() * 16000));
      }, delay);
    }

    paintBot();
    botBtn.addEventListener("click", () => {
      if (sheetOpen) {
        hideAll();
        return;
      }
      showContact();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideAll();
    });
    document.addEventListener("visibilitychange", () => {
      bot.setPaused(document.hidden);
      if (document.hidden) {
        window.clearTimeout(talkTimer);
        return;
      }
      scheduleTalk(4000);
    });
    window.addEventListener("xglow:theme", paintBot);
    window.Telegram?.WebApp?.onEvent?.("themeChanged", paintBot);

    window.setTimeout(() => {
      if (!sheetOpen && !bubble.classList.contains("is-in")) {
        say("嗨，我是拾光小助手。");
      }
    }, 800);
    scheduleTalk(7000);
  }

  async function start() {
    let payload = window.XGlowAssistantContact || null;
    try {
      const response = await fetch("/api/public/assistant", { cache: "no-store" });
      if (response.ok) payload = await response.json();
    } catch (_) { /* keep fallback */ }
    if (payload && payload.enabled === false) return;
    const contact = payload && !payload.items
      ? contactFrom(payload)
      : (payload || contactFrom({ name: "作者" }));
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => mount(contact), { once: true });
    } else {
      mount(contact);
    }
  }

  start();
})();
