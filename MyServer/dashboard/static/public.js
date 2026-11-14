// 公开状态页：只读监控缓存；历史格子来自 online 指标
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const t = window.MSI18N.t;
  const tf = window.MSI18N.tf;
  let timer = null;

  function esc(text) {
    const div = document.createElement("div");
    div.textContent = String(text == null ? "" : text);
    return div.innerHTML;
  }

  function fmtUptime(seconds) {
    if (!seconds) return "–";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    return days ? `${days}d${hours}h` : `${Math.floor(seconds / 3600)}h${Math.floor((seconds % 3600) / 60)}m`;
  }

  function fmtChecked(ts) {
    if (!ts) return "–";
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function bar(pct) {
    const value = pct == null ? 0 : Math.min(100, Math.max(0, pct));
    const hot = value >= 90 ? " hot" : "";
    return `<div class="bar"><i class="${hot}" style="width:${value.toFixed(0)}%"></i></div>`;
  }

  function metric(label, value, pct, extra) {
    const text = pct == null ? "–" : pct.toFixed(0) + "%";
    return `
      <div class="metric">
        <div class="metric-label">${esc(label)}</div>
        <div class="metric-value${pct != null && pct >= 90 ? " accent" : ""}">${text}</div>
        ${extra ? `<div class="metric-extra">${esc(extra)}</div>` : ""}
        ${bar(pct)}
      </div>`;
  }

  function flag(code) {
    if (!code || code.length !== 2) return "";
    const base = 0x1f1e6;
    return String.fromCodePoint(...[...code.toUpperCase()].map((c) => base + c.charCodeAt(0) - 65));
  }

  function render(data) {
    const fields = data.fields || [];
    const show = (key) => fields.includes(key);
    document.title = data.title || "Server Status";
    $("page-title").textContent = data.title || "Server Status";
    $("page-sub").textContent =
      tf("ms_pub_summary", "{total} 台机器 · {online} 在线", { total: data.stats.total, online: data.stats.online });

    $("st-total").textContent = data.stats.total;
    $("st-online").textContent = data.stats.online;
    const first = (data.machines || [])[0];
    $("st-updated").textContent = fmtChecked(first ? first.checked_at : 0);
    $("st-refresh").textContent = data.refresh > 0 ? data.refresh + "s" : t("ms_pub_manual", "手动");

    $("machine-list").innerHTML = (data.machines || []).map((m) => {
      const cells = [];
      if (show("cpu")) cells.push(metric("CPU", m.cpu));
      if (show("mem")) cells.push(metric(t("ms_pub_mem", "内存"), m.mem, m.mem_text));
      if (show("disk")) cells.push(metric(t("ms_pub_disk", "磁盘"), m.disk, m.disk_text));
      if (show("load")) {
        cells.push(`<div class="metric"><div class="metric-label">${t("ms_pub_load", "负载")}</div><div class="metric-value">${m.load1 != null ? m.load1.toFixed(2) : "–"}</div></div>`);
      }
      if (show("uptime")) {
        cells.push(`<div class="metric"><div class="metric-label">${t("ms_pub_uptime", "运行")}</div><div class="metric-value">${esc(fmtUptime(m.uptime_s))}</div></div>`);
      }
      const flagEmoji = flag(m.country_code);
      return `
      <article class="machine-card">
        <div class="machine-head">
          <div class="machine-id">
            <span class="dot ${m.online ? "on" : "off"}"></span>
            <span class="machine-name">${esc(m.name)}</span>
            ${flagEmoji ? `<span class="flag" title="${esc(m.country_code)}">${flagEmoji}</span>` : ""}
          </div>
          <div class="machine-meta">
            ${m.host ? `<span class="mono">${esc(m.host)}</span>` : ""}
            <span>${esc(m.summary || "")}</span>
          </div>
        </div>
        ${cells.length ? `<div class="metrics">${cells.join("")}</div>` : ""}
      </article>`;
    }).join("") || `<div class="glass-panel">${t("ms_pub_no_machines", "暂无机器")}</div>`;

    const heading = document.querySelector(".subheading");
    const feed = $("event-feed");
    if (!show("events")) {
      heading.hidden = true;
      feed.hidden = true;
    } else {
      heading.hidden = false;
      feed.hidden = false;
      feed.innerHTML = (data.alerts || []).map((a) => {
        const time = a.time ? new Date(a.time * 1000).toLocaleString() : "";
        const offline = String(a.type || "").includes("offline");
        return `<div><span class="dot ${offline ? "off" : "on"}"></span><b>${esc(a.machine)}</b> · ${esc(a.type)} · ${time}</div>`;
      }).join("") || `<div>${t("ms_pub_no_events", "暂无事件")}</div>`;
    }
  }

  async function refresh() {
    try {
      const response = await fetch("api/public/overview", { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      render(data);
      clearInterval(timer);
      if (data.refresh > 0) {
        timer = setInterval(refresh, Math.max(10, data.refresh) * 1000);
      }
    } catch (e) {
      /* 静默重试 */
    }
  }

  $("btn-refresh").addEventListener("click", refresh);
  window.MSI18N.apply();
  refresh();
})();
