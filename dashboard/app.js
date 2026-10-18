/**
 * QuantaSHI Live Control Centre — Unified Event-Driven Architecture
 * Connects User Interface (Web Network), Server Interface (2D Rack),
 * and System Interface (Decision Engine) in a single synchronized loop.
 */

const $ = (selector) => document.querySelector(selector);
const number = (value, digits = 0) => Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: digits });
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

// Server naming mapping: srv_gpu_01 -> Server A, srv_acc_02 -> Server B, srv_cpu_03 -> Server C
const SERVER_NAMES = {
  'srv_gpu_01': { letter: 'Server A', title: 'High-Performance GPU', model: 'NVIDIA H100 PCIe 80GB HBM3', color: '#1d70b8' },
  'srv_acc_02': { letter: 'Server B', title: 'Energy-Efficient Tensor', model: 'NVIDIA L4 24GB / IBM Telum', color: '#1e824c' },
  'srv_cpu_03': { letter: 'Server C', title: 'General-Purpose CPU', model: 'Intel Xeon Platinum 8480+', color: '#b45309' },
};

// --- Global UI State ---
const uiState = {
  canvas: null,
  ctx: null,
  nodes: [],
  nodeMap: new Map(),
  originNode: null,
  dcNode: null,
  pulses: [],
  selectedNode: null,
  lastSnapshot: null,
  initializedCanvas: false,
};

// --- Control Simulation API ---
async function control(action, extra = {}) {
  const response = await fetch('/api/simulation/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, ...extra })
  });
  if (!response.ok) throw new Error('Simulation control request failed');
  render(await response.json());
}

function metric(label, value, sub = '') {
  return `<article class="metric"><span class="label">${label}</span><span class="value">${value}</span><span class="sub">${sub}</span></article>`;
}

// --- 1. Web Network Node Generator (White + Blue + Grey Corporate Style) ---
function initNetworkNodes() {
  const canvas = $('#network-canvas');
  if (!canvas) return;
  uiState.canvas = canvas;
  uiState.ctx = canvas.getContext('2d');

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = rect.width || 800;
  const h = rect.height || 480;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  uiState.ctx.scale(dpr, dpr);

  uiState.nodes = [];
  uiState.nodeMap.clear();

  // Top Origin User: U-ORIGIN
  uiState.originNode = {
    id: 'U-ORIGIN',
    label: 'U-ORIGIN',
    x: w * 0.12,
    y: h * 0.5,
    radius: 12,
    isOrigin: true,
    status: 'ACTIVE',
  };

  // Data Center Target Hub on Right
  uiState.dcNode = {
    id: 'DC-GATEWAY',
    label: 'DATA CENTER',
    x: w * 0.88,
    y: h * 0.5,
    radius: 16,
    isDC: true,
    status: 'ACTIVE',
  };

  // 100 User Nodes arranged in clean clustered constellation between Origin and DC
  const totalUsers = 100;
  const cols = 10;
  const rows = 10;
  const startX = w * 0.22;
  const endX = w * 0.78;
  const startY = h * 0.12;
  const endY = h * 0.88;
  const stepX = (endX - startX) / (cols - 1);
  const stepY = (endY - startY) / (rows - 1);

  let idx = 1;
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (idx > totalUsers) break;
      const uid = `U-10${String(idx).padStart(3, '0')}`;
      // subtle organic jitter
      const jitterX = (Math.sin(idx * 7.1) * 8);
      const jitterY = (Math.cos(idx * 5.3) * 8);
      const node = {
        id: uid,
        label: uid,
        index: idx,
        x: startX + c * stepX + jitterX,
        y: startY + r * stepY + jitterY,
        radius: 5.5,
        status: 'IDLE',
        sendTimer: 0,
      };
      uiState.nodes.push(node);
      uiState.nodeMap.set(uid, node);
      idx++;
    }
  }

  uiState.initializedCanvas = true;
}

// Draw Canvas Web Network
function drawNetwork() {
  if (!uiState.ctx || !uiState.canvas) return;
  const ctx = uiState.ctx;
  const rect = uiState.canvas.getBoundingClientRect();
  const w = rect.width;
  const h = rect.height;

  ctx.clearRect(0, 0, w, h);

  // Background subtle grid
  ctx.strokeStyle = '#eaeded';
  ctx.lineWidth = 1;
  const gridSize = 40;
  for (let x = 0; x < w; x += gridSize) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
  }
  for (let y = 0; y < h; y += gridSize) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  // Draw Origin Lines to Column 1 Users
  ctx.strokeStyle = 'rgba(29, 112, 184, 0.18)';
  ctx.lineWidth = 1.2;
  uiState.nodes.slice(0, 10).forEach(n => {
    ctx.beginPath();
    ctx.moveTo(uiState.originNode.x, uiState.originNode.y);
    ctx.lineTo(n.x, n.y);
    ctx.stroke();
  });

  // Draw Web Network Links between adjacent nodes
  ctx.strokeStyle = 'rgba(213, 219, 219, 0.7)';
  ctx.lineWidth = 0.9;
  for (let i = 0; i < uiState.nodes.length; i++) {
    const a = uiState.nodes[i];
    // Right neighbor
    if ((i + 1) % 10 !== 0 && i + 1 < uiState.nodes.length) {
      const b = uiState.nodes[i + 1];
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    // Down neighbor
    if (i + 10 < uiState.nodes.length) {
      const b = uiState.nodes[i + 10];
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
  }

  // Draw Lines to Data Center from Rightmost Column
  ctx.strokeStyle = 'rgba(30, 130, 76, 0.22)';
  ctx.lineWidth = 1.2;
  uiState.nodes.slice(-10).forEach(n => {
    ctx.beginPath();
    ctx.moveTo(n.x, n.y);
    ctx.lineTo(uiState.dcNode.x, uiState.dcNode.y);
    ctx.stroke();
  });

  // Animate Pulses travelling towards Data Center
  for (let i = uiState.pulses.length - 1; i >= 0; i--) {
    const p = uiState.pulses[i];
    p.progress += 0.035;
    if (p.progress >= 1.0) {
      uiState.pulses.splice(i, 1);
      continue;
    }
    const curX = p.startX + (p.targetX - p.startX) * p.progress;
    const curY = p.startY + (p.targetY - p.startY) * p.progress;
    ctx.beginPath();
    ctx.arc(curX, curY, 3.5, 0, Math.PI * 2);
    ctx.fillStyle = '#1d70b8';
    ctx.shadowColor = 'rgba(29, 112, 184, 0.5)';
    ctx.shadowBlur = 6;
    ctx.fill();
    ctx.shadowBlur = 0;
  }

  // Draw 100 User Nodes
  uiState.nodes.forEach(n => {
    const isSending = n.status === 'SENDING';
    const isSelected = uiState.selectedNode === n;

    // Node Body
    ctx.beginPath();
    ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
    ctx.fillStyle = isSending ? '#1d70b8' : isSelected ? '#2c3e50' : '#ffffff';
    ctx.strokeStyle = isSending ? '#155a96' : isSelected ? '#1d70b8' : '#85929e';
    ctx.lineWidth = isSending || isSelected ? 2.2 : 1.2;
    ctx.fill();
    ctx.stroke();

    // Node Center Dot
    ctx.beginPath();
    ctx.arc(n.x, n.y, 1.8, 0, Math.PI * 2);
    ctx.fillStyle = isSending ? '#ffffff' : '#2c3e50';
    ctx.fill();

    // Label: User ID on TOP of head only
    ctx.fillStyle = isSending ? '#1d70b8' : '#5d6d7e';
    ctx.font = isSending ? "700 8.5px 'DM Mono', monospace" : "500 7.5px 'DM Mono', monospace";
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(n.label, n.x, n.y - (n.radius + 3));
  });

  // Draw Origin Node
  const orig = uiState.originNode;
  ctx.beginPath();
  ctx.arc(orig.x, orig.y, orig.radius, 0, Math.PI * 2);
  ctx.fillStyle = '#1d70b8';
  ctx.strokeStyle = '#2c3e50';
  ctx.lineWidth = 2.5;
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#ffffff';
  ctx.font = "800 10px 'DM Mono', monospace";
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('U0', orig.x, orig.y);
  ctx.fillStyle = '#1d70b8';
  ctx.font = "700 9px 'DM Mono', monospace";
  ctx.fillText('U-ORIGIN', orig.x, orig.y - (orig.radius + 4));

  // Draw Data Center Node
  const dc = uiState.dcNode;
  ctx.beginPath();
  ctx.arc(dc.x, dc.y, dc.radius, 0, Math.PI * 2);
  ctx.fillStyle = '#1e824c';
  ctx.strokeStyle = '#2c3e50';
  ctx.lineWidth = 2.5;
  ctx.fill(); ctx.stroke();
  ctx.fillStyle = '#ffffff';
  ctx.font = "800 11px 'DM Mono', monospace";
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('DC', dc.x, dc.y);
  ctx.fillStyle = '#1e824c';
  ctx.font = "700 9px 'DM Mono', monospace";
  ctx.fillText('DATA CENTER', dc.x, dc.y - (dc.radius + 4));
}

// Trigger Request Pulse Animation across Web Graph
function triggerRequestPulse(senderId = null) {
  if (!uiState.nodes.length) return;
  const node = senderId ? (uiState.nodeMap.get(senderId) || uiState.nodes[Math.floor(Math.random() * uiState.nodes.length)]) : uiState.nodes[Math.floor(Math.random() * uiState.nodes.length)];
  node.status = 'SENDING';
  node.sendTimer = 1.0;

  uiState.pulses.push({
    startX: node.x,
    startY: node.y,
    targetX: uiState.dcNode.x,
    targetY: uiState.dcNode.y,
    progress: 0,
  });

  setTimeout(() => {
    node.status = 'IDLE';
  }, 900);
}

// --- 2. Render 2D Server Rack Cards (Server A, B, C) ---
function renderServerCards(servers) {
  return servers.map(server => {
    const meta = SERVER_NAMES[server.server_id] || { letter: server.server_id, title: server.model, model: '', color: '#1d70b8' };
    const util = Math.min(100, Math.max(0, server.utilization_pct || 0));
    const powerW = Number(server.current_power_w || 0);
    const activeStreams = Number(server.active_streams || 0);
    const maxStreams = Number(server.max_streams || 1);
    const queueDepth = Number(server.queue_depth || 0);
    const status = server.status || 'IDLE';

    return `
      <article class="server-chassis ${status}" id="rack-${escapeHtml(server.server_id)}">
        <div class="chassis-head">
          <div class="chassis-title">
            <span class="server-letter">${escapeHtml(meta.letter)}: ${escapeHtml(meta.title)}</span>
            <span class="server-hardware">${escapeHtml(server.model)}</span>
          </div>
          <span class="badge ${status}">${status}</span>
        </div>
        <div class="chassis-body">
          <div class="utilization-row">
            <div class="util-label-row">
              <span>Processor Utilization</span>
              <strong>${number(util, 1)}%</strong>
            </div>
            <div class="util-track">
              <div class="util-fill" style="width: ${util}%;"></div>
            </div>
          </div>
          <div class="telemetry-specs-grid">
            <div class="telemetry-cell">
              <span class="cell-lbl">Active Streams</span>
              <span class="cell-val">${activeStreams} / ${maxStreams}</span>
            </div>
            <div class="telemetry-cell">
              <span class="cell-lbl">Queue Depth</span>
              <span class="cell-val">${queueDepth} tasks</span>
            </div>
            <div class="telemetry-cell">
              <span class="cell-lbl">Power Draw</span>
              <span class="cell-val">${number(powerW, 1)} W</span>
            </div>
            <div class="telemetry-cell">
              <span class="cell-lbl">Capacity Limit</span>
              <span class="cell-val">${maxStreams} streams</span>
            </div>
          </div>
        </div>
      </article>
    `;
  }).join('');
}

// --- 3. Main Synchronized Render Function ---
function render(state) {
  uiState.lastSnapshot = state;
  const primary = state.primary;
  const metrics = primary.metrics;

  // Status strip updates
  $('#run-status').textContent = state.status.replace('_', ' ');
  $('#run-dot').className = `dot ${state.status === 'RUNNING' ? 'running' : ''}`;
  $('#clock').textContent = `${number(state.clock_seconds, 2)}s`;
  $('#seed').textContent = state.seed;
  $('#trace').textContent = `${state.trace_delivered} / ${state.trace_total}`;
  $('#scenario').value = state.scenario;
  $('#speed').value = String(state.speed);
  $('#assumptions').textContent = state.assumptions;

  // Top KPI Metrics
  $('#metrics').innerHTML = [
    metric('Workload Generated', number(metrics.generated), `${number(metrics.processing_current)} processing · ${number(metrics.queued_current)} queued`),
    metric('Completed Inferences', number(metrics.completed), `${number(metrics.throughput_rps, 2)} req/s throughput`),
    metric('p95 Turnaround', `${number(metrics.p95_turnaround_ms)} ms`, `avg ${number(metrics.avg_turnaround_ms)} ms`),
    metric('SLA Compliance', `${number(100 - metrics.deadline_miss_rate_pct, 1)}%`, `${number(metrics.deadline_miss_rate_pct, 1)}% miss rate`),
    metric('Total Energy (Estimated)', `${number(metrics.estimated_total_energy_j)} J`, `${number(metrics.estimated_energy_per_ontime_j || metrics.estimated_energy_per_completed_j)} J / on-time req`),
    metric('Routing Dispatches', number(metrics.decision_counts.dispatch), `${metrics.decision_counts.defer} deferred · ${metrics.decision_counts.reject} rejected`),
  ].join('');

  // Render 2D Server Rack cards in both Overview and Server Tab
  const serverRackHtml = renderServerCards(primary.servers);
  if ($('#servers-overview-grid')) $('#servers-overview-grid').innerHTML = serverRackHtml;
  if ($('#servers-main-grid')) $('#servers-main-grid').innerHTML = serverRackHtml;

  // Render Decision Lists (Overview & System Tab)
  const decisionsHtml = primary.recent_decisions.length ? primary.recent_decisions.map(decision => {
    const srvMeta = SERVER_NAMES[decision.selected_server_id] || { letter: decision.selected_server_id || 'DEFER' };
    const alternatives = (decision.rejected_alternatives || []).map(item => {
      const altMeta = SERVER_NAMES[item.server_id] || { letter: item.server_id || '' };
      return `${altMeta.letter || item.server_id}: ${item.reason}`;
    }).join(' &bull; ');

    return `
      <div class="decision">
        <span class="decision-id">${escapeHtml(decision.request_id.slice(0, 8))}</span>
        <div class="decision-main">
          <div class="decision-target">${escapeHtml(srvMeta.letter)} &bull; ${escapeHtml(decision.selected_server_id || 'Hold in Buffer')}</div>
          <div class="decision-sub">
            predicted ${number(decision.predicted_total_turnaround_ms)} ms &bull; ${number(decision.predicted_energy_joules, 2)} J delta &bull; ${escapeHtml(decision.solver_provenance)}
          </div>
          ${alternatives ? `<div class="alternatives-text">Pruned Alternatives: ${alternatives}</div>` : ''}
        </div>
        <span class="action ${decision.action === 'REJECT' ? 'REJECT' : decision.action === 'DEFER' ? 'DEFER' : ''}">${escapeHtml(decision.action)}</span>
      </div>
    `;
  }).join('') : '<div style="padding: 20px; color: var(--muted); text-align: center;">Decisions with exact rationales and pruned alternatives will display here as requests arrive.</div>';

  if ($('#decisions-overview')) $('#decisions-overview').innerHTML = decisionsHtml;
  if ($('#decisions-main')) $('#decisions-main').innerHTML = decisionsHtml;

  // Render Matched Experiment Comparison (QuantaSHI vs Round-Robin Baseline)
  const base = state.baseline.metrics;
  const delta = state.comparison.energy_delta_j;
  const deltaClass = delta >= 0 ? 'positive' : 'negative';
  const comparisonHtml = `
    <div class="comparison-row"><span>Trace & Seed</span><b>${state.comparison.same_trace_requests} requests · Seed ${state.comparison.same_seed}</b></div>
    <div class="comparison-row"><span>Estimated Energy</span><b>QuantaSHI ${number(metrics.estimated_total_energy_j)} J &bull; Round Robin ${number(base.estimated_total_energy_j)} J</b></div>
    <div class="comparison-row"><span>Energy Savings (RR &minus; Q)</span><b class="${deltaClass}">${delta >= 0 ? '+' : ''}${number(delta)} J (${number(state.comparison.energy_delta_pct, 1)}%)</b></div>
    <div class="comparison-row"><span>p95 Turnaround Latency</span><b>Q ${number(metrics.p95_turnaround_ms)} ms &bull; RR ${number(base.p95_turnaround_ms)} ms</b></div>
    <div class="comparison-row"><span>SLA Deadline Misses</span><b>Q ${number(metrics.deadline_miss_rate_pct, 1)}% &bull; RR ${number(base.deadline_miss_rate_pct, 1)}%</b></div>
    <p class="footer-note" style="margin-top: 10px;">${escapeHtml(state.comparison.note)}</p>
  `;
  if ($('#comparison')) $('#comparison').innerHTML = comparisonHtml;
  if ($('#comparison-sys')) $('#comparison-sys').innerHTML = comparisonHtml;

  // Render Events Timeline
  $('#events').innerHTML = primary.recent_events.length ? primary.recent_events.map(event => `
    <div class="event">
      <span class="event-time">${number(event.timestamp, 2)}s</span>
      <span class="event-kind">${escapeHtml(event.kind)}</span>
      <span class="event-message">${escapeHtml(event.message)}</span>
    </div>
  `).join('') : '<div style="padding: 20px; color: var(--muted); text-align: center;">Start simulation loop to stream live discrete-event execution telemetry.</div>';

  // Render Recent Requests Log
  $('#requests').innerHTML = primary.recent_requests.length ? primary.recent_requests.map(request => `
    <div class="request-row">
      <div>
        <div class="request-id">${escapeHtml(request.request_id.slice(0, 8))} &bull; ${escapeHtml(request.workload_type)}</div>
        <div class="request-sub">${escapeHtml(request.user_id)} &bull; ${number(request.context_tokens)} in / ${number(request.max_output_tokens)} out &bull; ${escapeHtml(request.selected_server_id || 'unassigned')}</div>
      </div>
      <span class="request-status ${request.status}">${escapeHtml(request.status)}</span>
    </div>
  `).join('') : '<div style="padding: 20px; color: var(--muted); text-align: center;">No requests have entered the shared ingress queue yet.</div>';

  // Update User View Ingress List & Pulse Animation
  const userState = state.synthetic_users;
  $('#ingress-counter').textContent = `${userState.active_requests} in queue`;
  $('#user-population-meta').textContent = `${userState.active_users} active / 100 population`;

  if ($('#user-ingress-list')) {
    $('#user-ingress-list').innerHTML = primary.recent_requests.slice(0, 15).map(req => `
      <div class="ingress-item">
        <div class="ingress-meta">
          <strong>${escapeHtml(req.user_id)} &bull; ${escapeHtml(req.workload_type)}</strong>
          <span>${number(req.arrival_timestamp, 2)}s</span>
        </div>
        <div class="ingress-prompt">"${escapeHtml(req.prompt_preview || 'Generating real-world LLM inference payload...')}"</div>
        <div style="font-size: 10px; color: var(--muted);">Context: ${req.context_tokens} tok &bull; Output: ${req.max_output_tokens} tok &bull; SLA: ${number(req.deadline_slo_ms)} ms</div>
      </div>
    `).join('') || '<div style="padding: 20px; color: var(--muted); text-align: center;">Workload ingress will populate as synthetic users send requests.</div>';
  }

  // Trigger Network Pulses for Active Senders
  if (state.status === 'RUNNING' && primary.recent_requests.length > 0) {
    const latest = primary.recent_requests[0];
    triggerRequestPulse(latest.user_id);
  }
}

// --- 4. Event-Driven Loop Setup (SSE with Polling Fallback) ---
function startEventSourceLoop() {
  try {
    const sse = new EventSource('/api/simulation/events');
    sse.onmessage = (event) => {
      try {
        const state = JSON.parse(event.data);
        render(state);
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    };
    sse.onerror = () => {
      // fallback to regular polling if SSE connection drops
      console.warn('SSE disconnected, falling back to polling.');
      sse.close();
      setInterval(pollState, 350);
    };
  } catch (e) {
    setInterval(pollState, 350);
  }
}

async function pollState() {
  try {
    const res = await fetch('/api/simulation/state', { cache: 'no-store' });
    if (res.ok) render(await res.json());
  } catch (err) {
    $('#run-status').textContent = 'Simulation offline';
  }
}

// --- 5. User Controls & View Tabs ---
function selectView(view) {
  document.querySelectorAll('[data-view-section]').forEach(sec => {
    sec.hidden = sec.dataset.viewSection !== view;
  });
  document.querySelectorAll('.view-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.view === view);
  });
  if (view === 'users-view' && !uiState.initializedCanvas) {
    initNetworkNodes();
  }
}

document.querySelectorAll('.view-tab').forEach(tab => {
  tab.addEventListener('click', () => selectView(tab.dataset.view));
});

$('#start').addEventListener('click', () => control('START').catch(pollState));
$('#pause').addEventListener('click', () => control('PAUSE').catch(pollState));
$('#reset').addEventListener('click', () => control('RESET', {
  scenario: $('#scenario').value,
  speed: Number($('#speed').value)
}).catch(pollState));
$('#speed').addEventListener('change', () => control('SPEED', { speed: Number($('#speed').value) }).catch(pollState));

if ($('#btn-fire-user-workload')) {
  $('#btn-fire-user-workload').addEventListener('click', () => {
    triggerRequestPulse();
    control('START').catch(pollState);
  });
}

// --- 6. AI Agents Handlers ---
const btnUserAgent = $('#btn-dash-user-agent');
const outUserAgent = $('#dash-user-agent-output');
if (btnUserAgent) {
  btnUserAgent.addEventListener('click', async () => {
    btnUserAgent.disabled = true;
    btnUserAgent.textContent = '⏳ Synthesizing Workload...';
    try {
      const res = await fetch('/api/agent/user', { method: 'POST' });
      const data = await res.json();
      if (data.success && data.request) {
        const req = data.request;
        const hist = (data.history && data.history[0]) || {};
        outUserAgent.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <strong style="color:var(--blue);">${escapeHtml(req.workload_type)}</strong>
            <span style="font-family:'DM Mono',monospace; color:var(--muted); font-size:10px;">${escapeHtml(req.user_id)} &bull; ${escapeHtml(req.request_id)}</span>
          </div>
          ${hist.persona ? `<div style="color:var(--amber); font-weight:700; font-size:10.5px; margin-bottom:6px;">Persona: ${escapeHtml(hist.persona)}</div>` : ''}
          <div style="background:#ffffff; border:1px solid var(--line); border-radius:6px; padding:10px; color:var(--text); font-style:italic; margin-bottom:10px;">
            "${escapeHtml(req.prompt_preview)}"
          </div>
          <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-family:'DM Mono',monospace; font-size:10px;">
            <div style="background:var(--surface2); padding:6px; border-radius:4px; border:1px solid var(--line);">In: <b style="color:var(--blue);">${number(req.context_tokens)} tok</b></div>
            <div style="background:var(--surface2); padding:6px; border-radius:4px; border:1px solid var(--line);">Out: <b style="color:var(--blue);">${number(req.max_output_tokens)} tok</b></div>
            <div style="background:var(--surface2); padding:6px; border-radius:4px; border:1px solid var(--line);">SLO: <b style="color:var(--green);">${number(req.deadline_slo_ms)} ms</b></div>
            <div style="background:var(--surface2); padding:6px; border-radius:4px; border:1px solid var(--line);">Priority: <b style="color:var(--amber);">Tier ${escapeHtml(req.priority_level)}</b></div>
          </div>
        `;
        triggerRequestPulse();
      }
    } catch (e) {
      outUserAgent.innerHTML = `<div style="color:var(--red); padding:10px;">Synthesis error: ${escapeHtml(e.message)}</div>`;
    } finally {
      btnUserAgent.disabled = false;
      btnUserAgent.textContent = '✨ Synthesize AI Workload Query';
    }
  });
}

const btnServerAgent = $('#btn-dash-server-agent');
const outServerAgent = $('#dash-server-agent-output');
if (btnServerAgent) {
  btnServerAgent.addEventListener('click', async () => {
    btnServerAgent.disabled = true;
    btnServerAgent.textContent = '⏳ Diagnosing Cluster SRE...';
    try {
      const res = await fetch('/api/agent/server', { method: 'POST' });
      const data = await res.json();
      if (data.success && data.diagnosis) {
        const diag = data.diagnosis;
        const healthColor = diag.cluster_health_score >= 80 ? 'var(--green)' : diag.cluster_health_score >= 50 ? 'var(--amber)' : 'var(--red)';
        outServerAgent.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <strong style="color:var(--green);">Cluster Health</strong>
            <span style="border:1px solid ${healthColor}; color:${healthColor}; padding:2px 8px; border-radius:12px; font-weight:700; font-family:'DM Mono',monospace; font-size:10px;">${number(diag.cluster_health_score)} / 100</span>
          </div>
          <div style="background:#ffffff; border:1px solid var(--line); border-radius:6px; padding:10px; margin-bottom:8px; line-height:1.4;">
            ${escapeHtml(diag.executive_summary)}
          </div>
          <div style="font-size:10.5px; margin-bottom:8px; font-family:'DM Mono',monospace;">
            <span style="color:var(--muted);">Bottleneck: </span><b style="color:var(--text);">${escapeHtml(diag.primary_bottleneck)}</b>
          </div>
          <div style="font-size:10px; color:var(--muted); margin-bottom:4px; font-weight:700;">Recommended Directives:</div>
          <ul style="margin:0; padding-left:16px; font-size:10.5px; color:var(--blue); line-height:1.4;">
            ${(diag.recommended_actions || []).map(act => `<li>${escapeHtml(act)}</li>`).join('')}
          </ul>
        `;
      }
    } catch (e) {
      outServerAgent.innerHTML = `<div style="color:var(--red); padding:10px;">Diagnostic error: ${escapeHtml(e.message)}</div>`;
    } finally {
      btnServerAgent.disabled = false;
      btnServerAgent.textContent = '🩺 Run Cluster Diagnostic';
    }
  });
}

const btnSystemAgent = $('#btn-dash-system-agent');
const outSystemAgent = $('#dash-system-agent-output');
if (btnSystemAgent) {
  btnSystemAgent.addEventListener('click', async () => {
    btnSystemAgent.disabled = true;
    btnSystemAgent.textContent = '⏳ Explaining Decision...';
    try {
      const res = await fetch('/api/agent/system', { method: 'POST' });
      const data = await res.json();
      if (data.success && data.explanation) {
        const exp = data.explanation;
        const dec = data.decision || {};
        const confColor = exp.sla_confidence === 'HIGH' ? 'var(--green)' : exp.sla_confidence === 'MODERATE' ? 'var(--amber)' : 'var(--red)';
        outSystemAgent.innerHTML = `
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <strong style="color:var(--amber);">Decision Attribution</strong>
            <span style="border:1px solid ${confColor}; color:${confColor}; padding:2px 8px; border-radius:12px; font-weight:700; font-family:'DM Mono',monospace; font-size:10px;">SLA: ${escapeHtml(exp.sla_confidence)}</span>
          </div>
          <div style="background:#ffffff; border:1px solid var(--line); border-radius:6px; padding:10px; margin-bottom:8px; line-height:1.4; font-style:italic;">
            "${escapeHtml(exp.rationale)}"
          </div>
          <div style="font-size:10.5px; margin-bottom:6px; line-height:1.4;">
            <span style="color:var(--muted);">Energy Trade-off: </span><span style="color:var(--green); font-weight:600;">${escapeHtml(exp.energy_tradeoff)}</span>
          </div>
          <div style="font-size:10.5px; margin-bottom:8px; line-height:1.4;">
            <span style="color:var(--muted);">Solver Audit: </span><span style="color:var(--blue); font-weight:600;">${escapeHtml(exp.solver_audit)}</span>
          </div>
          <div style="background:var(--surface2); border:1px solid var(--line); padding:6px 8px; border-radius:4px; font-size:10px; font-family:'DM Mono',monospace; display:flex; justify-content:space-between;">
            <span>Target: <b style="color:var(--blue);">${escapeHtml(dec.selected_server_id || 'DEFER')}</b></span>
            <span>Policy: <b style="color:var(--amber);">${escapeHtml(dec.policy || 'BALANCED_PARETO')}</b></span>
          </div>
        `;
      }
    } catch (e) {
      outSystemAgent.innerHTML = `<div style="color:var(--red); padding:10px;">Attribution error: ${escapeHtml(e.message)}</div>`;
    } finally {
      btnSystemAgent.disabled = false;
      btnSystemAgent.textContent = '🧠 Explain Latest Decision';
    }
  });
}

// --- 7. Animation Loop for Canvas Network ---
function canvasAnimationLoop() {
  drawNetwork();
  requestAnimationFrame(canvasAnimationLoop);
}

// Initialize on page load
window.addEventListener('DOMContentLoaded', () => {
  initNetworkNodes();
  canvasAnimationLoop();
  startEventSourceLoop();
  selectView('overview');
});
