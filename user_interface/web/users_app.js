/**
 * Low-Code Client Workload Generator & 2D Web Network Simulator
 * Part 1: Users Interface Component
 */

(function () {
  'use strict';

  // --- Real-world Client Profiles & Payload Templates ---
  const DEVICES = [
    { type: 'MacBook Pro M3 Max', app: 'VS Code Copilot (macOS)', ip: '192.168.1.104' },
    { type: 'iPhone 15 Pro', app: 'Claude iOS App', ip: '10.0.4.52' },
    { type: 'Ubuntu 24.04 Workstation', app: 'PyTorch / LangChain Agent', ip: '172.16.2.18' },
    { type: 'ThinkPad X1 Carbon', app: 'Chrome 124 / ChatGPT Web', ip: '192.168.1.189' },
    { type: 'Google Pixel 8 Pro', app: 'Perplexity Mobile App', ip: '10.0.8.210' },
    { type: 'Enterprise Server Node', app: 'FastAPI / vLLM Gateway', ip: '10.240.0.12' },
  ];

  const PROMPTS = [
    "Write an async Python queue worker with exponential backoff and Kafka dead-letter support.",
    "Can you review this SQL migration plan and check for table locking on high write volume?",
    "Explain the architectural difference between FlashAttention-2 and standard attention on H100s.",
    "Draft a summary of the quarterly cloud infrastructure report focusing on GPU capex depreciation.",
    "How do we configure Kubernetes KEDA to scale inference pods based on Prometheus queue latency?",
    "Translate this C++ CUDA kernel hook for fused Rotary Position Embeddings (RoPE) into Triton.",
    "Analyze the attached contract for SLA penalty terms when system uptime drops below 99.95%.",
  ];

  // --- State ---
  const state = {
    nodes: [],
    links: [],
    nodeMap: new Map(),
    isRunning: false,
    isBlasted: false,
    selectedId: 'usr_01',
    hoveredId: null,
    totalEmitted: 0,
    recentRequests: [],
    pulses: [],
    shockwaves: [],
    lastFrame: performance.now(),
    pan: { x: 0, y: 0 },
    zoom: 1.0,
    isPanning: false,
    panStart: { x: 0, y: 0 },
  };

  // --- DOM Elements ---
  const $ = (id) => document.getElementById(id);
  const dom = {
    canvas: $('network-canvas'),
    container: $('canvas-container'),
    btnToggle: $('btn-toggle'),
    btnReset: $('btn-reset'),
    userSearch: $('user-search'),
    btnClearSearch: $('btn-clear-search'),
    btnZoomIn: $('btn-zoom-in'),
    btnZoomOut: $('btn-zoom-out'),
    btnZoomReset: $('btn-zoom-reset'),
    statRate: $('stat-rate'),
    statActive: $('stat-active'),
    statTotal: $('stat-total'),
    tabInspector: $('tab-inspector'),
    tabStream: $('tab-stream'),
    tabAgent: $('tab-agent'),
    viewInspector: $('view-inspector'),
    viewStream: $('view-stream'),
    viewAgent: $('view-agent'),
    btnTriggerAgent: $('btn-trigger-ai-agent'),
    agentOutput: $('ai-agent-output'),
    queueCount: $('queue-count'),
    streamContainer: $('ingress-stream-container'),
    insUserId: $('ins-user-id'),
    insDeviceType: $('ins-device-type'),
    insStatusPill: $('ins-status-pill'),
    insClientApp: $('ins-client-app'),
    insServerDest: $('ins-server-dest'),
    insPayloadCode: $('ins-payload-code'),
    insCtxTokens: $('ins-ctx-tokens'),
    insOutTokens: $('ins-out-tokens'),
    insSla: $('ins-sla'),
    insTotalReqs: $('ins-total-reqs'),
    btnFireSingle: $('btn-fire-single'),
  };
  const ctx = dom.canvas.getContext('2d');

  // --- 1. Low-Code 2D Web Network Generator ---
  function buildNetwork(numUsers) {
    state.nodes = [];
    state.links = [];
    state.nodeMap.clear();

    const w = dom.container.clientWidth || 950;
    const h = dom.container.clientHeight || 650;
    const cx = w / 2, cy = h / 2;

    // 7 regional hubs spanning the 2D plane
    const hubs = [
      { x: cx, y: cy, count: 18 },
      { x: cx - w * 0.28, y: cy - h * 0.22, count: 14 },
      { x: cx + w * 0.28, y: cy - h * 0.22, count: 14 },
      { x: cx - w * 0.26, y: cy + h * 0.24, count: 14 },
      { x: cx + w * 0.26, y: cy + h * 0.24, count: 14 },
      { x: cx, y: cy - h * 0.33, count: 13 },
      { x: cx, y: cy + h * 0.33, count: 13 },
    ];

    let userIdx = 1;
    hubs.forEach(hub => {
      for (let k = 0; k < hub.count && userIdx <= numUsers; k++, userIdx++) {
        const uid = `U-10${String(userIdx).padStart(3, '0')}`;
        const dev = DEVICES[(userIdx - 1) % DEVICES.length];
        const angle = Math.random() * Math.PI * 2;
        const dist = (k === 0) ? 0 : 25 + Math.random() * 105;

        state.nodes.push({
          id: uid,
          device: dev,
          isHub: (k === 0),
          radius: (k === 0) ? 10 : 7,
          x: cx, y: cy, vx: 0, vy: 0, // Starts at center for blast mode
          targetX: hub.x + Math.cos(angle) * dist,
          targetY: hub.y + Math.sin(angle) * (dist * 0.85),
          status: 'IDLE',
          timer: 0,
          requestsSent: 0,
          lastPayload: null,
          thinkTime: 1.0 + Math.random() * 4.0,
        });
      }
    });

    // Relaxation: prevent any label/node overlap (min 46px separation)
    for (let it = 0; it < 60; it++) {
      for (let i = 0; i < state.nodes.length; i++) {
        for (let j = i + 1; j < state.nodes.length; j++) {
          const a = state.nodes[i], b = state.nodes[j];
          const dx = b.targetX - a.targetX, dy = b.targetY - a.targetY;
          const d = Math.hypot(dx, dy) || 1;
          if (d < 46) {
            const shift = (46 - d) * 0.5;
            a.targetX -= (dx / d) * shift; a.targetY -= (dy / d) * shift;
            b.targetX += (dx / d) * shift; b.targetY += (dy / d) * shift;
          }
        }
      }
    }

    // Keep within canvas padding
    state.nodes.forEach(n => {
      n.targetX = Math.max(50, Math.min(w - 50, n.targetX));
      n.targetY = Math.max(55, Math.min(h - 55, n.targetY));
      state.nodeMap.set(n.id, n);
    });

    // Connect nodes to 3-4 nearest neighbors to form rich web mesh
    state.nodes.forEach(n => {
      const peers = [...state.nodes].filter(o => o.id !== n.id)
        .sort((a, b) => Math.hypot(a.targetX - n.targetX, a.targetY - n.targetY) - Math.hypot(b.targetX - n.targetX, b.targetY - n.targetY));

      const count = n.isHub ? 5 : 3;
      for (let k = 0; k < count; k++) {
        const target = peers[k];
        if (target && Math.hypot(target.targetX - n.targetX, target.targetY - n.targetY) < 220) {
          if (!state.links.some(l => (l.source === n && l.target === target) || (l.source === target && l.target === n))) {
            state.links.push({ source: n, target: target, isTrunk: n.isHub && target.isHub });
          }
        }
      }
    });
  }

  // --- 2. Blast Mode: Explosive Expansion Into Network ---
  function triggerBlast() {
    state.isBlasted = true;
    const w = dom.container.clientWidth || 950;
    const h = dom.container.clientHeight || 650;
    const cx = w / 2, cy = h / 2;

    state.nodes.forEach(n => {
      n.x = cx; n.y = cy;
      const dx = n.targetX - cx, dy = n.targetY - cy;
      const dist = Math.hypot(dx, dy) || 1;
      const speed = 18 + Math.random() * 10;
      n.vx = (dx / dist) * speed;
      n.vy = (dy / dist) * speed;
    });

    state.shockwaves.push({ x: cx, y: cy, radius: 5, max: Math.min(w, h) * 0.65, alpha: 1.0 });
  }

  // --- 3. Request Dispatcher (Real-World HTTP JSON Payload) ---
  function sendRequest(node) {
    node.status = 'SENDING';
    node.timer = 0.85;
    node.requestsSent++;
    state.totalEmitted++;
    state.recentRequests.push(performance.now());

    const promptText = PROMPTS[Math.floor(Math.random() * PROMPTS.length)];
    const ctxTokens = Math.floor(64 + Math.random() * 1200);
    const outTokens = Math.floor(32 + Math.random() * 384);
    const slaMs = Math.round(250 + ctxTokens * 0.03 + outTokens * 22);

    const payload = {
      model: "meta-llama/Llama-3-70B-Instruct",
      messages: [{ role: "user", content: promptText }],
      stream: true,
      max_tokens: outTokens,
      temperature: 0.7
    };

    node.lastPayload = {
      json: JSON.stringify(payload, null, 2),
      ctxTokens, outTokens, slaMs, promptText,
    };

    // Rhythmic edge packet pulse
    const connected = state.links.filter(l => l.source === node || l.target === node);
    if (connected.length > 0) {
      const l = connected[Math.floor(Math.random() * connected.length)];
      const target = (l.source === node) ? l.target : l.source;
      state.pulses.push({ x1: node.x, y1: node.y, x2: target.x, y2: target.y, prog: 0, speed: 2.5 });
    }

    // Stream item
    if (dom.streamContainer) {
      const item = document.createElement('div');
      item.className = 'stream-item';
      item.innerHTML = `<div class="stream-top"><span class="stream-user">${node.id}</span><span class="stream-time">${new Date().toLocaleTimeString()}</span></div><div class="stream-text">"${promptText}"</div>`;
      item.onclick = () => selectUser(node.id);
      dom.streamContainer.insertBefore(item, dom.streamContainer.firstChild);
      if (dom.streamContainer.children.length > 50) dom.streamContainer.removeChild(dom.streamContainer.lastChild);
    }
    if (dom.queueCount) dom.queueCount.textContent = state.totalEmitted;

    if (state.selectedId === node.id) updateInspector(node);
  }

  // --- 4. Main Animation & Physics Loop ---
  function renderLoop(time) {
    const dt = Math.min((time - state.lastFrame) / 1000, 0.1);
    state.lastFrame = time;
    if (!dom.container) return;
    const w = dom.container.clientWidth, h = dom.container.clientHeight;

    if (state.isBlasted) {
      state.nodes.forEach(n => {
        n.vx += (n.targetX - n.x) * 0.08; n.vy += (n.targetY - n.y) * 0.08;
        n.vx *= 0.86; n.vy *= 0.86;
        n.x += n.vx; n.y += n.vy;

        if (n.timer > 0) {
          n.timer -= dt;
          if (n.timer <= 0) { n.status = 'IDLE'; if (state.selectedId === n.id) updateInspector(n); }
        }

        if (state.isRunning) {
          n.thinkTime -= dt;
          if (n.thinkTime <= 0) {
            sendRequest(n);
            n.thinkTime = 2.0 + Math.random() * 5.0;
          }
        }
      });
    }

    for (let i = state.pulses.length - 1; i >= 0; i--) {
      state.pulses[i].prog += dt * state.pulses[i].speed;
      if (state.pulses[i].prog >= 1.0) state.pulses.splice(i, 1);
    }

    for (let i = state.shockwaves.length - 1; i >= 0; i--) {
      const s = state.shockwaves[i];
      s.radius += dt * 420;
      s.alpha = Math.max(0, 1 - (s.radius / s.max));
      if (s.alpha <= 0) state.shockwaves.splice(i, 1);
    }

    const now = performance.now();
    state.recentRequests = state.recentRequests.filter(t => now - t < 1000);
    if (dom.statRate) dom.statRate.textContent = state.recentRequests.length.toFixed(1);
    if (dom.statTotal) dom.statTotal.textContent = state.totalEmitted.toLocaleString();
    if (dom.statActive) dom.statActive.textContent = state.nodes.filter(n => n.status === 'SENDING').length;

    drawCanvas(w, h);
    requestAnimationFrame(renderLoop);
  }

  // --- 5. Clean Canvas Rendering ---
  function drawCanvas(w, h) {
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    ctx.save();
    ctx.translate(state.pan.x, state.pan.y);
    ctx.scale(state.zoom, state.zoom);

    const cx = w / 2, cy = h / 2;

    if (!state.isBlasted) {
      ctx.beginPath();
      ctx.arc(cx, cy, 15, 0, Math.PI * 2);
      ctx.fillStyle = '#1e293b'; ctx.strokeStyle = '#38bdf8'; ctx.lineWidth = 2.5;
      ctx.fill(); ctx.stroke();

      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.fillStyle = '#ffffff'; ctx.fill();

      ctx.fillStyle = '#f1f5f9';
      ctx.font = "600 12px 'JetBrains Mono', monospace";
      ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      ctx.fillText('usr_01 (Ready — Press Start Generator)', cx, cy - 20);
      ctx.restore();
      return;
    }

    state.shockwaves.forEach(s => {
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(56, 189, 248, ${s.alpha * 0.75})`;
      ctx.lineWidth = 2; ctx.stroke();
    });

    state.links.forEach(l => {
      const isSending = (l.source.status === 'SENDING' || l.target.status === 'SENDING');
      const isSelected = (l.source.id === state.selectedId || l.target.id === state.selectedId);

      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);

      if (isSending) {
        ctx.strokeStyle = '#1d70b8'; ctx.lineWidth = 2.0;
      } else if (isSelected) {
        ctx.strokeStyle = 'rgba(29, 112, 184, 0.75)'; ctx.lineWidth = 1.6;
      } else if (l.isTrunk) {
        ctx.strokeStyle = 'rgba(93, 109, 126, 0.45)'; ctx.lineWidth = 1.4;
      } else {
        ctx.strokeStyle = 'rgba(213, 219, 219, 0.75)'; ctx.lineWidth = 1.1;
      }
      ctx.stroke();
    });

    state.pulses.forEach(p => {
      const px = p.x1 + (p.x2 - p.x1) * p.prog, py = p.y1 + (p.y2 - p.y1) * p.prog;
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fillStyle = '#1d70b8'; ctx.shadowColor = 'rgba(29, 112, 184, 0.5)'; ctx.shadowBlur = 6;
      ctx.fill(); ctx.shadowBlur = 0;
    });

    state.nodes.forEach(n => {
      const isSelected = (n.id === state.selectedId);
      const isSending = (n.status === 'SENDING');
      const r = n.radius;

      if (isSelected) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = '#1d70b8'; ctx.lineWidth = 2.2;
        ctx.stroke();
      }

      if (n.isHub) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, r + 3, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(44, 62, 80, 0.3)'; ctx.lineWidth = 1.2;
        ctx.stroke();
      }

      ctx.beginPath();
      ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
      ctx.fillStyle = isSending ? '#1d70b8' : n.isHub ? '#2c3e50' : '#ffffff';
      ctx.strokeStyle = isSending ? '#155a96' : isSelected ? '#1d70b8' : n.isHub ? '#2c3e50' : '#85929e';
      ctx.lineWidth = isSending ? 2.2 : 1.5;
      ctx.fill(); ctx.stroke();

      ctx.beginPath();
      ctx.arc(n.x, n.y, n.isHub ? 3.5 : 2.5, 0, Math.PI * 2);
      ctx.fillStyle = isSending ? '#ffffff' : '#2c3e50';
      ctx.fill();

      // Label on top of head only
      ctx.fillStyle = isSelected ? '#1d70b8' : isSending ? '#1d70b8' : '#5d6d7e';
      ctx.font = isSelected ? "700 9px 'DM Mono', monospace" : "500 8px 'DM Mono', monospace";
      ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      ctx.fillText(n.id, n.x, n.y - (r + 4));
    });

    ctx.restore();
  }

  // --- 6. Inspector Logic ---
  function selectUser(userId) {
    state.selectedId = userId;
    const node = state.nodeMap.get(userId);
    if (node) { updateInspector(node); switchTab('inspector'); }
  }

  function updateInspector(node) {
    if (!node || !dom.insUserId) return;
    dom.insUserId.textContent = node.id;
    dom.insDeviceType.textContent = node.device.type;
    dom.insClientApp.textContent = node.device.app;
    dom.insServerDest.textContent = `gateway-01.datacenter.internal:443 (Client IP: ${node.device.ip})`;
    dom.insStatusPill.textContent = (node.status === 'SENDING') ? 'SENDING' : 'IDLE';
    dom.insStatusPill.className = (node.status === 'SENDING') ? 'status-pill sending' : 'status-pill';
    dom.insTotalReqs.textContent = node.requestsSent;

    if (node.lastPayload) {
      dom.insPayloadCode.textContent = node.lastPayload.json;
      dom.insCtxTokens.textContent = node.lastPayload.ctxTokens.toLocaleString();
      dom.insOutTokens.textContent = node.lastPayload.outTokens.toLocaleString();
      dom.insSla.textContent = `${node.lastPayload.slaMs} ms`;
    } else {
      const sample = {
        model: "meta-llama/Llama-3-70B-Instruct",
        messages: [{ role: "user", content: PROMPTS[parseInt(node.id.replace('usr_', ''), 10) % PROMPTS.length] }],
        stream: true, max_tokens: 256, temperature: 0.7
      };
      dom.insPayloadCode.textContent = JSON.stringify(sample, null, 2);
      dom.insCtxTokens.textContent = '380';
      dom.insOutTokens.textContent = '256';
      dom.insSla.textContent = '1,150 ms';
    }
  }

  function switchTab(name) {
    if (dom.tabInspector) dom.tabInspector.classList.toggle('active', name === 'inspector');
    if (dom.tabStream) dom.tabStream.classList.toggle('active', name === 'stream');
    if (dom.tabAgent) dom.tabAgent.classList.toggle('active', name === 'agent');
    if (dom.viewInspector) dom.viewInspector.classList.toggle('hidden', name !== 'inspector');
    if (dom.viewStream) dom.viewStream.classList.toggle('hidden', name !== 'stream');
    if (dom.viewAgent) dom.viewAgent.classList.toggle('hidden', name !== 'agent');
  }

  // --- 7. Event Listeners ---
  function setupEvents() {
    if (dom.btnToggle) {
      dom.btnToggle.addEventListener('click', () => {
        if (!state.isBlasted) triggerBlast();
        state.isRunning = !state.isRunning;
        dom.btnToggle.textContent = state.isRunning ? '❚❚ Stop Generator' : '▶ Start Generator';
        dom.btnToggle.classList.toggle('running', state.isRunning);
        fetch('/api/simulation/control', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: state.isRunning ? 'START' : 'PAUSE' })
        }).catch(() => {});
      });
    }

    function resetSimulation() {
      state.isRunning = false;
      state.isBlasted = false;
      state.totalEmitted = 0;
      state.recentRequests = [];
      state.pulses = [];
      state.shockwaves = [];
      state.selectedId = 'U-10001';
      fetch('/api/simulation/control', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'RESET' })
      }).catch(() => {});
      state.pan = { x: 0, y: 0 };
      state.zoom = 1.0;

      if (dom.btnToggle) {
        dom.btnToggle.textContent = '▶ Start Generator';
        dom.btnToggle.classList.remove('running');
      }

      if (dom.statRate) dom.statRate.textContent = '0.0';
      if (dom.statActive) dom.statActive.textContent = '0';
      if (dom.statTotal) dom.statTotal.textContent = '0';
      if (dom.queueCount) dom.queueCount.textContent = '0';

      if (dom.streamContainer) {
        dom.streamContainer.innerHTML = '';
      }

      if (dom.userSearch) {
        dom.userSearch.value = '';
      }

      buildNetwork(100);
      updateInspector(state.nodeMap.get('U-10001'));
      switchTab('inspector');

      // Also reset server cluster if active
      if (window.QuantaSHI_Servers && typeof window.QuantaSHI_Servers.resetCluster === 'function') {
        window.QuantaSHI_Servers.resetCluster();
      }
    }

    if (dom.btnReset) {
      dom.btnReset.addEventListener('click', resetSimulation);
    }

    if (dom.btnFireSingle) {
      dom.btnFireSingle.addEventListener('click', () => {
        const n = state.nodeMap.get(state.selectedId);
        if (n) sendRequest(n);
      });
    }

    if (dom.tabInspector) dom.tabInspector.addEventListener('click', () => switchTab('inspector'));
    if (dom.tabStream) dom.tabStream.addEventListener('click', () => switchTab('stream'));
    if (dom.tabAgent) dom.tabAgent.addEventListener('click', () => switchTab('agent'));

    if (dom.btnTriggerAgent) {
      dom.btnTriggerAgent.addEventListener('click', async () => {
        dom.btnTriggerAgent.disabled = true;
        dom.btnTriggerAgent.textContent = '⏳ AI Agent Synthesizing...';
        try {
          const res = await fetch('/api/agent/user', { method: 'POST' });
          const data = await res.json();
          if (data.success && data.request) {
            const req = data.request;
            dom.agentOutput.innerHTML = `
              <div style="margin-bottom: 8px;">
                <span style="color: #38bdf8; font-weight: 700;">➔ [${req.workload_type}] ${req.request_id}</span>
                <span style="color: #94a3b8; font-size: 0.7rem; float: right;">Sender: ${req.user_id}</span>
              </div>
              <div style="background: #162032; border: 1px solid #1e293b; border-radius: 6px; padding: 10px; color: #f8fafc; font-style: italic; margin-bottom: 10px;">
                "${req.prompt_preview}"
              </div>
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; font-size: 0.7rem;">
                <div style="background: #0b0f19; padding: 6px 8px; border-radius: 4px;">Context: <strong style="color: #38bdf8">${req.context_tokens} tok</strong></div>
                <div style="background: #0b0f19; padding: 6px 8px; border-radius: 4px;">Output: <strong style="color: #38bdf8">${req.max_output_tokens} tok</strong></div>
                <div style="background: #0b0f19; padding: 6px 8px; border-radius: 4px;">Deadline: <strong style="color: #10b981">${req.deadline_slo_ms} ms</strong></div>
                <div style="background: #0b0f19; padding: 6px 8px; border-radius: 4px;">Priority: <strong style="color: #f59e0b">Tier ${req.priority_level}</strong></div>
              </div>
            `;
            const n = state.nodeMap.get(req.user_id) || state.nodes[0];
            if (n) sendRequest(n);
          }
        } catch (e) {
          dom.agentOutput.innerHTML = `<div style="color: #ef4444; padding: 10px;">Error calling UserWorkloadAgent: ${e.message}</div>`;
        } finally {
          dom.btnTriggerAgent.disabled = false;
          dom.btnTriggerAgent.textContent = '✨ Generate Live Query via AI Agent';
        }
      });
    }

    if (dom.userSearch) {
      dom.userSearch.addEventListener('input', (e) => {
        const q = e.target.value.trim().toLowerCase();
        const match = state.nodes.find(n => n.id.toLowerCase() === q || n.id.replace('usr_', '') === q);
        if (match) selectUser(match.id);
      });
    }
    if (dom.btnClearSearch) dom.btnClearSearch.addEventListener('click', () => { dom.userSearch.value = ''; });

    if (dom.btnZoomIn) dom.btnZoomIn.addEventListener('click', () => { state.zoom = Math.min(2.5, state.zoom * 1.2); });
    if (dom.btnZoomOut) dom.btnZoomOut.addEventListener('click', () => { state.zoom = Math.max(0.5, state.zoom * 0.8); });
    if (dom.btnZoomReset) dom.btnZoomReset.addEventListener('click', () => { state.zoom = 1.0; state.pan.x = 0; state.pan.y = 0; });

    function getCoords(e) {
      const r = dom.canvas.getBoundingClientRect();
      return { x: (e.clientX - r.left - state.pan.x) / state.zoom, y: (e.clientY - r.top - state.pan.y) / state.zoom };
    }

    if (dom.canvas) {
      dom.canvas.addEventListener('click', (e) => {
        const c = getCoords(e);
        const found = state.nodes.find(n => Math.hypot(n.x - c.x, n.y - c.y) <= 18);
        if (found) selectUser(found.id);
      });

      dom.canvas.addEventListener('mousedown', (e) => {
        const c = getCoords(e);
        if (!state.nodes.some(n => Math.hypot(n.x - c.x, n.y - c.y) <= 18)) {
          state.isPanning = true;
          state.panStart.x = e.clientX - state.pan.x;
          state.panStart.y = e.clientY - state.pan.y;
        }
      });
    }

    window.addEventListener('mousemove', (e) => {
      if (state.isPanning) {
        state.pan.x = e.clientX - state.panStart.x;
        state.pan.y = e.clientY - state.panStart.y;
      } else if (dom.canvas) {
        const c = getCoords(e);
        const hovered = state.nodes.some(n => Math.hypot(n.x - c.x, n.y - c.y) <= 18);
        dom.canvas.style.cursor = hovered ? 'pointer' : 'default';
      }
    });

    window.addEventListener('mouseup', () => { state.isPanning = false; });
    if (dom.canvas) {
      dom.canvas.addEventListener('wheel', (e) => {
        e.preventDefault();
        state.zoom = Math.max(0.5, Math.min(2.5, state.zoom * (e.deltaY < 0 ? 1.1 : 0.9)));
      }, { passive: false });
    }
  }

  function resize() {
    if (!dom.container || !dom.canvas) return;
    const r = dom.container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    dom.canvas.width = r.width * dpr; dom.canvas.height = r.height * dpr;
    ctx.scale(dpr, dpr);
  }

  window.addEventListener('resize', resize);
  window.addEventListener('DOMContentLoaded', () => {
    resize();
    setupEvents();
    buildNetwork(100);
    updateInspector(state.nodeMap.get('usr_01'));
    requestAnimationFrame(renderLoop);
  });
})();
