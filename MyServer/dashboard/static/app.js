// MyServer 控制台：全部 UI 由 MS 组件库构建，请求走相对路径（反代子路径可用）
"use strict";

(function () {
  const MS = window.MS;
  const { el, clear, toast } = MS;
  const t = window.MSI18N.t;
  const tf = window.MSI18N.tf;

  const params = new URLSearchParams(location.search);
  const TOKEN = params.get("token") || localStorage.getItem("__ep_tk__") || "";
  const API = "api/";
  const $ = (id) => document.getElementById(id);

  const state = { machines: [], term: "", files: "", mon: "" };

  function headers() {
    return { "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json" };
  }

  async function api(path, options) {
    const res = await fetch(API + path, Object.assign({ headers: headers() }, options || {}));
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  function fmtTime(ts) {
    if (!ts) return "–";
    return new Date(ts * 1000).toLocaleString();
  }

  function fmtSize(n) {
    if (n === null || n === undefined) return "–";
    const units = ["B", "KB", "MB", "GB"];
    let value = n;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
    return value.toFixed(unit ? 1 : 0) + units[unit];
  }

  function pct(value) {
    return value === null || value === undefined ? "–" : value.toFixed(0) + "%";
  }

  const scriptCache = new Map();

  function loadScript(src) {
    if (!scriptCache.has(src)) {
      scriptCache.set(src, new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = src;
        script.async = true;
        script.onload = () => resolve();
        script.onerror = () => reject(new Error("加载失败：" + src));
        document.head.appendChild(script);
      }));
    }
    return scriptCache.get(src);
  }

  async function ensureXterm() {
    if (!window.Terminal) await loadScript("res/vendor/xterm.js");
    if (!window.FitAddon) await loadScript("res/vendor/fit.js");
    if (!document.querySelector('link[data-xterm-css]')) {
      document.head.appendChild(el("link", {
        rel: "stylesheet",
        href: "res/vendor/xterm.css",
        "data-xterm-css": "1",
      }));
    }
  }

  /* ---------- 选择器（组件库） ---------- */

  const termMachine = MS.select({
    placeholder: t("ms_pick_machine", "选择机器"), minWidth: 160,
    onChange: (value) => { state.term = value; },
  });
  const filesMachine = MS.select({
    placeholder: t("ms_pick_machine", "选择机器"), minWidth: 160,
    onChange: (value) => { state.files = value; loadFiles(); },
  });
  const monMachine = MS.select({
    placeholder: t("ms_pick_machine", "选择机器"), minWidth: 160,
    onChange: (value) => { state.mon = value; },
  });
  const monMetric = MS.select({
    minWidth: 130,
    options: [
      { value: "cpu_percent", label: "CPU %" },
      { value: "mem_percent", label: t("ms_metric_mem", "内存 %") },
      { value: "disk_percent", label: t("ms_metric_disk", "磁盘 %") },
      { value: "load1", label: t("ms_metric_load", "负载 load1") },
      { value: "net_rx_rate", label: t("ms_metric_rx", "下行 KB/s") },
      { value: "net_tx_rate", label: t("ms_metric_tx", "上行 KB/s") },
      { value: "tcp_conns", label: t("ms_metric_tcp", "TCP 连接数") },
      { value: "online", label: t("ms_metric_online_hist", "在线历史") },
    ],
  });
  const monHours = MS.select({
    minWidth: 110,
    options: [
      { value: "6", label: t("ms_6h", "6 小时") },
      { value: "24", label: t("ms_24h", "24 小时") },
      { value: "72", label: t("ms_3d", "3 天") },
    ],
  });

  $("term-machine").appendChild(termMachine.el);
  $("files-machine").appendChild(filesMachine.el);
  $("mon-machine").appendChild(monMachine.el);
  $("mon-metric").appendChild(monMetric.el);
  $("mon-hours").appendChild(monHours.el);
  monHours.setValue("24");
  monMetric.setValue("cpu_percent");

  const termSessionInput = MS.input({ id: "term-session", placeholder: t("ms_session_ph", "会话名"), value: "main" });
  termSessionInput.classList.add("ms-input-sm");
  $("term-session-host").appendChild(termSessionInput);

  const filesPathInput = MS.input({ id: "files-path", placeholder: t("ms_path_ph", "远端路径"), value: "/" });
  filesPathInput.classList.add("ms-grow");
  $("files-path-host").appendChild(filesPathInput);

  /* ---------- 统计与概览 ---------- */

  function renderStats(stats, pending) {
    const grid = clear($("stat-grid"));
    grid.append(
      MS.stat({ label: t("ms_stat_total", "机器总数"), value: stats.total }),
      MS.stat({ label: t("ms_stat_online", "在线"), value: stats.online, accent: true }),
      MS.stat({ label: t("ms_stat_offline", "离线"), value: stats.offline }),
      MS.stat({ label: t("ms_stat_pending", "待确认"), value: pending }),
    );
  }

  function maskHostText(text) {
    if (!text) return "";
    const at = text.indexOf("@");
    if (at < 0) return text.slice(0, 3) + "•••";
    return text.slice(0, at + 4) + "•••";
  }

  function expiryBadge(machine) {
    const expiry = machine.expiry;
    if (!expiry) return null;
    const today = new Date();
    const end = new Date(expiry + "T23:59:59");
    const days = Math.round((end - today) / 86400000);
    let tone = "";
    let text = tf("ms_expiry_on", "{date} 到期", { date: expiry });
    if (days < 0) { tone = "confirm"; text = tf("ms_expired_ago", "已过期 {n} 天", { n: -days }); }
    else if (days === 0) { tone = "confirm"; text = t("ms_expiry_today", "今天到期"); }
    else if (days <= 7) { tone = "confirm"; text = tf("ms_expiry_left", "{date} · 剩 {n} 天", { date: expiry, n: days }); }
    else if (days <= 30) { tone = "warn"; text = tf("ms_expiry_left", "{date} · 剩 {n} 天", { date: expiry, n: days }); }
    else { text = tf("ms_expiry_left", "{date} · 剩 {n} 天", { date: expiry, n: days }); }
    return MS.badge(tone, text);
  }

  function specsLine(machine) {
    const specs = machine.specs || {};
    const parts = [];
    if (specs.os) parts.push(specs.os);
    if (specs.cpu_cores) parts.push(tf("ms_cores", "{n} 核", { n: specs.cpu_cores }));
    if (specs.mem_total) parts.push(tf("ms_mem_value", "内存 {v}", { v: specs.mem_total }));
    if (specs.disk_total) parts.push(tf("ms_disk_value", "磁盘 {v}", { v: specs.disk_total }));
    return parts.join(" · ");
  }

  function notes(machine) {
    return String(machine.notes || "").trim();
  }

  function machineCard(machine) {
    const metrics = machine.metrics || {};
    const status = machine.status || {};
    const dot = el("span", { class: "ms-dot " + (machine.online ? "ms-dot-on" : "ms-dot-off") });
    const actions = el("div", { class: "ms-machine-actions" },
      el("button", { class: "ms-btn", type: "button", onclick: () => openTerminalFor(machine.name) }, t("ms_card_term", "终端")),
      el("button", { class: "ms-btn", type: "button", onclick: () => openExec(machine.name) }, t("ms_card_exec", "执行命令")),
      el("button", { class: "ms-btn", type: "button", onclick: () => openMachineModal(machine.name) }, t("ms_card_edit", "编辑")),
      el("button", {
        class: "ms-btn ms-btn-danger", type: "button",
        onclick: () => removeMachine(machine.name),
      }, t("ms_card_delete", "删除")),
    );
    return el("div", { class: "ms-card ms-machine" },
      el("div", { class: "ms-machine-head" },
        el("span", { class: "ms-machine-name" }, dot, machine.name),
        el("span", { class: "ms-machine-head-right" },
          expiryBadge(machine),
          (() => {
            const full = `${machine.username || ""}${machine.username ? "@" : ""}${machine.ip || ""}`;
          const meta = el("span", {
            class: "ms-machine-meta ms-host-toggle",
            title: t("ms_toggle_host", "点击显示 / 隐藏地址"),
            onclick: () => {
              meta.dataset.revealed = meta.dataset.revealed === "1" ? "0" : "1";
              renderMeta();
            },
          });
          function renderMeta() {
            clear(meta);
            const revealed = meta.dataset.revealed === "1";
            meta.append(document.createTextNode(revealed ? full : maskHostText(full)));
            if (machine.group) meta.append(document.createTextNode(" · " + machine.group));
          }
          renderMeta();
          return meta;
        })(),
        ),
      ),
      el("div", { class: "ms-machine-summary" },
        machine.online ? (machine.summary || "") : (status.error || t("ms_card_offline", "离线"))),
      specsLine(machine) ? el("div", { class: "ms-machine-specs" }, specsLine(machine)) : null,
      notes(machine) ? el("div", { class: "ms-machine-specs" }, t("ms_notes_prefix", "备注：") + notes(machine)) : null,
      el("div", { class: "ms-machine-metrics" },
        el("div", { class: "ms-metric" }, "CPU", el("b", null, pct(metrics.cpu_percent))),
        el("div", { class: "ms-metric" }, t("ms_card_mem", "内存"), el("b", null, pct(metrics.mem_percent))),
        el("div", { class: "ms-metric" }, t("ms_card_disk", "磁盘"), el("b", null, pct(metrics.disk_percent))),
        el("div", { class: "ms-metric" }, t("ms_card_load", "负载"),
          el("b", null, metrics.load1 !== null && metrics.load1 !== undefined ? metrics.load1.toFixed(2) : "–")),
      ),
      actions,
    );
  }

  function renderMachines(machines) {
    const grid = clear($("machine-grid"));
    if (!machines.length) {
      grid.appendChild(MS.empty(t("ms_empty_machines", "还没有机器。添加一台，三十秒后就能在聊天里管它。"),
        t("ms_add_machine", "＋ 添加机器"), () => openMachineModal("")));
      return;
    }
    grid.append(...machines.map(machineCard));
  }

  function renderAlerts(alerts) {
    const feed = clear($("alert-feed"));
    if (!alerts.length) {
      feed.appendChild(el("div", null, t("ms_no_alerts", "暂无告警")));
      return;
    }
    for (const alert of alerts) {
      feed.appendChild(el("div", null,
        el("b", null, alert.machine_name || ""), ` · ${alert.alert_type || ""} · ${fmtTime(alert.timestamp)}`));
    }
  }

  function machineOptions() {
    return state.machines.map((machine) => ({
      value: machine.name,
      label: machine.name + (machine.online ? "" : t("ms_offline_suffix", "（离线）")),
    }));
  }

  function syncSelectors() {
    const options = machineOptions();
    termMachine.setOptions(options);
    filesMachine.setOptions(options);
    monMachine.setOptions(options);
    state.term = termMachine.value;
    state.files = filesMachine.value;
    state.mon = monMachine.value;
    $("btn-term-connect").disabled = !options.length;
  }

  async function loadOverview() {
    const data = await api("overview");
    state.machines = data.machines || [];
    renderStats(data.stats, data.pending_confirms);
    renderMachines(state.machines);
    renderAlerts(data.alerts || []);
    syncSelectors();
  }

  /* ---------- 机器管理 ---------- */

  function machineForm(machine) {
    const name = MS.input({ id: "mf-name", placeholder: "web-1", value: machine ? machine.name : "" });
    name.disabled = !!machine;
    const ip = MS.input({
      id: "mf-ip", placeholder: "1.2.3.4",
      value: machine && machine.ip !== "****" ? machine.ip : "",
    });
    const port = MS.input({ id: "mf-port", type: "number", value: machine ? machine.port : 22 });
    const username = MS.input({ id: "mf-user", value: machine ? machine.username : "root" });
    const auth = MS.select({
      minWidth: 120,
      options: [{ value: "password", label: t("ms_auth_password", "密码") }, { value: "key", label: t("ms_auth_key", "密钥") }],
      value: machine ? (machine.auth_type || "password") : "password",
    });
    const group = MS.input({
      id: "mf-group", placeholder: "web",
      value: machine ? (machine.group || "") : "",
    });
    const expiry = MS.input({
      id: "mf-expiry", type: "date",
      value: machine ? (machine.expiry || "") : "",
    });
    const secret = MS.textarea({
      id: "mf-secret", rows: 4,
      placeholder: machine ? t("ms_secret_ph_keep", "留空表示不修改") : t("ms_secret_ph_new", "密码或私钥内容"),
    });
    const notes = MS.textarea({
      id: "mf-notes", rows: 2,
      value: machine ? (machine.notes || "") : "",
    });
    const form = el("div", { class: "ms-form-grid" },
      MS.field({ label: t("ms_f_name", "名称"), control: name }),
      MS.field({ label: t("ms_f_addr", "地址"), control: ip }),
      MS.field({ label: t("ms_f_port", "端口"), control: port }),
      MS.field({ label: t("ms_f_user", "用户名"), control: username }),
      MS.field({ label: t("ms_f_auth", "认证"), control: auth.el }),
      MS.field({ label: t("ms_f_group", "分组"), control: group }),
      MS.field({ label: t("ms_f_expiry", "到期日期（触发到期提醒）"), control: expiry }),
      MS.field({ label: t("ms_f_notes", "备注"), control: notes, span: true }),
      MS.field({ label: t("ms_f_secret", "凭据（密码或私钥内容）"), control: secret, span: true }),
    );
    return { form, fields: { name, ip, port, username, group, expiry, secret, notes }, auth };
  }

  async function openMachineModal(name) {
    let machine = null;
    if (name) {
      const data = await api("machines");
      machine = (data.machines || []).find((item) => item.name === name) || null;
    }
    const { form, fields, auth } = machineForm(machine);
    const modal = MS.modal({
      title: machine ? t("ms_edit_machine_title", "编辑机器：") + machine.name : t("ms_machine_modal_add", "添加机器"),
      body: form,
      actions: [
        {
          label: t("ms_save_test", "保存并测试"), primary: true, onClick: async (handle) => {
            const body = {
              name: fields.name.value.trim(),
              ip: fields.ip.value.trim(),
              port: parseInt(fields.port.value) || 22,
              username: fields.username.value.trim() || "root",
              auth_type: auth.value,
              group: fields.group.value.trim(),
              expiry: fields.expiry.value.trim(),
              notes: fields.notes.value,
            };
            if (fields.secret.value) {
              if (body.auth_type === "key") body.private_key = fields.secret.value;
              else body.password = fields.secret.value;
            }
            handle.setError("");
            try {
              if (machine) await api("machines/" + encodeURIComponent(machine.name), { method: "PUT", body: JSON.stringify(body) });
              else await api("machines", { method: "POST", body: JSON.stringify(body) });
              handle.close();
              toast(t("ms_saved", "已保存"));
              loadOverview();
            } catch (e) {
              handle.setError(e.message);
            }
          },
        },
        { label: t("ms_cancel", "取消") },
      ],
    });
    return modal;
  }

  async function removeMachine(name) {
    if (!confirm(tf("ms_confirm_remove_machine", "删除机器 {name}？", { name }))) return;
    try {
      await api("machines/" + encodeURIComponent(name), { method: "DELETE" });
      toast(t("ms_deleted", "已删除"));
      loadOverview();
    } catch (e) {
      toast(t("ms_delete_failed", "删除失败：") + e.message);
    }
  }

  /* ---------- 快捷执行 ---------- */

  function openExec(machine) {
    const input = MS.input({ id: "exec-command", placeholder: t("ms_cmd_ph", "命令") });
    const output = el("pre", { class: "ms-exec-output", id: "exec-output", hidden: "" });
    const body = el("div", null, input, output);
    let pendingToken = "";

    async function run() {
      const command = input.value.trim();
      if (!command) return;
      output.hidden = false;
      output.textContent = t("ms_running", "执行中…");
      try {
        const data = await api("exec", { method: "POST", body: JSON.stringify({ name: machine, command }) });
        if (data.needs_confirm) {
          pendingToken = data.token;
          output.textContent = data.message + "\n\n" + t("ms_confirm_prompt", "确认执行？在输入框输入 YES 后回车：");
          input.value = "";
          return;
        }
        let text = "";
        if (data.warning) text += data.warning + "\n";
        text += data.stdout || data.stderr || data.error || t("ms_no_output", "(无输出)");
        if (data.stderr && data.stdout) text += "\n[stderr]\n" + data.stderr;
        output.textContent = text;
      } catch (e) {
        output.textContent = t("ms_failed", "失败：") + e.message;
      }
    }

    async function confirmPending() {
      try {
        output.hidden = false;
        const done = await api("confirm", {
          method: "POST",
          body: JSON.stringify({ name: machine, token: pendingToken }),
        });
        output.textContent = done.stdout || done.stderr || done.error || t("ms_no_output", "(无输出)");
      } catch (e) {
        output.textContent = t("ms_confirm_failed", "确认失败：") + e.message;
      }
    }

    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      if (pendingToken) {
        if (input.value.trim().toUpperCase() === "YES") {
          pendingToken = "";
          input.value = "";
          confirmPending();
        }
      } else {
        run();
      }
    });

    const modal = MS.modal({
      title: t("ms_exec_title", "执行命令 · ") + machine,
      body,
      actions: [{ label: t("ms_run", "执行"), primary: true, onClick: run }, { label: t("ms_close", "关闭") }],
    });
    input.focus();
    return modal;
  }

  $("btn-add-machine").addEventListener("click", () => openMachineModal(""));
  $("btn-refresh").addEventListener("click", () => {
    loadOverview().catch((e) => toast(t("ms_refresh_failed", "刷新失败：") + e.message));
  });

  /* ---------- 终端 ---------- */

  const terminals = new Map();
  let activeTerm = "";

  let installModal = null;

  function handleWsControl(ws, term, raw) {
    let control;
    try {
      control = JSON.parse(raw);
    } catch (e) {
      return;
    }
    if (control.mstype === "confirm") {
      if (installModal) return;
      const body = el("div", null,
        el("div", null, t("ms_tmux_missing", "这台机器没有安装 tmux（会话托管依赖它，断线不丢现场）。")),
        el("div", { class: "ms-field-hint" }, t("ms_tmux_hint", "安装在本机执行；跳过则本次会话不持久。")));
      installModal = MS.modal({
        title: t("ms_install_tmux_title", "安装 tmux？"),
        body,
        onClose: () => { installModal = null; },
        actions: [
          {
            label: t("ms_install", "安装（推荐）"), primary: true,
            onClick: (handle) => {
              handle.close();
              if (ws.readyState === 1) ws.send('{"mstype":"install_tmux"}');
            },
          },
          {
            label: t("ms_skip", "跳过"),
            onClick: (handle) => {
              handle.close();
              if (ws.readyState === 1) ws.send('{"mstype":"skip"}');
            },
          },
        ],
      });
    } else if (control.mstype === "log") {
      term.writeln(String(control.text || ""));
    }
  }

  function openTerminalFor(machine) {
    document.querySelector('[data-tab="terminal"]').click();
    termMachine.setValue(machine);
    state.term = machine;
    (async () => {
      try {
        await ensureXterm();
        connectTerm(machine, $("term-session").value.trim() || "main");
      } catch (e) {
        toast(e.message);
      }
    })();
  }

  function activeTermSend(text) {
    const item = terminals.get(activeTerm);
    if (!item || item.ws.readyState !== 1) {
      toast(t("ms_no_terminal", "没有已连接的终端"));
      return;
    }
    item.ws.send(text);
    item.term.focus();
  }

  $("term-cmd").addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    const input = event.currentTarget;
    const command = input.value;
    if (!command) return;
    activeTermSend(command + "\r");
    input.value = "";
  });

  document.querySelectorAll("[data-quick]").forEach((button) => {
    button.addEventListener("click", () => {
      const seq = button.dataset.quick
        .replace(/\\x([0-9a-f]{2})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
        .replace("\\t", "\t");
      activeTermSend(seq);
    });
  });

  $("btn-term-connect").addEventListener("click", async () => {
    const machine = state.term;
    const session = $("term-session").value.trim() || "main";
    if (!machine) {
      toast(t("ms_add_first", "先添加机器"));
      return;
    }
    $("btn-term-connect").disabled = true;
    try {
      await ensureXterm();
      connectTerm(machine, session);
    } catch (e) {
      toast(e.message);
    } finally {
      $("btn-term-connect").disabled = false;
    }
  });

  function connectTerm(machine, session) {
    const key = machine + "/" + session;
    if (terminals.has(key)) {
      switchTerm(key);
      return;
    }
    $("term-wrap").innerHTML = "";
    const holder = el("div", { style: { height: "100%" } });
    $("term-wrap").appendChild(holder);
    const term = new window.Terminal({
      cursorBlink: true, scrollback: 10000, fontSize: 14,
      theme: { background: "rgba(2,6,16,0.0)", foreground: "#d7e3f4", cursor: "#e4b863" },
    });
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(holder);
    try { fit.fit(); } catch (e) { /* ignore */ }
    const proto = location.protocol === "https:" ? "wss://" : "ws://";
    const wsBase = location.pathname.replace(/\/app$/, "");
    const ws = new WebSocket(`${proto}${location.host}${wsBase}/ws/terminal?machine=${encodeURIComponent(machine)}&session=${encodeURIComponent(session)}&token=${encodeURIComponent(TOKEN)}`);
    ws.onopen = () => term.writeln(`\x1b[38;5;180m── ${key} · ${t("ms_tmux_hosted", "tmux 托管")} ──\x1b[0m`);
    ws.onmessage = (event) => {
      if (typeof event.data === "string" && event.data.startsWith('{"mstype"')) {
        handleWsControl(ws, term, event.data);
        return;
      }
      term.write(event.data);
    };
    ws.onerror = () => term.writeln("\r\n\x1b[31m── " + t("ms_ws_failed", "WebSocket 连接失败") + " ──\x1b[0m");
    ws.onclose = (event) => {
      const hint = event.code === 4404 ? t("ms_machine_missing", "机器不存在") : t("ms_session_remote", "会话仍在远端");
      term.writeln(`\r\n\x1b[38;5;180m── ${tf("ms_conn_closed", "连接已关闭（{hint}）", { hint })} ──\x1b[0m`);
    };
    term.onData((text) => {
      if (ws.readyState === 1) ws.send(text);
    });
    term.onResize(({ cols, rows }) => {
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: "resize", cols, rows }));
    });
    window.addEventListener("resize", () => {
      try { fit.fit(); } catch (e) { /* ignore */ }
    });
    terminals.set(key, { term, ws, fit, machine, session, holder });
    renderTermTabs();
    switchTerm(key);
  }

  function renderTermTabs() {
    const tabs = clear($("term-tabs"));
    for (const key of terminals.keys()) {
      const tab = el("span", {
        class: "ms-term-tab" + (key === activeTerm ? " active" : ""),
        onclick: (event) => {
          if (event.offsetX > event.currentTarget.clientWidth - 20) closeTerm(key);
          else switchTerm(key);
        },
      }, key + " ✕");
      tabs.appendChild(tab);
    }
  }

  function switchTerm(key) {
    activeTerm = key;
    const item = terminals.get(key);
    if (!item) return;
    const wrap = $("term-wrap");
    if (item.holder.parentElement !== wrap) {
      wrap.innerHTML = "";
      wrap.appendChild(item.holder);
    }
    try { item.fit.fit(); } catch (e) { /* ignore */ }
    item.term.focus();
    renderTermTabs();
  }

  function closeTerm(key) {
    const item = terminals.get(key);
    if (item) {
      try { item.ws.close(); item.term.dispose(); } catch (e) { /* ignore */ }
    }
    terminals.delete(key);
    const next = [...terminals.keys()][0];
    if (next) switchTerm(next);
    else {
      $("term-wrap").innerHTML = "";
      activeTerm = "";
    }
    renderTermTabs();
  }

  /* ---------- 文件 ---------- */

  function joinPath(base, name) {
    return base.endsWith("/") ? base + name : base + "/" + name;
  }

  async function loadFiles() {
    const machine = state.files;
    const path = $("files-path").value || "/";
    if (!machine) return;
    renderCrumb(path);
    const tableHost = clear($("files-table"));
    tableHost.appendChild(el("div", { class: "ms-empty" }, t("ms_loading", "加载中…")));
    try {
      const data = await api(`files?machine=${encodeURIComponent(machine)}&path=${encodeURIComponent(path)}`);
      const rows = (data.entries || []).map((entry) => ({
        entry,
        path: joinPath(path, entry.name),
      }));
      const table = MS.table({
        columns: [
          {
            label: t("ms_col_name", "名称"),
            render: (row) => el("span", {
              class: row.entry.is_dir ? "ms-dir" : "",
              onclick: row.entry.is_dir ? () => {
                $("files-path").value = row.path;
                loadFiles();
              } : null,
            }, (row.entry.is_dir ? "📁 " : "📄 ") + row.entry.name),
          },
          { label: t("ms_col_type", "类型"), render: (row) => (row.entry.is_dir ? t("ms_type_dir", "目录") : t("ms_type_file", "文件")) },
          { label: t("ms_col_size", "大小"), render: (row) => (row.entry.is_dir ? "–" : fmtSize(row.entry.size)) },
          { label: t("ms_col_mtime", "修改时间"), render: (row) => fmtTime(row.entry.mtime) },
          {
            label: t("ms_col_ops", "操作"),
            render: (row) => {
              const buttons = [];
              if (!row.entry.is_dir) {
                buttons.push(el("button", { class: "ms-btn", type: "button", onclick: () => downloadFile(machine, row.path) }, t("ms_download", "下载")));
                buttons.push(el("button", { class: "ms-btn", type: "button", onclick: () => editFile(machine, row.path) }, t("ms_card_edit", "编辑")));
              }
              buttons.push(el("button", { class: "ms-btn", type: "button", onclick: () => renameEntry(machine, path, row.entry.name) }, t("ms_rename", "改名")));
              buttons.push(el("button", {
                class: "ms-btn ms-btn-danger", type: "button",
                onclick: () => deleteEntry(machine, row.path, row.entry.is_dir),
              }, t("ms_card_delete", "删除")));
              return el("div", { class: "ms-row-actions" }, buttons);
            },
          },
        ],
        rows,
        empty: t("ms_empty_dir", "空目录"),
      });
      clear(tableHost).appendChild(table);
    } catch (e) {
      clear(tableHost).appendChild(el("div", { class: "ms-empty" }, e.message));
    }
  }

  function renderCrumb(path) {
    const crumb = clear($("files-crumb"));
    const parts = String(path || "/").split("/").filter(Boolean);
    crumb.appendChild(el("span", {
      class: "ms-crumb-seg",
      onclick: () => { $("files-path").value = "/"; loadFiles(); },
    }, "/"));
    let acc = "";
    for (const part of parts) {
      acc += "/" + part;
      const segPath = acc;
      crumb.append(el("span", { class: "ms-crumb-sep" }, "›"),
        el("span", {
          class: "ms-crumb-seg",
          onclick: () => { $("files-path").value = segPath; loadFiles(); },
        }, part));
    }
  }

  async function editFile(machine, path) {
    let content = "";
    try {
      const data = await api("files/read", {
        method: "POST",
        body: JSON.stringify({ name: machine, path }),
      });
      content = data.text || "";
    } catch (e) {
      toast(t("ms_read_failed", "读取失败：") + e.message);
      return;
    }
    const textarea = el("textarea", { class: "ms-input ms-editor", rows: 18, spellcheck: "false" });
    textarea.value = content;
    MS.modal({
      title: t("ms_edit_title", "编辑 · ") + path,
      width: 860,
      body: textarea,
      actions: [
        {
          label: t("ms_save", "保存"), primary: true, onClick: async (handle) => {
            try {
              await api("files/write", {
                method: "POST",
                body: JSON.stringify({ name: machine, path, text: textarea.value }),
              });
              handle.close();
              toast(t("ms_saved", "已保存"));
            } catch (e) {
              handle.setError(e.message);
            }
          },
        },
        { label: t("ms_cancel", "取消") },
      ],
    });
  }

  function renameEntry(machine, parent, name) {
    const input = MS.input({ value: name });
    MS.modal({
      title: t("ms_rename_title", "重命名"),
      width: 420,
      body: MS.field({ label: t("ms_new_name", "新名称"), control: input }),
      actions: [
        {
          label: t("ms_ok", "确定"), primary: true, onClick: async (handle) => {
            const newName = input.value.trim();
            if (!newName || newName === name) { handle.close(); return; }
            try {
              await api("files/rename", {
                method: "POST",
                body: JSON.stringify({ machine, path: joinPath(parent, name), name: newName }),
              });
              handle.close();
              loadFiles();
            } catch (e) {
              handle.setError(e.message);
            }
          },
        },
        { label: t("ms_cancel", "取消") },
      ],
    });
    input.focus();
  }

  function deleteEntry(machine, path, isDir) {
    if (!confirm(tf("ms_confirm_delete", "删除{type} {path}？", {
      type: isDir ? t("ms_del_dir", "目录（含全部内容）") : t("ms_del_file", "文件"),
      path,
    }))) return;
    api("files/delete", {
      method: "POST",
      body: JSON.stringify({ machine, path, is_dir: isDir }),
    }).then(() => { toast(t("ms_deleted", "已删除")); loadFiles(); })
      .catch((e) => toast(t("ms_delete_failed", "删除失败：") + e.message));
  }

  async function downloadFile(machine, remote) {
    toast(t("ms_downloading", "下载中…"));
    try {
      const data = await api("files/fetch", {
        method: "POST",
        body: JSON.stringify({ name: machine, remote_path: remote }),
      });
      const bytes = Uint8Array.from(atob(data.content_b64), (c) => c.charCodeAt(0));
      const link = el("a", { href: URL.createObjectURL(new Blob([bytes])), download: remote.split("/").pop() || "file" });
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (e) {
      toast(t("ms_download_failed", "下载失败：") + e.message);
    }
  }

  $("btn-files-go").addEventListener("click", loadFiles);
  $("btn-files-up").addEventListener("click", () => {
    const current = $("files-path").value || "/";
    $("files-path").value = current.replace(/\/[^/]*\/?$/, "") || "/";
    loadFiles();
  });
  $("btn-files-mkdir").addEventListener("click", () => {
    const machine = state.files;
    const parent = $("files-path").value || "/";
    if (!machine) { toast(t("ms_add_first", "先添加机器")); return; }
    const input = MS.input({ placeholder: t("ms_folder_ph", "文件夹名称") });
    MS.modal({
      title: t("ms_new_folder", "新建文件夹"),
      width: 420,
      body: MS.field({ label: t("ms_f_name", "名称"), control: input }),
      actions: [
        {
          label: t("ms_create", "创建"), primary: true, onClick: async (handle) => {
            const name = input.value.trim();
            if (!name) return;
            try {
              await api("files/mkdir", {
                method: "POST",
                body: JSON.stringify({ machine, path: parent, name }),
              });
              handle.close();
              loadFiles();
            } catch (e) {
              handle.setError(e.message);
            }
          },
        },
        { label: t("ms_cancel", "取消") },
      ],
    });
    input.focus();
  });
  $("files-path").addEventListener("keydown", (event) => {
    if (event.key === "Enter") loadFiles();
  });

  async function uploadFiles(fileList) {
    const machine = state.files;
    const path = $("files-path").value || "/";
    for (const file of fileList) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      try {
        await api("files/upload", {
          method: "POST",
          body: JSON.stringify({
            name: machine,
            remote_path: joinPath(path, file.name),
            content_b64: btoa(binary),
          }),
        });
        toast(tf("ms_uploaded", "已上传 {name}", { name: file.name }));
      } catch (e) {
        toast(tf("ms_upload_failed", "上传失败 {name}：", { name: file.name }) + e.message);
      }
    }
    filePicker.reset();
    loadFiles();
  }

  const filePicker = MS.filePicker({ label: t("ms_upload", "上传"), multiple: true, onFiles: uploadFiles });
  $("files-upload-host").appendChild(filePicker.el);

  /* ---------- 监控总览 ---------- */

  function renderMonGrid() {
    const grid = clear($("mon-grid"));
    if (!state.machines.length) {
      grid.appendChild(MS.empty(t("ms_mon_empty", "还没有机器。"), t("ms_add_machine", "＋ 添加机器"), () => openMachineModal("")));
      return;
    }
    for (const machine of state.machines) {
      const metrics = machine.metrics || {};
      const selected = machine.name === state.mon;
      const card = el("div", {
        class: "ms-card ms-machine ms-mon-card" + (selected ? " selected" : ""),
        onclick: () => {
          state.mon = machine.name;
          monMachine.setValue(machine.name, true);
          state.mon = machine.name;
          renderMonGrid();
          loadMonitor();
        },
      },
        el("div", { class: "ms-machine-head" },
          el("span", { class: "ms-machine-name" },
            el("span", { class: "ms-dot " + (machine.online ? "ms-dot-on" : "ms-dot-off") }),
            machine.name),
          el("span", { class: "ms-machine-meta" }, machine.online ? t("ms_stat_online", "在线") : t("ms_card_offline", "离线")),
        ),
        el("div", { class: "ms-machine-metrics" },
          el("div", { class: "ms-metric" }, "CPU", el("b", null, pct(metrics.cpu_percent))),
          el("div", { class: "ms-metric" }, t("ms_card_mem", "内存"), el("b", null, pct(metrics.mem_percent))),
          el("div", { class: "ms-metric" }, t("ms_card_disk", "磁盘"), el("b", null, pct(metrics.disk_percent))),
          el("div", { class: "ms-metric" }, "TCP",
            el("b", null, metrics.tcp != null ? String(Math.round(metrics.tcp)) : "–")),
        ),
      );
      grid.appendChild(card);
    }
  }

  async function loadMonitor() {
    if (!state.machines.length) await loadOverview();
    renderMonGrid();
    const machine = state.mon;
    if (!machine) return;
    const metric = monMetric.value;
    const hours = parseInt(monHours.value) || 24;
    const data = await api(`metrics?machine=${encodeURIComponent(machine)}&metric=${encodeURIComponent(metric)}&hours=${hours}`);
    drawChart($("mon-chart"), data.points || []);
  }

  async function refreshMonitor() {
    try {
      await api("check/" + encodeURIComponent(state.mon), { method: "POST" });
    } catch (e) { /* 检测失败仍尝试绘制已有历史 */ }
    await loadMonitor();
  }

  function drawChart(canvas, points) {
    const ctx = canvas.getContext("2d");
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = "rgba(255,255,255,0.03)";
    ctx.fillRect(0, 0, W, H);
    if (!points.length) {
      ctx.fillStyle = "#7c9cc4";
      ctx.font = "14px Inter, sans-serif";
      ctx.fillText(t("ms_chart_empty", "点「检测」立即采集一次；之后随监控轮自动积累成曲线"), 24, H / 2);
      return;
    }
    if (points.length === 1) {
      const p = points[0];
      ctx.fillStyle = "#e4b863";
      ctx.beginPath();
      ctx.arc(60, H / 2, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#7c9cc4";
      ctx.font = "14px Inter, sans-serif";
      ctx.fillText(tf("ms_chart_single", "当前值 {v}（{time}）— 积累多点后成曲线",
        { v: p[0], time: new Date(p[1] * 1000).toLocaleTimeString() }), 78, H / 2 + 5);
      return;
    }
    const values = points.map((point) => point[0]);
    const max = Math.max(...values, 1) * 1.15;
    const min = Math.min(...values, 0);
    const t0 = points[0][1];
    const t1 = points[points.length - 1][1] || t0 + 1;
    const pad = 36;
    const x = (t) => pad + ((t - t0) / (t1 - t0 || 1)) * (W - pad * 2);
    const y = (v) => H - pad - ((v - min) / (max - min || 1)) * (H - pad * 2);
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const gy = pad + ((H - pad * 2) * i) / 4;
      ctx.beginPath();
      ctx.moveTo(pad, gy);
      ctx.lineTo(W - pad, gy);
      ctx.stroke();
      ctx.fillStyle = "#33517a";
      ctx.font = "11px Inter, sans-serif";
      ctx.fillText((max - ((max - min) * i) / 4).toFixed(1), 4, gy + 4);
    }
    ctx.strokeStyle = "#e4b863";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, index) => {
      if (index) ctx.lineTo(x(point[1]), y(point[0]));
      else ctx.moveTo(x(point[1]), y(point[0]));
    });
    ctx.stroke();
    ctx.lineTo(x(t1), H - pad);
    ctx.lineTo(x(t0), H - pad);
    ctx.closePath();
    const gradient = ctx.createLinearGradient(0, 0, 0, H);
    gradient.addColorStop(0, "rgba(228,184,99,0.18)");
    gradient.addColorStop(1, "rgba(228,184,99,0)");
    ctx.fillStyle = gradient;
    ctx.fill();
  }

  /* ---------- 审计 ---------- */

  const auditMachine = MS.select({ placeholder: t("ms_audit_machine_all", "全部机器"), minWidth: 150 });
  $("audit-machine").appendChild(auditMachine.el);

  async function loadAudit() {
    if (!state.machines.length) await loadOverview();
    auditMachine.setOptions(machineOptions());
    const machineFilter = auditMachine.value || "";
    const actionFilter = $("audit-action").value;
    let items = [];
    try {
      const data = await api(`history?limit=200`);
      items = data.items || [];
    } catch (e) { /* ignore */ }
    if (machineFilter) items = items.filter((row) => row.machine === machineFilter);
    if (actionFilter) {
      items = items.filter((row) => {
        const action = String(row.action || "");
        if (actionFilter === "machine") return action.startsWith("machine");
        if (actionFilter === "file_write") return action === "file_write";
        if (actionFilter === "file_delete") return action === "file_delete";
        if (actionFilter === "session") return action.startsWith("session");
        if (actionFilter === "terminal") return action.startsWith("terminal");
        return action === actionFilter;
      });
    }
    const table = MS.table({
      columns: [
        { label: t("ms_col_time", "时间"), render: (row) => fmtTime(row.ts), width: "160px" },
        { label: t("ms_col_machine", "机器"), key: "machine" },
        { label: t("ms_col_actor", "操作者"), key: "actor" },
        { label: t("ms_col_action", "动作"), key: "action" },
        { label: t("ms_col_detail", "内容"), render: (row) => String(row.detail || "").slice(0, 140) },
        { label: t("ms_col_level", "级别"), render: (row) => MS.badge(row.level, row.level) },
      ],
      rows: items.slice(0, 120),
      empty: t("ms_audit_empty", "暂无记录 —— 控制台、AI、聊天的一切操作都会出现在这里"),
    });
    clear($("audit-table")).appendChild(table);

    let alerts = [];
    try {
      const data = await api("alerts?limit=50");
      alerts = data.alerts || [];
    } catch (e) { /* ignore */ }
    const alertTable = MS.table({
      columns: [
        { label: t("ms_col_time", "时间"), render: (row) => fmtTime(row.timestamp), width: "160px" },
        { label: t("ms_col_machine", "机器"), key: "machine_name" },
        { label: t("ms_col_action", "动作"), key: "alert_type" },
        { label: t("ms_col_detail", "内容"), key: "message" },
      ],
      rows: alerts,
      empty: t("ms_no_alerts", "暂无告警"),
    });
    clear($("audit-alerts")).appendChild(alertTable);
  }

  $("audit-action").addEventListener("change", loadAudit);

  /* ---------- 设置 ---------- */

  const CFG_BOOL = ["prefer_tmux", "allow_paste_keys", "monitor_enabled",
    "public_page", "public_show_host", "public_geo"];

  const SETTINGS_SECTIONS = [
    {
      title: t("ms_s_exec", "执行与会话"),
      items: [
        { key: "exec_timeout", label: t("ms_s_exec_timeout", "命令超时（秒）"), type: "number" },
        { key: "max_sessions", label: t("ms_s_max_sessions", "会话上限"), type: "number" },
        { key: "prefer_tmux", label: t("ms_s_prefer_tmux", "会话优先跑在远端 tmux（断线不丢）"), type: "switch" },
        { key: "allow_paste_keys", label: t("ms_s_paste_keys", "允许粘贴私钥内容"), type: "switch" },
      ],
    },
    {
      title: t("ms_s_monitor", "监控与告警"),
      items: [
        { key: "monitor_enabled", label: t("ms_s_monitor_enabled", "开启定时监控"), type: "switch" },
        { key: "check_interval", label: t("ms_s_interval", "采集间隔（秒）"), type: "number" },
        { key: "cpu_threshold", label: t("ms_s_cpu_threshold", "CPU 阈值（%）"), type: "number" },
        { key: "mem_threshold", label: t("ms_s_mem_threshold", "内存阈值（%）"), type: "number" },
        { key: "disk_threshold", label: t("ms_s_disk_threshold", "磁盘阈值（%）"), type: "number" },
        { key: "load_factor", label: t("ms_s_load_factor", "负载倍数（×核数）"), type: "number", step: "0.1" },
        { key: "alert_cooldown_min", label: t("ms_s_cooldown", "告警冷却（分钟）"), type: "number" },
        { key: "history_retention_days", label: t("ms_s_retention", "历史保留（天）"), type: "number" },
      ],
    },
    {
      title: t("ms_s_public", "公开状态页"),
      items: [
        { key: "public_page", label: t("ms_s_public_page", "开启公开页（/MyServer/public，免鉴权）"), type: "switch" },
        { key: "public_title", label: t("ms_s_public_title", "页面标题"), type: "text" },
        { key: "public_refresh_seconds", label: t("ms_s_public_refresh", "自动刷新间隔（秒，0 = 仅手动）"), type: "number" },
        { key: "public_geo", label: t("ms_s_public_geo", "自动查询国家国旗（ipapi.co，缓存 24h）"), type: "switch" },
        { key: "public_show_host", label: t("ms_s_public_show_host", "展示打码后的主机地址"), type: "switch" },
        { type: "public_fields" },
      ],
    },
    {
      title: t("ms_s_transfer", "传输"),
      items: [
        { key: "transfer_max_mb", label: t("ms_s_transfer_max", "单文件上限（MB）"), type: "number" },
      ],
    },
  ];

  const PUBLIC_FIELD_LABELS = {
    cpu: "CPU", mem: t("ms_pf_mem", "内存"), disk: t("ms_pf_disk", "磁盘"), load: t("ms_pf_load", "负载"),
    uptime: t("ms_pf_uptime", "运行时长"), history: t("ms_pf_history", "在线历史格子"), events: t("ms_pf_events", "最近事件"),
  };

  function renderSettings() {
    const host = clear($("settings-form"));
    for (const section of SETTINGS_SECTIONS) {
      const card = el("div", { class: "ms-card" });
      card.appendChild(el("h2", { class: "ms-section-title" }, section.title));
      const grid = el("div", { class: "ms-form-grid" });
      for (const item of section.items) {
        if (item.type === "public_fields") {
          const wrap = el("div", { class: "ms-form-span" });
          wrap.appendChild(el("div", { class: "ms-field-hint" },
            t("ms_s_fields_hint", "公开页展示的字段（全部取消 = 只显示机器名与在线状态）：")));
          const grid2 = el("div", { class: "ms-form-grid" });
          for (const [key, label] of Object.entries(PUBLIC_FIELD_LABELS)) {
            grid2.appendChild(MS.switch({ id: "pf-" + key, label }));
          }
          wrap.appendChild(grid2);
          card.appendChild(wrap);
          continue;
        }
        if (item.type === "switch") {
          grid.appendChild(MS.switch({ id: "cf-" + item.key, label: item.label }));
        } else {
          grid.appendChild(MS.field({
            label: item.label,
            control: MS.input({
              id: "cf-" + item.key,
              type: item.type,
              step: item.step || "",
            }),
          }));
        }
      }
      if (grid.children.length) card.appendChild(grid);
      host.appendChild(card);
    }
  }

  const PUBLIC_FIELD_ORDER = ["cpu", "mem", "disk", "load", "uptime", "history", "events"];

  async function loadSettings() {
    const config = await api("config");
    for (const [key, value] of Object.entries(config)) {
      const input = $("cf-" + key);
      if (!input) continue;
      if (CFG_BOOL.includes(key)) input.checked = !!value;
      else input.value = value;
    }
    const fields = config.public_fields || [];
    for (const key of PUBLIC_FIELD_ORDER) {
      const box = $("pf-" + key);
      if (box) box.checked = fields.includes(key);
    }
  }

  $("btn-cfg-save").addEventListener("click", async () => {
    const body = {};
    document.querySelectorAll("[id^='cf-']").forEach((input) => {
      const key = input.id.slice(3);
      body[key] = CFG_BOOL.includes(key) ? input.checked : input.value;
    });
    body.public_fields = PUBLIC_FIELD_ORDER.filter((key) => {
      const box = $("pf-" + key);
      return box && box.checked;
    });
    $("btn-cfg-save").disabled = true;
    try {
      await api("config", { method: "POST", body: JSON.stringify(body) });
      toast(t("ms_saved_effective", "已保存，立即生效"));
    } catch (e) {
      toast(t("ms_save_failed", "保存失败：") + e.message);
    } finally {
      $("btn-cfg-save").disabled = false;
    }
  });

  /* ---------- 导航 ---------- */

  document.querySelectorAll(".ms-nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".ms-nav-item").forEach((node) => node.classList.remove("active"));
      document.querySelectorAll(".ms-tab").forEach((node) => node.classList.remove("active"));
      item.classList.add("active");
      $("tab-" + item.dataset.tab).classList.add("active");
      if (item.dataset.tab === "audit") loadAudit();
      if (item.dataset.tab === "monitor") refreshMonitor();
      if (item.dataset.tab === "overview") loadOverview();
      if (item.dataset.tab === "settings") loadSettings();
      if (item.dataset.tab === "files") loadFiles();
    });
  });

  /* ---------- 启动 ---------- */

  window.MSI18N.apply();

  const langButton = $("btn-lang");
  if (langButton) {
    langButton.textContent = window.MSI18N.nextLabel();
    langButton.addEventListener("click", () => {
      try {
        localStorage.setItem("ms_lang", window.MSI18N.next());
      } catch (e) { /* ignore */ }
      location.reload();
    });
  }

  renderSettings();
  loadOverview().catch((e) => toast(t("ms_load_failed", "加载失败：") + e.message));
})();
