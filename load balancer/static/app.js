const state = {
  lastRequest: null,
  charts: {},
  autoTrafficHandle: null,
  lastAssignmentFlashKey: null,
  weightDebounce: {},
  algorithmOptionsReady: false,
};

const $ = (id) => document.getElementById(id);

const CHART_ANIMATION = {
  duration: 550,
  easing: "easeOutQuart",
};

const CHART_TEXT = "#b3b3b3";
const CHART_GRID = "#303030";

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || res.statusText);
  }
  return res.json();
}

async function postAlgorithm(algorithm) {
  await api("/algorithm", {
    method: "POST",
    body: JSON.stringify({ algorithm }),
  });
}

function debounceWeightPost(serverId, weight) {
  const key = String(serverId);
  if (state.weightDebounce[key]) {
    clearTimeout(state.weightDebounce[key]);
  }
  state.weightDebounce[key] = setTimeout(async () => {
    delete state.weightDebounce[key];
    try {
      await api(`/server/${serverId}/weight`, {
        method: "POST",
        body: JSON.stringify({ weight: Number(weight) }),
      });
    } catch (err) {
      console.error("weight update failed", err);
    }
  }, 180);
}

function flashServerCard(serverId) {
  const card = document.querySelector(`.server-card[data-server-id="${serverId}"]`);
  if (!card) return;
  card.classList.remove("flash-hit");
  void card.offsetWidth;
  card.classList.add("flash-hit");
  setTimeout(() => card.classList.remove("flash-hit"), 800);
}

function maybeFlashFromAssignments(rows) {
  if (!rows || !rows.length) return;
  const head = rows[0];
  const key = `${head.request_id}:${head.server_id}`;
  if (key === state.lastAssignmentFlashKey) return;
  state.lastAssignmentFlashKey = key;
  flashServerCard(head.server_id);
}

function syncAlgorithmUi(activeAlgorithm, algorithmsMeta) {
  const select = $("algorithm-select");
  const pill = $("active-algorithm-pill");

  if (!state.algorithmOptionsReady && algorithmsMeta?.length) {
    select.innerHTML = "";
    algorithmsMeta.forEach((algo) => {
      const opt = document.createElement("option");
      opt.value = algo.name;
      opt.textContent = `${formatAlgoName(algo.name)}`;
      select.appendChild(opt);
    });
    state.algorithmOptionsReady = true;
  }

  if (pill) {
    pill.textContent = formatAlgoName(activeAlgorithm);
  }

  if (state.algorithmOptionsReady && activeAlgorithm) {
    const allowed = new Set([...select.options].map((o) => o.value));
    if (allowed.has(activeAlgorithm)) {
      select.value = activeAlgorithm;
    }
  }
}

function formatAlgoName(name) {
  if (!name) return "—";
  return name.replace(/_/g, " ");
}

function renderServers(servers) {
  const grid = $("server-grid");
  grid.innerHTML = "";
  servers.forEach((s) => {
    const card = document.createElement("div");
    card.className = `server-card${s.failed ? " failed" : ""}`;
    card.dataset.serverId = String(s.id);
    const utilPct = Math.round((s.utilization || 0) * 100);
    const w = Number(s.weight);
    const weightVal = Number.isFinite(w) ? w : 1;
    card.innerHTML = `
      <div class="pill">ID ${s.id}</div>
      <h3>${escapeHtml(s.name)}</h3>
      <div class="meta">
        <div>Load</div><div>${s.current_load} / ${s.max_capacity}</div>
        <div>Connections</div><div>${s.active_connections}</div>
        <div>Queue</div><div>${s.queue_length}</div>
        <div>Latency</div><div>${s.failed ? "offline" : `${s.response_time_ms} ms`}</div>
      </div>
      <div class="util-bar"><div class="util-fill" style="width:${utilPct}%"></div></div>
      <label class="weight">
        Weight (0.1–3.0)
        <div class="weight-row">
          <input type="range" min="0.1" max="3" step="0.05" value="${weightVal}"
            data-server="${s.id}" class="weight-slider" ${s.failed ? "disabled" : ""} />
          <span class="weight-value" data-weight-label="${s.id}">${weightVal.toFixed(2)}</span>
        </div>
      </label>
      <div class="server-actions">
        <button type="button" class="btn btn-outline-danger btn-failure" data-fail-btn="${s.id}"
          data-failed="${s.failed ? "1" : "0"}">
          ${s.failed ? "Restore AP" : "Simulate AP failure"}
        </button>
      </div>
    `;
    grid.appendChild(card);
  });

  grid.querySelectorAll(".weight-slider").forEach((input) => {
    const id = Number(input.dataset.server);
    const label = grid.querySelector(`[data-weight-label="${id}"]`);
    input.addEventListener("input", () => {
      const v = Number(input.value);
      if (label) label.textContent = v.toFixed(2);
      debounceWeightPost(id, v);
    });
  });

  grid.querySelectorAll(".btn-failure").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = Number(btn.dataset.failBtn);
      const currentlyFailed = btn.dataset.failed === "1";
      const failed = !currentlyFailed;
      try {
        await api(`/server/${id}/failure`, {
          method: "POST",
          body: JSON.stringify({ failed }),
        });
        await refresh();
      } catch (err) {
        console.error("failure toggle failed", err);
      }
    });
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderAssignments(rows) {
  const log = $("assignment-log");
  log.innerHTML = "";
  
  if (!rows || !rows.length) {
    log.innerHTML = `<div class="log-row"><div>—</div><div>No assignments yet.</div></div>`;
    return;
  }
  
  rows.forEach((row) => {
    const line = document.createElement("div");
    line.className = "log-row";
    const ip = row.ip_address || "127.0.0.1";
    line.innerHTML = `
      <div class="mono">#${row.request_id}</div>
      <div>
        <strong>${escapeHtml(row.algorithm)}</strong>
        → ${escapeHtml(row.server_name)}
        <div style="margin-top: 0.3rem;">
          <span style="background: #333; color: #00a8e1; border: 1px solid #444; padding: 0.15rem 0.35rem; border-radius: 4px; font-family: ui-monospace, monospace; font-size: 0.7rem; font-weight: 600; margin-right: 0.4rem;">
            ${escapeHtml(ip)}
          </span>
          <span class="muted">${escapeHtml(row.user_type)} · ${row.work_units} wu</span>
        </div>
      </div>`;
    log.appendChild(line);
  });
}

function lineChartLayoutOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: CHART_ANIMATION,
    plugins: {
      legend: { labels: { color: CHART_TEXT } },
    },
    scales: {
      x: {
        ticks: { color: CHART_TEXT },
        grid: { color: CHART_GRID },
      },
      y: {
        beginAtZero: true,
        ticks: { color: CHART_TEXT },
        grid: { color: CHART_GRID },
      },
    },
  };
}

function yScaleZero() {
  return {
    beginAtZero: true,
    min: 0,
    ticks: { color: CHART_TEXT },
    grid: { color: CHART_GRID },
  };
}

function updateCharts(history, servers) {
  if (!history || !window.Chart) return;
  const labels = history.sim_time;

  if (!state.charts.throughput) {
    state.charts.throughput = new Chart($("chart-throughput"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Throughput (rps)",
            data: history.throughput_rps,
            borderColor: "#00a8e1",
            tension: 0.25,
            fill: false,
          },
        ],
      },
      options: {
        ...lineChartLayoutOptions(),
        scales: {
          x: lineChartLayoutOptions().scales.x,
          y: yScaleZero(),
        },
      },
    });
  } else {
    state.charts.throughput.data.labels = labels;
    state.charts.throughput.data.datasets[0].data = history.throughput_rps;
    state.charts.throughput.update();
  }

  if (!state.charts.latency) {
    state.charts.latency = new Chart($("chart-latency"), {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Avg latency (ms)",
            data: history.latency_ms,
            borderColor: "#e50914",
            tension: 0.25,
            fill: false,
          },
        ],
      },
      options: {
        ...lineChartLayoutOptions(),
        scales: {
          x: lineChartLayoutOptions().scales.x,
          y: yScaleZero(),
        },
      },
    });
  } else {
    state.charts.latency.data.labels = labels;
    state.charts.latency.data.datasets[0].data = history.latency_ms;
    state.charts.latency.update();
  }

  const utilLabels = servers.map((s) => s.name.split(" ")[0]);
  const utilData = servers.map((s) => Math.round((s.utilization || 0) * 100));

  if (!state.charts.util) {
    state.charts.util = new Chart($("chart-util"), {
      type: "bar",
      data: {
        labels: utilLabels,
        datasets: [
          {
            label: "Utilization %",
            data: utilData,
            backgroundColor: "#00a8e1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: CHART_ANIMATION,
        plugins: {
          legend: { labels: { color: CHART_TEXT } },
        },
        scales: {
          x: {
            ticks: { color: CHART_TEXT },
            grid: { color: CHART_GRID },
          },
          y: {
            max: 100,
            beginAtZero: true,
            min: 0,
            ticks: { color: CHART_TEXT },
            grid: { color: CHART_GRID },
          },
        },
      },
    });
  } else {
    state.charts.util.data.labels = utilLabels;
    state.charts.util.data.datasets[0].data = utilData;
    state.charts.util.update();
  }
}

function syncDdosUi(ddosActive) {
  const banner = $("ddos-banner");
  const btn = $("btn-ddos-toggle");
  const active = !!ddosActive;
  document.body.classList.toggle("ddos-active", active);
  if (banner) {
    banner.hidden = !active;
  }
  if (btn) {
    btn.dataset.active = active ? "true" : "false";
    btn.textContent = active ? "Stop DDoS attack" : "Start DDoS attack";
  }
}

async function refresh() {
  const data = await api("/metrics");
  $("kpi-throughput").textContent = `${data.rolling_throughput_rps} rps`;
  $("kpi-latency").textContent = `${data.average_latency_ms} ms`;
  $("kpi-fairness").textContent = data.fairness_jain.toFixed(3);
  $("kpi-assignments").textContent = data.assignments;
  const blockedEl = $("kpi-blocked");
  if (blockedEl) {
    blockedEl.textContent = String(data.blocked_requests ?? 0);
  }

  const wafToggle = $("waf-toggle");
  if (wafToggle && typeof data.waf_enabled === "boolean") {
    wafToggle.checked = data.waf_enabled;
  }

  syncDdosUi(data.ddos_active);

  syncAlgorithmUi(data.active_algorithm, data.algorithms);
  renderServers(data.servers);
  maybeFlashFromAssignments(data.recent_assignments);
  renderAssignments(data.recent_assignments);
  updateCharts(data.history, data.servers);
}

function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

async function runAutoTrafficBatch() {
  const auto = $("auto-generate-traffic");
  if (!auto || !auto.checked) return;

  const rateSelect = $("traffic-rate-select");
  const rateMode = rateSelect ? rateSelect.value : "medium";
  
  let min = 2, max = 5;
  if (rateMode === "low") {
    min = 1; max = 3;
  } else if (rateMode === "high") {
    min = 8; max = 15;
  } else if (rateMode === "stress") {
    min = 20; max = 40;
  }

  const n = randomInt(min, max);
  const algorithm = $("algorithm-select").value;
  try {
    for (let i = 0; i < n; i += 1) {
      const payload = await api("/generate_request", { method: "POST" });
      state.lastRequest = payload.request;
      await api("/assign_request", {
        method: "POST",
        body: JSON.stringify({ request: payload.request, algorithm }),
      });
    }
    await refresh();
  } catch (err) {
    console.error("auto traffic batch failed", err);
  }
}

function startAutoTraffic() {
  if (state.autoTrafficHandle) {
    clearInterval(state.autoTrafficHandle);
  }
  state.autoTrafficHandle = setInterval(() => {
    runAutoTrafficBatch();
  }, 1000);
}

function stopAutoTraffic() {
  if (state.autoTrafficHandle) {
    clearInterval(state.autoTrafficHandle);
    state.autoTrafficHandle = null;
  }
}

async function init() {
  await refresh().catch(console.error);

  const select = $("algorithm-select");

  select.addEventListener("change", async () => {
    const algorithm = select.value;
    try {
      await postAlgorithm(algorithm);
      await refresh();
    } catch (err) {
      console.error("algorithm switch failed", err);
      await refresh();
    }
  });

  $("apply-algorithm").addEventListener("click", async () => {
    const algorithm = select.value;
    try {
      await postAlgorithm(algorithm);
      await refresh();
    } catch (err) {
      console.error(err);
    }
  });

  $("waf-toggle").addEventListener("change", async (evt) => {
    const enabled = evt.target.checked;
    try {
      await api("/waf", {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
      await refresh();
    } catch (err) {
      console.error("WAF toggle failed", err);
      await refresh();
    }
  });

  $("btn-ddos-toggle").addEventListener("click", async () => {
    const btn = $("btn-ddos-toggle");
    const currently = btn.dataset.active === "true";
    const next = !currently;
    try {
      await api("/ddos", {
        method: "POST",
        body: JSON.stringify({ active: next }),
      });
      await refresh();
    } catch (err) {
      console.error("DDoS toggle failed", err);
    }
  });

  $("btn-generate").addEventListener("click", async () => {
    const payload = await api("/generate_request", { method: "POST" });
    state.lastRequest = payload.request;
    $("request-preview").textContent = JSON.stringify(payload.request, null, 2);
  });

  $("btn-assign").addEventListener("click", async () => {
    if (!state.lastRequest) {
      $("request-preview").textContent = "Generate a request first.";
      return;
    }
    const algorithm = $("algorithm-select").value;
    await api("/assign_request", {
      method: "POST",
      body: JSON.stringify({ request: state.lastRequest, algorithm }),
    });
    await refresh();
  });

  $("btn-burst").addEventListener("click", async () => {
    await api("/burst?count=24", { method: "POST" });
    await refresh();
  });

  // Pro Feature: Toggle logic for Normal vs Attack Source
  const ipModeRadios = document.querySelectorAll('input[name="ip_mode"]');
  ipModeRadios.forEach((radio) => {
    radio.addEventListener("change", (e) => {
      const ipInput = $("custom-ip");
      const userSelect = $("custom-user");
      
      if (e.target.value === "fixed") {
        ipInput.disabled = false;
        ipInput.value = "192.168.1.99";
        userSelect.value = "malicious_bot";
      } else {
        ipInput.disabled = true;
        ipInput.value = "Auto-generated";
      }
    });
  });

  // Custom Request Tool Listener
  $("btn-send-custom").addEventListener("click", async () => {
    const mode = document.querySelector('input[name="ip_mode"]:checked').value;
    let ip;
    
    if (mode === "random") {
      ip = `10.0.${randomInt(0, 5)}.${randomInt(1, 254)}`;
    } else {
      ip = $("custom-ip").value || "192.168.1.99";
    }

    const userType = $("custom-user").value;
    const priority = randomInt(1, 5);
    const size = Number((Math.random() * 23 + 2).toFixed(2));
    const reqId = Math.floor(Math.random() * 100000) + 10000; 
    
    const requestPayload = {
      id: reqId,
      user_type: userType,
      priority: priority,
      size: size,
      ip_address: ip
    };
    
    const algorithm = $("algorithm-select").value;
    
    try {
      await api("/assign_request", {
        method: "POST",
        body: JSON.stringify({ request: requestPayload, algorithm }),
      });
      await refresh();
    } catch (err) {
      console.error("Custom request failed", err);
    }
  });

  $("auto-generate-traffic").addEventListener("change", (evt) => {
    if (evt.target.checked) {
      startAutoTraffic();
    } else {
      stopAutoTraffic();
    }
  });

  if ($("auto-generate-traffic")?.checked) {
    startAutoTraffic();
  }

  setInterval(() => {
    refresh().catch(console.error);
  }, 900);
}

window.addEventListener("DOMContentLoaded", init);