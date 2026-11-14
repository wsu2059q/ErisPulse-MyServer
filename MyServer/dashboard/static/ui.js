/* MyServer UI 组件库
 * 依赖：无（原生 DOM）
 * 导出：window.MS
 * 组件：el / toast / modal / select / table / badge / empty / stat / field
 */

(function () {
  "use strict";

  const MS = { version: "2.0.0" };
  const _t = (key, fallback) =>
    (window.MSI18N ? window.MSI18N.t(key, fallback) : fallback);

  /* ---------- DOM 工厂 ---------- */

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value === null || value === undefined || value === false) continue;
        if (key === "class") node.className = value;
        else if (key === "dataset") Object.assign(node.dataset, value);
        else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
        else if (key.startsWith("on") && typeof value === "function") {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (key === "html") node.innerHTML = value;
        else if (key === "text") node.textContent = value;
        else if (key === "value" && "value" in node) node.value = value;
        else node.setAttribute(key, value);
      }
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      node.appendChild(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  MS.el = el;
  MS.clear = clear;

  /* ---------- Toast ---------- */

  let toastEl = null;
  let toastTimer = null;

  MS.toast = function (message, kind) {
    if (!toastEl) {
      toastEl = el("div", { class: "ms-toast", role: "status", "aria-live": "polite" });
      document.body.appendChild(toastEl);
    }
    toastEl.textContent = message;
    toastEl.dataset.kind = kind || "info";
    toastEl.classList.add("is-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-show"), 2600);
  };

  /* ---------- Modal ---------- */

  MS.modal = function (options) {
    const { title = "", body = null, actions = [], width = 560, onClose = null } = options;
    const mask = el("div", { class: "ms-modal-mask" });
    const card = el("div", { class: "ms-card ms-modal", style: { width: width + "px" } });
    const head = el("div", { class: "ms-modal-head" }, el("h2", { class: "ms-section-title" }, title));
    const bodyWrap = el("div", { class: "ms-modal-body" });
    const actionWrap = el("div", { class: "ms-toolbar ms-modal-actions" });
    const error = el("div", { class: "ms-form-error" });

    if (body) bodyWrap.appendChild(body instanceof Node ? body : document.createTextNode(String(body)));

    const handle = {
      el: card,
      mask,
      body: bodyWrap,
      error,
      close() {
        mask.remove();
        document.removeEventListener("keydown", onKey);
        if (onClose) onClose();
      },
      setError(message) {
        error.textContent = message || "";
      },
    };

    for (const action of actions) {
      actionWrap.appendChild(el("button", {
        class: "ms-btn" + (action.primary ? " ms-btn-primary" : ""),
        type: "button",
        onclick: () => {
          if (action.onClick) action.onClick(handle);
          else handle.close();
        },
      }, action.label));
    }

    function onKey(event) {
      if (event.key === "Escape") handle.close();
    }

    mask.addEventListener("click", (event) => {
      if (event.target === mask) handle.close();
    });
    document.addEventListener("keydown", onKey);

    card.append(head, bodyWrap, error, actionWrap);
    mask.appendChild(card);
    document.body.appendChild(mask);
    const firstInput = card.querySelector("input, textarea, select");
    if (firstInput) firstInput.focus();
    return handle;
  };

  /* ---------- Select（自定义下拉） ---------- */

  MS.select = function (options) {
    const { options: initial = [], value = "", placeholder = _t("ms_please_select", "请选择"), disabled = false,
      onChange = null, minWidth = 140 } = options || {};

    const root = el("div", { class: "ms-select", style: { minWidth: minWidth + "px" } });
    const btn = el("button", {
      type: "button",
      class: "ms-select-btn",
      role: "combobox",
      "aria-haspopup": "listbox",
      "aria-expanded": "false",
    }, el("span", { class: "ms-select-label" }), el("span", { class: "ms-select-caret", html: "&#9662;" }));
    const label = btn.querySelector(".ms-select-label");
    root.appendChild(btn);

    let items = [];
    let current = value;
    let pop = null;
    let activeIndex = -1;

    function optionLabel(item) {
      return item.label === undefined ? String(item.value) : String(item.label);
    }

    function renderLabel() {
      const found = items.find((item) => String(item.value) === String(current));
      label.textContent = found ? optionLabel(found) : (items.length ? placeholder : _t("ms_no_data", "暂无数据"));
      btn.classList.toggle("is-placeholder", !found);
      btn.disabled = !!disabled || !items.length;
    }

    function close() {
      if (!pop) return;
      pop.remove();
      pop = null;
      btn.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", onDocClick, true);
      document.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      root.classList.remove("is-open");
    }

    function place() {
      if (!pop) return;
      const rect = btn.getBoundingClientRect();
      const width = Math.max(rect.width, 168);
      let left = rect.left;
      if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
      pop.style.left = Math.max(8, left) + "px";
      pop.style.width = width + "px";
      const below = window.innerHeight - rect.bottom;
      const height = Math.min(280, items.length * 38 + 8);
      if (below < height + 12 && rect.top > below) {
        pop.style.top = Math.max(8, rect.top - height - 6) + "px";
      } else {
        pop.style.top = (rect.bottom + 6) + "px";
      }
    }

    function onDocClick(event) {
      if (!pop) return;
      if (pop.contains(event.target) || btn.contains(event.target)) return;
      close();
    }

    function choose(index) {
      const item = items[index];
      if (!item) return;
      current = item.value;
      renderLabel();
      close();
      if (onChange) onChange(item.value, item);
    }

    function open() {
      if (pop || disabled || !items.length) return;
      pop = el("div", { class: "ms-select-pop", role: "listbox" });
      items.forEach((item, index) => {
        const opt = el("div", {
          class: "ms-select-opt" + (String(item.value) === String(current) ? " is-active" : ""),
          role: "option",
          "aria-selected": String(item.value) === String(current) ? "true" : "false",
        }, optionLabel(item));
        opt.addEventListener("click", () => choose(index));
        opt.addEventListener("mouseenter", () => setActive(index));
        pop.appendChild(opt);
      });
      document.body.appendChild(pop);
      root.classList.add("is-open");
      btn.setAttribute("aria-expanded", "true");
      activeIndex = items.findIndex((item) => String(item.value) === String(current));
      setActive(activeIndex < 0 ? 0 : activeIndex);
      place();
      document.addEventListener("click", onDocClick, true);
      document.addEventListener("scroll", place, true);
      window.addEventListener("resize", place);
    }

    function setActive(index) {
      activeIndex = index;
      if (!pop) return;
      pop.querySelectorAll(".ms-select-opt").forEach((node, i) => {
        node.classList.toggle("is-focus", i === index);
      });
    }

    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      if (pop) close(); else open();
    });

    btn.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        close();
        return;
      }
      if (!pop) {
        if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
          event.preventDefault();
          open();
        }
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive(Math.min(items.length - 1, activeIndex + 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive(Math.max(0, activeIndex - 1));
      } else if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        choose(activeIndex);
      } else if (event.key === "Tab") {
        close();
      }
    });

    const api = {
      el: root,
      get value() { return current; },
      setOptions(next, nextValue) {
        items = (next || []).map((item) =>
          typeof item === "object" ? item : { value: item, label: String(item) });
        if (nextValue !== undefined) current = nextValue;
        if (current === "" && items.length) current = items[0].value;
        if (!items.some((item) => String(item.value) === String(current))) current = "";
        renderLabel();
        if (pop) { close(); }
      },
      setValue(next, silent) {
        current = next;
        renderLabel();
        if (!silent && onChange) onChange(current);
      },
      setDisabled(flag) {
        disabled = !!flag;
        renderLabel();
        if (disabled) close();
      },
      get disabled() { return !!disabled || !items.length; },
    };

    api.setOptions(initial, value);
    return api;
  };

  /* ---------- Table ---------- */

  MS.table = function (config) {
    const { columns = [], rows = [], empty = _t("ms_no_data", "暂无数据"), rowClick = null } = config || {};
    const table = el("table", { class: "ms-table" });
    const thead = el("thead");
    const headRow = el("tr");
    for (const column of columns) {
      headRow.appendChild(el("th", column.width ? { style: { width: column.width } } : null,
        column.label || ""));
    }
    thead.appendChild(headRow);
    const tbody = el("tbody");

    if (!rows.length) {
      tbody.appendChild(el("tr", null,
        el("td", { colspan: String(columns.length || 1), class: "ms-table-empty" }, empty)));
    } else {
      rows.forEach((row, index) => {
        const tr = el("tr");
        for (const column of columns) {
          const cell = el("td", column.className ? { class: column.className } : null);
          const value = column.render ? column.render(row, index) : row[column.key];
          if (value instanceof Node) cell.appendChild(value);
          else cell.textContent = value === null || value === undefined ? "" : String(value);
          tr.appendChild(cell);
        }
        if (rowClick) tr.addEventListener("click", () => rowClick(row, index));
        tbody.appendChild(tr);
      });
    }
    table.append(thead, tbody);
    return table;
  };

  /* ---------- 小组件 ---------- */

  MS.badge = function (level, text) {
    const map = { ok: "ok", warn: "warn", confirm: "confirm", alerting: "confirm" };
    return el("span", { class: "ms-badge " + (map[level] || "ok") }, text || level || "ok");
  };

  MS.empty = function (message, actionLabel, onAction) {
    const node = el("div", { class: "ms-card ms-empty" }, el("div", null, message));
    if (actionLabel && onAction) {
      node.appendChild(el("button", { class: "ms-btn ms-btn-primary", type: "button", onclick: onAction },
        actionLabel));
    }
    return node;
  };

  MS.stat = function (options) {
    const { label = "", value = "–", accent = false, id = "" } = options || {};
    return el("div", { class: "ms-stat" },
      el("div", { class: "ms-stat-label" }, label),
      el("div", { class: "ms-stat-num" + (accent ? " accent" : ""), id }, String(value)));
  };

  MS.field = function (options) {
    const { label = "", control = null, hint = "", span = false } = options || {};
    const wrap = el("label", span ? { class: "ms-form-span" } : null, label);
    if (control) wrap.appendChild(control);
    if (hint) wrap.appendChild(el("span", { class: "ms-field-hint" }, hint));
    return wrap;
  };

  MS.input = function (options) {
    const { type = "text", value = "", placeholder = "", id = "", step = "" } = options || {};
    return el("input", {
      class: "ms-input",
      type,
      value,
      placeholder,
      id,
      step,
    });
  };

  MS.textarea = function (options) {
    const { value = "", placeholder = "", id = "", rows = 3 } = options || {};
    return el("textarea", {
      class: "ms-input",
      id,
      rows: String(rows),
      placeholder,
      value,
    });
  };

  MS.switch = function (options) {
    const { label = "", id = "", checked = false } = options || {};
    const input = el("input", { type: "checkbox", id });
    input.checked = !!checked;
    return el("label", { class: "ms-check ms-switch" }, input, el("span", null, label));
  };

  MS.host = function (id) {
    return el("div", { id });
  };

  MS.filePicker = function (options) {
    const { label = _t("ms_upload", "上传"), multiple = false, accept = "", onFiles = null } = options || {};
    const input = el("input", { type: "file", hidden: "", accept });
    input.multiple = !!multiple;
    const wrap = el("label", { class: "ms-btn" }, label, input);
    input.addEventListener("change", () => {
      if (onFiles) onFiles(input.files);
    });
    return {
      el: wrap,
      input,
      reset() { input.value = ""; },
    };
  };

  window.MS = MS;
})();
