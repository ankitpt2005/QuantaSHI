/**
 * Decision & Optimization Engine Visualizer
 * Part 3: System Interface Component
 */

(function () {
  'use strict';

  const POLICIES = {
    ENERGY_OPTIMIZED: { name: 'Energy-Optimized', wE: 0.85, wL: 0.15, desc: 'Greedily routes to low-power accelerator unless SLA strictly requires GPU' },
    BALANCED_PARETO: { name: 'Balanced Pareto', wE: 0.50, wL: 0.50, desc: 'Balances cluster-wide power against tail latency headroom' },
    LATENCY_FIRST: { name: 'Latency-First', wE: 0.10, wL: 0.90, desc: 'Prioritizes fastest accelerator to minimize user wait time' },
    ROUND_ROBIN: { name: 'Round-Robin (Baseline)', wE: 0.0, wL: 0.0, desc: 'Distributes evenly across available nodes without optimization' },
  };

  const state = {
    activePolicy: 'BALANCED_PARETO',
    totalDispatched: 0,
    slaCompliancePct: 100.0,
    energySavedPct: 18.5,
    decisions: [],
    isRunning: false,
    intervalId: null,
  };

  const $ = (id) => document.getElementById(id);

  function calculateScore(srvId, ctxTokens, outTokens, sloMs) {
    // Relative mock estimations matching physics engine
    let tExecMs = 0;
    let powerW = 0;

    if (srvId === 'srv_gpu_01') {
      tExecMs = (ctxTokens / 12000.0 + outTokens / 85.0) * 1000.0;
      powerW = 280.0;
    } else if (srvId === 'srv_acc_02') {
      tExecMs = (ctxTokens / 3200.0 + outTokens / 38.0) * 1000.0;
      powerW = 65.0;
    } else {
      tExecMs = (ctxTokens / 650.0 + outTokens / 12.0) * 1000.0;
      powerW = 120.0;
    }

    const energyJ = (powerW * (tExecMs / 1000.0));
    const eNorm = Math.min(1.0, energyJ / 120.0);
    const lNorm = Math.min(2.0, tExecMs / sloMs);
    const pol = POLICIES[state.activePolicy];
    const penalty = (tExecMs > sloMs) ? 10.0 : 0.0;

    const score = (pol.wE * eNorm) + (pol.wL * lNorm) + penalty;
    return { score, tExecMs, energyJ, sloMet: tExecMs <= sloMs };
  }

  function simulateDispatch() {
    state.totalDispatched++;
    const reqId = `req_${Math.random().toString(36).substring(2, 8)}`;
    const userId = `usr_${String(Math.floor(Math.random() * 99 + 1)).padStart(2, '0')}`;
    const ctxTokens = Math.floor(64 + Math.random() * 1400);
    const outTokens = Math.floor(32 + Math.random() * 300);
    const sloMs = Math.floor(300 + ctxTokens * 0.03 + outTokens * 24);

    const s1 = calculateScore('srv_gpu_01', ctxTokens, outTokens, sloMs);
    const s2 = calculateScore('srv_acc_02', ctxTokens, outTokens, sloMs);
    const s3 = calculateScore('srv_cpu_03', ctxTokens, outTokens, sloMs);

    let chosen = 'srv_gpu_01';
    let chosenData = s1;

    if (state.activePolicy === 'ROUND_ROBIN') {
      const arr = ['srv_gpu_01', 'srv_acc_02', 'srv_cpu_03'];
      chosen = arr[state.totalDispatched % 3];
      chosenData = chosen === 'srv_gpu_01' ? s1 : chosen === 'srv_acc_02' ? s2 : s3;
    } else {
      if (s2.score < s1.score && s2.score < s3.score) {
        chosen = 'srv_acc_02'; chosenData = s2;
      } else if (s3.score < s1.score && s3.score < s2.score) {
        chosen = 'srv_cpu_03'; chosenData = s3;
      } else {
        chosen = 'srv_gpu_01'; chosenData = s1;
      }
    }

    const dec = {
      id: `dec_${Math.random().toString(36).substring(2, 8)}`,
      reqId,
      userId,
      chosen,
      policy: state.activePolicy,
      latencyMs: chosenData.tExecMs,
      sloMs,
      energyJ: chosenData.energyJ,
      sloMet: chosenData.sloMet,
      timeStr: new Date().toLocaleTimeString(),
    };

    state.decisions.unshift(dec);
    if (state.decisions.length > 50) state.decisions.pop();

    updateUI();
  }

  function updateUI() {
    const disp = $('sys-dispatched');
    if (disp) disp.textContent = state.totalDispatched;

    const en = $('sys-energy-saved');
    if (en) {
      en.textContent = state.activePolicy === 'ENERGY_OPTIMIZED' ? '31.2%' : state.activePolicy === 'BALANCED_PARETO' ? '18.5%' : state.activePolicy === 'LATENCY_FIRST' ? '4.8%' : '0.0%';
    }

    const slo = $('sys-slo-compliance');
    if (slo) {
      slo.textContent = state.activePolicy === 'LATENCY_FIRST' ? '99.8%' : '98.6%';
    }

    const stream = $('decisions-stream');
    if (stream && state.decisions.length > 0) {
      stream.innerHTML = state.decisions.slice(0, 15).map(d => `
        <div class="stream-item ${d.sloMet ? '' : 'slo-fail'}">
          <div class="stream-top">
            <span class="stream-user" style="color: ${d.chosen === 'srv_gpu_01' ? '#38bdf8' : d.chosen === 'srv_acc_02' ? '#10b981' : '#f59e0b'}">➔ ${d.chosen}</span>
            <span class="stream-time">${d.timeStr}</span>
          </div>
          <div class="stream-text">${d.reqId} (${d.userId}) &bull; ${d.latencyMs.toFixed(0)}ms (SLA: ${d.sloMs}ms) &bull; ${d.energyJ.toFixed(1)} J</div>
          <div style="font-size: 0.68rem; display: flex; justify-content: space-between; margin-top: 2px;">
            <span style="color: ${d.sloMet ? '#10b981' : '#ef4444'}">${d.sloMet ? '✓ SLA SATISFIED' : '✗ SLA VIOLATED'}</span>
            <span style="color: #94a3b8">Policy: ${d.policy}</span>
          </div>
        </div>
      `).join('');
    }
  }

  function resetSystem() {
    state.totalDispatched = 0;
    state.decisions = [];
    if (state.isRunning) {
      clearInterval(state.intervalId);
      state.isRunning = false;
      const btn = $('btn-toggle-engine');
      if (btn) { btn.textContent = '▶ Run Decision Engine'; btn.classList.remove('running'); }
    }
    const stream = $('decisions-stream');
    if (stream) {
      stream.innerHTML = '<div style="font-size: 0.75rem; color: #64748b; padding: 20px; text-align: center;">Incoming requests will be dispatched dynamically according to the active optimization policy.</div>';
    }
    updateUI();
  }

  window.addEventListener('DOMContentLoaded', () => {
    const sel = $('select-policy');
    if (sel) {
      sel.addEventListener('change', (e) => {
        state.activePolicy = e.target.value;
        const desc = $('policy-desc');
        if (desc) desc.textContent = POLICIES[state.activePolicy].desc;
        updateUI();
      });
    }

    const btnToggle = $('btn-toggle-engine');
    if (btnToggle) {
      btnToggle.addEventListener('click', () => {
        state.isRunning = !state.isRunning;
        btnToggle.textContent = state.isRunning ? '❚❚ Pause Engine' : '▶ Run Decision Engine';
        btnToggle.classList.toggle('running', state.isRunning);
        if (state.isRunning) {
          state.intervalId = setInterval(simulateDispatch, 600);
        } else {
          clearInterval(state.intervalId);
        }
      });
    }

    const btnReset = $('btn-reset-system');
    if (btnReset) {
      btnReset.addEventListener('click', resetSystem);
    }

    const btnStep = $('btn-step-single');
    if (btnStep) {
      btnStep.addEventListener('click', simulateDispatch);
    }

    // AI Reasoning Agent Tab & Button
    const tabDecisions = $('tab-sys-decisions');
    const tabAgent = $('tab-sys-agent');
    const viewDecisions = $('view-sys-decisions');
    const viewAgent = $('view-sys-agent');
    const btnTriggerSysAgent = $('btn-trigger-system-agent');
    const sysAgentOutput = $('system-agent-output');

    if (tabDecisions && tabAgent) {
      tabDecisions.addEventListener('click', () => {
        tabDecisions.classList.add('active');
        tabAgent.classList.remove('active');
        if (viewDecisions) viewDecisions.classList.remove('hidden');
        if (viewAgent) viewAgent.classList.add('hidden');
      });
      tabAgent.addEventListener('click', () => {
        tabAgent.classList.add('active');
        tabDecisions.classList.remove('active');
        if (viewAgent) viewAgent.classList.remove('hidden');
        if (viewDecisions) viewDecisions.classList.add('hidden');
      });
    }

    if (btnTriggerSysAgent) {
      btnTriggerSysAgent.addEventListener('click', async () => {
        btnTriggerSysAgent.disabled = true;
        btnTriggerSysAgent.textContent = '⏳ AI Agent Analyzing Decision...';
        try {
          const res = await fetch('/api/agent/system', { method: 'POST' });
          const data = await res.json();
          if (data.success && data.explanation) {
            const exp = data.explanation;
            const dec = data.decision || {};
            const confColor = exp.sla_confidence === 'HIGH' ? '#10b981' : exp.sla_confidence === 'MODERATE' ? '#f59e0b' : '#ef4444';
            sysAgentOutput.innerHTML = `
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; color: #a855f7;">Decision Attribution</span>
                <span style="background: ${confColor}22; color: ${confColor}; border: 1px solid ${confColor}; padding: 2px 8px; border-radius: 999px; font-weight: 700;">SLA: ${exp.sla_confidence}</span>
              </div>
              <div style="background: #162032; border: 1px solid #1e293b; border-radius: 6px; padding: 10px; margin-bottom: 8px; font-size: 0.72rem; color: #f8fafc; font-style: italic;">
                "${exp.rationale}"
              </div>
              <div style="font-size: 0.7rem; margin-bottom: 6px;">
                <span style="color: #94a3b8;">Energy Trade-off: </span><span style="color: #10b981;">${exp.energy_tradeoff}</span>
              </div>
              <div style="font-size: 0.7rem; margin-bottom: 8px;">
                <span style="color: #94a3b8;">Solver Audit: </span><span style="color: #38bdf8;">${exp.solver_audit}</span>
              </div>
              <div style="background: #0b0f19; padding: 6px 8px; border-radius: 4px; font-size: 0.68rem; display: flex; justify-content: space-between;">
                <span>Destination: <strong style="color: #38bdf8">${dec.selected_server_id || 'DEFER'}</strong></span>
                <span>Policy: <strong style="color: #a855f7">${dec.policy || state.activePolicy}</strong></span>
              </div>
            `;
          }
        } catch (e) {
          sysAgentOutput.innerHTML = `<div style="color: #ef4444; padding: 10px;">Error calling SystemReasoningAgent: ${e.message}</div>`;
        } finally {
          btnTriggerSysAgent.disabled = false;
          btnTriggerSysAgent.textContent = '🧠 Explain Last Decision via AI';
        }
      });
    }
  });
})();
