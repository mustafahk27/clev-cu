// Walks the DOM (including open shadow roots) and returns Clev elements.
// Live element references are kept in window.__clev so the executor can get reliable handles
// without mutating the page. `ts` ties those references to one Observation (stale-id detection).
// Returns one compact JSON string (rows + a context table): Playwright's per-object transfer of
// ~5k objects costs ~200ms, a single string ~35ms.
({ ts, maxElements }) => {
  const INTERACTIVE = new Set([
    "button", "link", "textbox", "searchbox", "combobox", "checkbox", "radio", "menuitem",
    "menuitemcheckbox", "menuitemradio", "tab", "option", "switch", "slider", "spinbutton",
    "listbox", "treeitem",
  ]);
  const TEXTUAL = new Set(["heading", "alert", "status"]);
  const CONTAINERS = new Set([
    "banner", "navigation", "main", "contentinfo", "complementary", "form", "dialog",
    "alertdialog", "region", "search", "menu", "menubar", "toolbar", "tablist", "tree", "grid",
  ]);
  const TEXT_INPUTS = new Set(["", "text", "email", "tel", "url", "password"]);
  const SECRET_AUTOCOMPLETE = /^(cc-number|cc-csc|cc-exp|one-time-code|current-password|new-password)$/;

  const clean = (s, n = 200) => (s || "").replace(/\s+/g, " ").trim().slice(0, n);

  function implicitRole(el) {
    const tag = el.tagName.toLowerCase();
    switch (tag) {
      case "a": case "area": return el.hasAttribute("href") ? "link" : null;
      case "button": case "summary": return "button";
      case "select": return el.multiple || el.size > 1 ? "listbox" : "combobox";
      case "textarea": return "textbox";
      case "option": return "option";
      case "h1": case "h2": case "h3": case "h4": case "h5": case "h6": return "heading";
      case "nav": return "navigation";
      case "main": return "main";
      case "aside": return "complementary";
      case "dialog": return "dialog";
      case "form": return "form";
      case "search": return "search";
      case "header": return el.closest("article,section,main,aside,nav") ? null : "banner";
      case "footer": return el.closest("article,section,main,aside,nav") ? null : "contentinfo";
      case "section": return el.hasAttribute("aria-label") || el.hasAttribute("aria-labelledby") ? "region" : null;
      case "input": {
        const t = (el.getAttribute("type") || "").toLowerCase();
        if (t === "hidden") return null;
        if (["button", "submit", "reset", "image"].includes(t)) return "button";
        if (t === "checkbox") return el.getAttribute("switch") !== null ? "switch" : "checkbox";
        if (t === "radio") return "radio";
        if (t === "range") return "slider";
        if (t === "number") return "spinbutton";
        if (t === "search") return "searchbox";
        if (TEXT_INPUTS.has(t)) return "textbox";
        return "textbox"; // date, time, color, file... are still typed/clicked into
      }
    }
    if (el.isContentEditable && !el.parentElement?.isContentEditable) return "textbox";
    return null;
  }

  const roleOf = (el) => (el.getAttribute("role") || "").trim().split(/\s+/)[0] || implicitRole(el);

  const byIds = (el, attr) => {
    const ids = (el.getAttribute(attr) || "").split(/\s+/).filter(Boolean);
    const root = el.getRootNode();
    return clean(ids.map((id) => (root.getElementById ? root.getElementById(id) : document.getElementById(id))?.innerText || "").join(" "));
  };

  function textWithAlts(el) {
    let t = el.innerText || "";
    if (!clean(t)) t = [...el.querySelectorAll("img[alt],svg title")].map((i) => i.alt || i.textContent).join(" ");
    return clean(t);
  }

  function nameOf(el, role) {
    const labelled = byIds(el, "aria-labelledby");
    if (labelled) return labelled;
    const aria = clean(el.getAttribute("aria-label"));
    if (aria) return aria;
    const tag = el.tagName.toLowerCase();
    if (["input", "select", "textarea"].includes(tag)) {
      const t = (el.getAttribute("type") || "").toLowerCase();
      if (["button", "submit", "reset"].includes(t)) return clean(el.value) || (t === "submit" ? "Submit" : t);
      if (t === "image") return clean(el.alt) || "Submit";
      const labels = el.labels ? [...el.labels].map((l) => l.innerText).join(" ") : "";
      if (clean(labels)) return clean(labels);
      return clean(el.getAttribute("placeholder") || el.getAttribute("title") || el.getAttribute("name"));
    }
    if (role === "textbox" || role === "searchbox" || role === "combobox") {
      return clean(el.getAttribute("aria-placeholder") || el.getAttribute("title"));
    }
    if (tag === "img") return clean(el.alt);
    return textWithAlts(el) || clean(el.getAttribute("title"));
  }

  function valueOf(el, role) {
    const tag = el.tagName.toLowerCase();
    const t = (el.getAttribute("type") || "").toLowerCase();
    if (["checkbox", "radio", "switch", "menuitemcheckbox", "menuitemradio"].includes(role)) {
      const checked = tag === "input" ? el.checked : el.getAttribute("aria-checked") === "true";
      return checked ? "checked" : "unchecked";
    }
    if (tag === "select") return clean([...el.selectedOptions].map((o) => o.text).join(", "));
    if (tag === "input" && (t === "checkbox" || t === "radio")) {
      return el.checked ? "checked" : "unchecked"; // e.g. a checkbox restyled with role=button
    }
    if (tag === "input" || tag === "textarea") {
      if (!el.value) return null;
      // Never let secrets reach traces or models.
      if (t === "password" || SECRET_AUTOCOMPLETE.test(el.getAttribute("autocomplete") || "")) return "[redacted]";
      if (["button", "submit", "reset", "image"].includes(t)) return null;
      return clean(el.value);
    }
    if (role === "textbox" && el.isContentEditable) return clean(el.innerText) || null;
    if (el.hasAttribute("aria-valuenow")) return clean(el.getAttribute("aria-valuetext") || el.getAttribute("aria-valuenow"));
    if (["tab", "option", "treeitem"].includes(role) && el.getAttribute("aria-selected") === "true") return "selected";
    if (el.getAttribute("aria-expanded") === "true") return "expanded";
    return null;
  }

  const parentOf = (el) => el.parentElement || el.getRootNode()?.host || null;

  const containerLabel = new Map();
  function containerPart(el) {
    if (containerLabel.has(el)) return containerLabel.get(el);
    const role = roleOf(el);
    let part = null;
    if (CONTAINERS.has(role)) {
      let name = byIds(el, "aria-labelledby") || clean(el.getAttribute("aria-label"), 40);
      if (!name && (role === "dialog" || role === "alertdialog")) {
        name = clean(el.querySelector("h1,h2,h3,[role=heading]")?.innerText, 40);
      }
      part = name ? `${role} "${name.slice(0, 40)}"` : role;
    }
    containerLabel.set(el, part);
    return part;
  }

  function contextOf(el) {
    const parts = [];
    for (let p = parentOf(el); p && p !== document.documentElement; p = parentOf(p)) {
      const part = containerPart(p);
      if (part) parts.unshift(part);
    }
    return parts.slice(-3).join(" > ");
  }

  function isVisible(el) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return false;
    return el.checkVisibility ? el.checkVisibility({ visibilityProperty: true }) : true;
  }

  const isEnabled = (el) =>
    !el.matches(":disabled") && el.closest("[aria-disabled=true]") === null && !el.closest("[inert]");

  const els = new Map();
  const rows = [];
  const contexts = new Map();
  const contextIndex = (c) => {
    let i = contexts.get(c);
    if (i === undefined) contexts.set(c, (i = contexts.size));
    return i;
  };
  const active = (() => {
    let a = document.activeElement;
    while (a && a.shadowRoot && a.shadowRoot.activeElement) a = a.shadowRoot.activeElement;
    return a;
  })();

  function walk(root) {
    for (const el of root.querySelectorAll("*")) {
      if (rows.length >= maxElements) return;
      const role = roleOf(el);
      if (role && (INTERACTIVE.has(role) || TEXTUAL.has(role))) {
        const r = el.getBoundingClientRect();
        els.set("e" + rows.length, el); // id is the row index; Python builds the same "e<N>"
        const flags = (isEnabled(el) ? 1 : 0) | (el === active ? 2 : 0) | (isVisible(el) ? 4 : 0);
        rows.push([
          role, nameOf(el, role), valueOf(el, role), contextIndex(contextOf(el)), flags,
          Math.round(r.x + scrollX), Math.round(r.y + scrollY), Math.round(r.width), Math.round(r.height),
        ]);
      }
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  }
  walk(document);
  window.__clev = { ts, els };
  return JSON.stringify({ contexts: [...contexts.keys()], rows, truncated: rows.length >= maxElements });
}
