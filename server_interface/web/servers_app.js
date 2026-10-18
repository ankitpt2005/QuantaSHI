/**
 * Virtual Data Centre - Heterogeneous Server Cluster Simulator
 * Part 2: Servers Interface Component
 */

(function () {
  'use strict';

  // --- 1. The Three Heterogeneous Virtual Servers (Proven Parameters) ---
  const SERVERS_CONFIG = [
    {
      id: 'srv_gpu_01',
      name: 'Server A: High-Performance GPU',
      model: 'NVIDIA H100 PCIe 80GB HBM3',
      type: 'HIGH_PERF_ACCELERATOR',
      maxStreams: 32,
      prefillSpeed: 12000, // tokens/s
      decodeSpeed: 85.0,    // tokens/s/stream
      vramGB: 80,
      idlePowerW: 75.0,
      peakPowerW: 350.0,
      powerExp: 1.35,
      color: '#1d70b8',
    },
    {
      id: 'srv_acc_02',
      name: 'Server B: Energy-Efficient Tensor',
      model: 'NVIDIA L4 24GB / IBM Telum On-Chip',
      type: 'BALANCED_ACCELERATOR',
      maxStreams: 16,
      prefillSpeed: 3200,
      decodeSpeed: 38.0,
      vramGB: 24,
      idlePowerW: 25.0,
      peakPowerW: 72.0,
      powerExp: 1.40,
      color: '#1e824c',
    },
    {
      id: 'srv_cpu_03',
      name: 'Server C: General-Purpose CPU',
      model: 'Intel Xeon Platinum 8480+ / LinuxONE Core',
      type: 'COMMODITY_CPU',
      maxStreams: 4,
      prefillSpeed: 650,
      decodeSpeed: 12.0,
      vramGB: 64, // Host RAM
      idlePowerW: 45.0,
      peakPowerW: 220.0,
      powerExp: 1.10,
      color: '#b45309',
    },
  ];

  // --- Server Cluster State ---
  const serverState = {
    servers: SERVERS_CONFIG.map(cfg => ({
      ...cfg,
      status: 'IDLE', // IDLE, PROCESSING, CONGESTED, DRAINING, OFFLINE
      activeStreams: [],
      queue: [],
      currentPowerW: cfg.idlePowerW,
      cumulativeEnergyJ: 0.0,
      completedCount: 0,
      sloViolations: 0,
      totalTokensProcessed: 0,
    })),
    selectedServerId: 'srv_gpu_01',
    recentCompletions: [],
    lastFrame: performance.now(),
    isRunning: true,
  };

  const $ = (id) => document.getElementById(id);

  // --- 2. Request Execution Mechanics ---
  function calculateExecTime(server, req) {
    const activeCount = Math.max(1, server.activeStreams.length);
    // Prefill Phase (Compute bound)
    const tPrefill = (req.context_tokens / (server.prefillSpeed * Math.pow(activeCount, 0.15)));
    // Decode Phase (Memory bandwidth bound)
    const tDecode = (req.max_output_tokens / server.decodeSpeed) * (1.0 + 0.04 * (activeCount - 1));
    return tPrefill + tDecode; // in seconds
  }

  function calculatePower(server) {
    if (server.status === 'OFFLINE') return 0.0;
    const u = Math.min(1.0, server.activeStreams.length / server.maxStreams);
    // Fan et al. power curve
    const dynamicFactor = (2.0 * u) - Math.pow(u, server.powerExp);
    return server.idlePowerW + (server.peakPowerW - server.idlePowerW) * Math.max(0, dynamicFactor);
  }

  function dispatchTaskToServer(serverId, req) {
    const s = serverState.servers.find(srv => srv.id === serverId);
    if (!s || s.status === 'OFFLINE' || s.status === 'DRAINING') return false;

    const arrivalTime = performance.now() / 1000.0;
    const task = {
      ...req,
      simArrivalTime: arrivalTime,
      simStartTime: null,
      execDurationSec: calculateExecTime(s, req),
      progressSec: 0.0,
    };

    if (s.activeStreams.length < s.maxStreams) {
      task.simStartTime = arrivalTime;
      s.activeStreams.push(task);
      s.status = (s.activeStreams.length >= s.maxStreams) ? 'CONGESTED' : 'PROCESSING';
    } else {
      s.queue.push(task);
      s.status = 'CONGESTED';
    }
    updateServersUI();
    return true;
  }

  // --- 3. Simulation Step ---
  function simulationStep(time) {
    const dt = Math.min((time - serverState.lastFrame) / 1000.0, 0.1);
    serverState.lastFrame = time;

    serverState.servers.forEach(s => {
      if (s.status === 'OFFLINE') {
        s.currentPowerW = 0.0;
        return;
      }

      // Progress active executions
      for (let i = s.activeStreams.length - 1; i >= 0; i--) {
        const stream = s.activeStreams[i];
        stream.progressSec += dt;

        if (stream.progressSec >= stream.execDurationSec) {
          // Completed!
          s.activeStreams.splice(i, 1);
          s.completedCount++;
          s.totalTokensProcessed += (stream.context_tokens + stream.max_output_tokens);

          const nowSec = performance.now() / 1000.0;
          const waitTimeMs = Math.max(0, (stream.simStartTime - stream.simArrivalTime) * 1000.0);
          const execTimeMs = stream.execDurationSec * 1000.0;
          const totalLatencyMs = waitTimeMs + execTimeMs;
          const sloMet = totalLatencyMs <= stream.deadline_slo_ms;

          if (!sloMet) s.sloViolations++;

          // Energy allocated for this request
          const avgPower = s.currentPowerW;
          const reqEnergyJ = avgPower * stream.execDurationSec;

          serverState.recentCompletions.unshift({
            requestId: stream.request_id,
            serverId: s.id,
            workloadType: stream.workload_type,
            tokens: stream.context_tokens + stream.max_output_tokens,
            totalLatencyMs,
            deadlineMs: stream.deadline_slo_ms,
            sloMet,
            energyJ: reqEnergyJ,
            timeStr: new Date().toLocaleTimeString(),
          });

          if (serverState.recentCompletions.length > 50) {
            serverState.recentCompletions.pop();
          }

          // Pull from ingress queue
          if (s.queue.length > 0 && s.status !== 'DRAINING') {
            const nextTask = s.queue.shift();
            nextTask.simStartTime = nowSec;
            nextTask.execDurationSec = calculateExecTime(s, nextTask);
            s.activeStreams.push(nextTask);
          }
        }
      }

      // Update server state and energy integration
      if (s.activeStreams.length === 0 && s.queue.length === 0) {
        s.status = 'IDLE';
      } else if (s.activeStreams.length >= s.maxStreams) {
        s.status = 'CONGESTED';
      } else {
        s.status = 'PROCESSING';
      }

      s.currentPowerW = calculatePower(s);
      s.cumulativeEnergyJ += s.currentPowerW * dt;
    });

    updateServersUI();
    requestAnimationFrame(simulationStep);
  }

  // --- 4. Render Servers UI ---
  function updateServersUI() {
    const container = $('servers-grid-container');
    if (!container) return;

    // Render cards if not initialized
    if (container.children.length === 0) {
      container.innerHTML = serverState.servers.map(s => `
        <div class="server-chassis-card" id="card-${s.id}" data-id="${s.id}">
          <div class="server-chassis-header">
            <div class="server-name-row">
              <span class="server-id-badge" style="color: ${s.color}">${s.id}</span>
              <span class="server-status-pill pill-${s.status.toLowerCase()}" id="pill-${s.id}">${s.status}</span>
            </div>
            <h3 class="server-title">${s.name}</h3>
            <p class="server-model">${s.model}</p>
          </div>

          <div class="server-metrics-body">
            <!-- Active Streams Meter -->
            <div class="meter-row">
              <div class="meter-label-row">
                <span>Active Compute Streams</span>
                <strong id="streams-val-${s.id}">0 / ${s.maxStreams}</strong>
              </div>
              <div class="meter-bar-track">
                <div class="meter-bar-fill" id="streams-bar-${s.id}" style="width: 0%; background: ${s.color}"></div>
              </div>
            </div>

            <!-- Instantaneous Power Meter -->
            <div class="meter-row">
              <div class="meter-label-row">
                <span>Power Draw: <b id="power-val-${s.id}">${s.idlePowerW.toFixed(1)} W</b></span>
                <span class="meter-limit">Peak: ${s.peakPowerW}W</span>
              </div>
              <div class="meter-bar-track">
                <div class="meter-bar-fill" id="power-bar-${s.id}" style="width: 20%; background: #f59e0b"></div>
              </div>
            </div>

            <!-- Ingress Queue & Latency -->
            <div class="stats-mini-grid">
              <div class="mini-stat">
                <span class="stat-lbl">Queue Depth</span>
                <span class="stat-val" id="queue-val-${s.id}">0</span>
              </div>
              <div class="mini-stat">
                <span class="stat-lbl">Completed</span>
                <span class="stat-val" id="completed-val-${s.id}">0</span>
              </div>
              <div class="mini-stat">
                <span class="stat-lbl">SLO Misses</span>
                <span class="stat-val" id="slo-val-${s.id}">0</span>
              </div>
              <div class="mini-stat">
                <span class="stat-lbl">Cumulative Energy</span>
                <span class="stat-val" id="energy-val-${s.id}">0 J</span>
              </div>
            </div>

            <!-- Actions -->
            <div class="server-card-actions">
              <button class="btn btn-secondary btn-sm" onclick="window.QuantaSHI_Servers.injectSampleTask('${s.id}')">
                + Dispatch Test Task
              </button>
              <button class="btn btn-secondary btn-sm" id="btn-toggle-${s.id}" onclick="window.QuantaSHI_Servers.toggleServerState('${s.id}')">
                Simulate Drain
              </button>
            </div>
          </div>
        </div>
      `).join('');
    }

    // Dynamic Updates
    serverState.servers.forEach(s => {
      const uPct = Math.min(100, (s.activeStreams.length / s.maxStreams) * 100);
      const pPct = Math.min(100, (s.currentPowerW / s.peakPowerW) * 100);

      const streamsVal = $(`streams-val-${s.id}`);
      if (streamsVal) streamsVal.textContent = `${s.activeStreams.length} / ${s.maxStreams} (${uPct.toFixed(0)}%)`;

      const streamsBar = $(`streams-bar-${s.id}`);
      if (streamsBar) streamsBar.style.width = `${uPct}%`;

      const powerVal = $(`power-val-${s.id}`);
      if (powerVal) powerVal.textContent = `${s.currentPowerW.toFixed(1)} W`;

      const powerBar = $(`power-bar-${s.id}`);
      if (powerBar) powerBar.style.width = `${pPct}%`;

      const queueVal = $(`queue-val-${s.id}`);
      if (queueVal) queueVal.textContent = s.queue.length;

      const completedVal = $(`completed-val-${s.id}`);
      if (completedVal) completedVal.textContent = s.completedCount;

      const sloVal = $(`slo-val-${s.id}`);
      if (sloVal) {
        sloVal.textContent = s.sloViolations;
        sloVal.style.color = s.sloViolations > 0 ? '#ef4444' : '#10b981';
      }

      const energyVal = $(`energy-val-${s.id}`);
      if (energyVal) energyVal.textContent = s.cumulativeEnergyJ > 1000 ? `${(s.cumulativeEnergyJ / 1000).toFixed(1)} kJ` : `${s.cumulativeEnergyJ.toFixed(0)} J`;

      const pill = $(`pill-${s.id}`);
      if (pill) {
        pill.textContent = s.status;
        pill.className = `server-status-pill pill-${s.status.toLowerCase()}`;
      }
    });

    // Update Telemetry Header
    const totalPower = serverState.servers.reduce((acc, s) => acc + s.currentPowerW, 0);
    const totalActive = serverState.servers.reduce((acc, s) => acc + s.activeStreams.length, 0);
    const totalCompleted = serverState.servers.reduce((acc, s) => acc + s.completedCount, 0);

    const srvPower = $('srv-total-power');
    if (srvPower) srvPower.textContent = `${totalPower.toFixed(1)} W`;

    const srvActive = $('srv-total-active');
    if (srvActive) srvActive.textContent = `${totalActive} / 52`;

    const srvDone = $('srv-total-completed');
    if (srvDone) srvDone.textContent = totalCompleted;

    // Update Logs
    const logContainer = $('server-completion-stream');
    if (logContainer && serverState.recentCompletions.length > 0) {
      logContainer.innerHTML = serverState.recentCompletions.slice(0, 15).map(c => `
        <div class="stream-item ${c.sloMet ? '' : 'slo-fail'}">
          <div class="stream-top">
            <span class="stream-user" style="color: ${c.serverId === 'srv_gpu_01' ? '#38bdf8' : c.serverId === 'srv_acc_02' ? '#10b981' : '#f59e0b'}">${c.serverId}</span>
            <span class="stream-time">${c.timeStr}</span>
          </div>
          <div class="stream-text">${c.workloadType} &bull; ${c.tokens} tokens &bull; ${c.totalLatencyMs.toFixed(0)}ms (SLA: ${c.deadlineMs}ms)</div>
          <div style="font-size: 0.68rem; display: flex; justify-content: space-between; margin-top: 2px;">
            <span style="color: ${c.sloMet ? '#10b981' : '#ef4444'}">${c.sloMet ? '✓ SLA MET' : '✗ SLA VIOLATION'}</span>
            <span style="color: #94a3b8">${c.energyJ.toFixed(1)} J</span>
          </div>
        </div>
      `).join('');
    }
  }

  // --- 5. Public API for UI Interaction ---
  window.QuantaSHI_Servers = {
    injectSampleTask(serverId) {
      const sampleReq = {
        request_id: `req_${Math.random().toString(36).substring(2, 9)}`,
        user_id: `usr_${Math.floor(Math.random() * 99 + 1)}`,
        workload_type: Math.random() > 0.5 ? 'TEXT_CHAT' : 'RAG_QA',
        context_tokens: Math.floor(128 + Math.random() * 2048),
        max_output_tokens: Math.floor(64 + Math.random() * 384),
        deadline_slo_ms: Math.floor(400 + Math.random() * 1500),
      };
      dispatchTaskToServer(serverId, sampleReq);
    },

    toggleServerState(serverId) {
      const s = serverState.servers.find(srv => srv.id === serverId);
      if (!s) return;
      if (s.status === 'DRAINING' || s.status === 'OFFLINE') {
        s.status = 'IDLE';
        $(`btn-toggle-${s.id}`).textContent = 'Simulate Drain';
      } else {
        s.status = 'DRAINING';
        $(`btn-toggle-${s.id}`).textContent = 'Restore Node';
      }
      updateServersUI();
    },

    resetCluster() {
      serverState.servers.forEach(s => {
        s.status = 'IDLE';
        s.activeStreams = [];
        s.queue = [];
        s.currentPowerW = s.idlePowerW;
        s.cumulativeEnergyJ = 0.0;
        s.completedCount = 0;
        s.sloViolations = 0;
        s.totalTokensProcessed = 0;
        const btnToggle = $(`btn-toggle-${s.id}`);
        if (btnToggle) btnToggle.textContent = 'Simulate Drain';
      });
      serverState.recentCompletions = [];
      const logContainer = $('server-completion-stream');
      if (logContainer) {
        logContainer.innerHTML = `
          <div style="font-size: 0.75rem; color: #64748b; padding: 20px; text-align: center;">
            Dispatched tasks will report execution latency, SLA compliance, and energy consumption here in real-time.
          </div>
        `;
      }
      updateServersUI();
    },

      const btnResetServers = $('btn-reset-servers');
      if (btnResetServers) {
        btnResetServers.addEventListener('click', () => {
          window.QuantaSHI_Servers.resetCluster();
        });
      }

      // AI Ops Agent Tab & Trigger Button
      const tabEvents = $('tab-srv-events');
      const tabAgent = $('tab-srv-agent');
      const viewEvents = $('view-srv-events');
      const viewAgent = $('view-srv-agent');
      const btnTriggerServerAgent = $('btn-trigger-server-agent');
      const serverAgentOutput = $('server-agent-output');

      if (tabEvents && tabAgent) {
        tabEvents.addEventListener('click', () => {
          tabEvents.classList.add('active');
          tabAgent.classList.remove('active');
          if (viewEvents) viewEvents.classList.remove('hidden');
          if (viewAgent) viewAgent.classList.add('hidden');
        });
        tabAgent.addEventListener('click', () => {
          tabAgent.classList.add('active');
          tabEvents.classList.remove('active');
          if (viewAgent) viewAgent.classList.remove('hidden');
          if (viewEvents) viewEvents.classList.add('hidden');
        });
      }

      if (btnTriggerServerAgent) {
        btnTriggerServerAgent.addEventListener('click', async () => {
          btnTriggerServerAgent.disabled = true;
          btnTriggerServerAgent.textContent = '⏳ AI Agent Diagnosing...';
          try {
            const res = await fetch('/api/agent/server', { method: 'POST' });
            const data = await res.json();
            if (data.success && data.diagnosis) {
              const diag = data.diagnosis;
              const healthColor = diag.cluster_health_score >= 80 ? '#10b981' : diag.cluster_health_score >= 50 ? '#f59e0b' : '#ef4444';
              serverAgentOutput.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                  <span style="font-weight: 700; color: #10b981;">Health Assessment</span>
                  <span style="background: ${healthColor}22; color: ${healthColor}; border: 1px solid ${healthColor}; padding: 2px 8px; border-radius: 999px; font-weight: 700;">Score: ${diag.cluster_health_score}/100</span>
                </div>
                <div style="background: #162032; border: 1px solid #1e293b; border-radius: 6px; padding: 10px; margin-bottom: 8px; font-size: 0.72rem; color: #cbd5e1;">
                  ${diag.executive_summary}
                </div>
                <div style="font-size: 0.7rem; margin-bottom: 8px;">
                  <span style="color: #94a3b8;">Bottleneck: </span><strong style="color: #f8fafc;">${diag.primary_bottleneck}</strong>
                </div>
                <div style="font-size: 0.7rem; color: #94a3b8; margin-bottom: 4px;">Recommended Directives:</div>
                <ul style="padding-left: 16px; font-size: 0.7rem; color: #38bdf8;">
                  ${diag.recommended_actions.map(act => `<li>${act}</li>`).join('')}
                </ul>
              `;
            }
          } catch (e) {
            serverAgentOutput.innerHTML = `<div style="color: #ef4444; padding: 10px;">Error calling ServerOpsAgent: ${e.message}</div>`;
          } finally {
            btnTriggerServerAgent.disabled = false;
            btnTriggerServerAgent.textContent = '🩺 Run AI Cluster Diagnostic';
          }
        });
      }

      requestAnimationFrame(simulationStep);
    }
  };

  // Auto-start when loaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.QuantaSHI_Servers.start());
  } else {
    window.QuantaSHI_Servers.start();
  }
})();
