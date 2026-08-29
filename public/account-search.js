"use strict";

(() => {
  function normalize(value) {
    return String(value || "")
      .normalize("NFKD")
      .replace(/\p{M}/gu, "")
      .toLocaleLowerCase()
      .replace(/^@+/, "")
      .trim();
  }

  function isSubsequence(needle, haystack) {
    let index = 0;
    for (const character of haystack) {
      if (character === needle[index]) index += 1;
      if (index === needle.length) return true;
    }
    return false;
  }

  function score(account, query) {
    const terms = normalize(query).split(/\s+/).filter(Boolean);
    if (!terms.length) return 0;
    const fields = [account.displayName, account.username, account.id].map(normalize);
    const compactFields = fields.map((value) => value.replace(/[\s_.-]+/g, ""));
    let total = 0;
    for (const term of terms) {
      const compactTerm = term.replace(/[\s_.-]+/g, "");
      let best = Number.POSITIVE_INFINITY;
      fields.forEach((field, index) => {
        if (field === term) best = Math.min(best, index === 1 ? 0 : 1);
        else if (field.startsWith(term)) best = Math.min(best, 2);
        else if (field.includes(term)) best = Math.min(best, 4);
        else if (compactFields[index].includes(compactTerm)) best = Math.min(best, 6);
        else if (compactTerm.length >= 3 && isSubsequence(compactTerm, compactFields[index])) best = Math.min(best, 9);
      });
      if (!Number.isFinite(best)) return Number.POSITIVE_INFINITY;
      total += best;
    }
    return total;
  }

  function filter(accounts, query) {
    if (!normalize(query)) return accounts;
    return accounts
      .map((account, index) => ({ account, index, score: score(account, query) }))
      .filter((item) => Number.isFinite(item.score))
      .sort((left, right) => left.score - right.score || left.index - right.index)
      .map((item) => item.account);
  }

  window.XGlowAccountSearch = Object.freeze({ filter, normalize, score });
})();
