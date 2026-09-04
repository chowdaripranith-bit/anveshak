/**
 * ANVESHAK — Security Monitoring Interface
 * Local Server Ready: Single Camera Monitoring, Weapon Detection Banner, Evidence Snapshots
 */

// Local Server Configuration
const getBackendBaseUrl = () => {
  if (window.location.protocol.startsWith('http')) {
    const port = window.location.port;
    if (port === '8000') {
      return window.location.origin;
    }
  }
  return 'http://127.0.0.1:8000';
};

const BASE_URL = getBackendBaseUrl();
const WS_URL = BASE_URL.replace(/^http/, 'ws') + '/ws/alerts';

// Interface State
const state = {
  incidents: [],
  wsConnected: false,
  cameraActive: false,
};

// Element References
const dom = {
  clock: document.getElementById('clock'),
  camStatus: document.getElementById('cam-status'),
  camIndicator: document.getElementById('cam-indicator'),
  wsStatus: document.getElementById('ws-status'),
  wsIndicator: document.getElementById('ws-indicator'),
  feedSrc: document.getElementById('feed-src'),
  feedRes: document.getElementById('feed-res'),
  cameraStream: document.getElementById('camera-stream'),
  cameraCanvas: document.getElementById('camera-canvas'),
  btnCameraToggle: document.getElementById('btn-camera-toggle'),
  camToggleLabel: document.getElementById('cam-toggle-label'),
  camRecDot: document.getElementById('cam-rec-dot'),
  weaponAlert: document.getElementById('weapon-alert'),
  weaponTitle: document.getElementById('weapon-title'),
  weaponFacility: document.getElementById('weapon-facility'),
  weaponInstruction: document.getElementById('weapon-instruction'),
  btnAckWeapon: document.getElementById('btn-ack-weapon'),
  incidentsStream: document.getElementById('incidents-stream'),
  incidentCount: document.getElementById('incident-count'),
  noIncidents: document.getElementById('no-incidents'),
  personTrackingTag: document.getElementById('person-tracking-tag'),
  threatStatusTag: document.getElementById('threat-status-tag'),
  snapshotModal: document.getElementById('snapshot-modal'),
  btnCloseModal: document.getElementById('btn-close-modal'),
  btnDismissModal: document.getElementById('btn-dismiss-modal'),
  modalImg: document.getElementById('modal-img'),
  modalTime: document.getElementById('modal-time'),
  modalClassification: document.getElementById('modal-classification'),
  modalThreat: document.getElementById('modal-threat'),
  modalTrack: document.getElementById('modal-track'),
  modalDesc: document.getElementById('modal-desc'),
  modalAction: document.getElementById('modal-action'),
};

/* ==========================================================================
   Clock System
   ========================================================================== */
function initClock() {
  const update = () => {
    const d = new Date();
    dom.clock.textContent = d.toTimeString().split(' ')[0];
  };
  update();
  setInterval(update, 1000);
}

/* ==========================================================================
   Live Camera Stream (MJPEG)
   ========================================================================== */
function initCameraDisplay() {
  const streamImg = dom.cameraStream;
  if (!streamImg) return;

  // Show a dark offline placeholder when stream is unavailable
  streamImg.onerror = () => {
    streamImg.style.background = '#050505';
    streamImg.removeAttribute('src');
    // Retry after 3 seconds
    setTimeout(() => {
      streamImg.src = `${BASE_URL}/api/stream?_t=${Date.now()}`;
    }, 3000);
  };

  // Ensure we're pointing at the correct backend URL when served standalone
  if (!streamImg.src.startsWith(BASE_URL) && !streamImg.src.includes('/api/stream')) {
    streamImg.src = `${BASE_URL}/api/stream`;
  }
}

/* ==========================================================================
   Camera Status & Control (Turn ON / Turn OFF)
   ========================================================================== */
function updateCameraUI(active) {
  state.cameraActive = active;
  if (dom.camStatus) {
    dom.camStatus.textContent = active ? 'ACTIVE (REC)' : 'STANDBY (OFF)';
  }
  if (dom.camIndicator) {
    dom.camIndicator.className = active ? 'indicator live' : 'indicator danger';
  }
  if (dom.btnCameraToggle) {
    dom.btnCameraToggle.className = active ? 'btn-camera-toggle active' : 'btn-camera-toggle off';
  }
  if (dom.camToggleLabel) {
    dom.camToggleLabel.textContent = active ? 'CAMERA ON' : 'CAMERA OFF';
  }
  if (dom.camRecDot) {
    dom.camRecDot.style.opacity = active ? '1' : '0.2';
  }
}

async function pollCameraStatus() {
  try {
    const res = await fetch(`${BASE_URL}/api/camera/status`);
    if (res.ok) {
      const data = await res.json();
      const isRunning = Boolean(data.camera_worker_running);
      updateCameraUI(isRunning);
      if (dom.feedSrc) {
        dom.feedSrc.textContent = `SOURCE: ${data.camera_source}`;
      }
    } else {
      updateCameraUI(false);
    }
  } catch (err) {
    updateCameraUI(false);
  }
}

async function toggleCamera() {
  if (!dom.btnCameraToggle) return;
  dom.btnCameraToggle.disabled = true;
  try {
    const endpoint = state.cameraActive ? '/api/camera/stop' : '/api/camera/start';
    console.info(`[ANVESHAK] Toggling camera via ${endpoint}...`);
    const res = await fetch(`${BASE_URL}${endpoint}`, { method: 'POST' });
    if (res.ok) {
      const data = await res.json();
      const isRunning = Boolean(data.camera_worker_running);
      updateCameraUI(isRunning);
      // Re-trigger stream to reload immediately
      if (dom.cameraStream) {
        dom.cameraStream.src = `${BASE_URL}/api/stream?_t=${Date.now()}`;
      }
    }
  } catch (err) {
    console.error('Failed to toggle camera:', err);
  } finally {
    dom.btnCameraToggle.disabled = false;
  }
}

/* ==========================================================================
   Real-Time Alert WebSocket
   ========================================================================== */
let wsClient = null;
let reconnectTimer = null;

function connectAlertsWebSocket() {
  if (wsClient) {
    try { wsClient.close(); } catch (e) {}
  }

  dom.wsStatus.textContent = 'CONNECTING';
  dom.wsIndicator.className = 'indicator warning';

  try {
    wsClient = new WebSocket(WS_URL);

    wsClient.onopen = () => {
      state.wsConnected = true;
      dom.wsStatus.textContent = 'CONNECTED';
      dom.wsIndicator.className = 'indicator live';
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    wsClient.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'NEW_ALERT' && payload.data) {
          handleIncomingIncident(payload.data);
        }
      } catch (err) {
        console.error('Failed to parse incoming WebSocket message:', err);
      }
    };

    wsClient.onclose = () => {
      state.wsConnected = false;
      dom.wsStatus.textContent = 'OFFLINE';
      dom.wsIndicator.className = 'indicator danger';
      scheduleReconnect();
    };

    wsClient.onerror = () => {
      state.wsConnected = false;
      dom.wsStatus.textContent = 'OFFLINE';
      dom.wsIndicator.className = 'indicator danger';
    };
  } catch (err) {
    scheduleReconnect();
  }
}

function scheduleReconnect() {
  if (!reconnectTimer) {
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectAlertsWebSocket();
    }, 3000);
  }
}

/* ==========================================================================
   Incident & Weapon Alert Processing
   ========================================================================== */
function handleIncomingIncident(alert) {
  state.incidents.unshift(alert);
  if (state.incidents.length > 40) state.incidents.pop();

  const threat = (alert.threat_level || 'HIGH').toUpperCase();
  const classification = (alert.classification || alert.incident_type || 'SECURITY ALERT').toUpperCase();
  const msg = (alert.message || '').toLowerCase();

  // 1. Weapon Detection Alert Check (Knife or Gun ONLY - grenade/explosives excluded)
  const isGun = classification.includes('GUN') || msg.includes('gun') || msg.includes('firearm') || msg.includes('pistol') || msg.includes('rifle');
  const isKnife = classification.includes('KNIFE') || msg.includes('knife') || msg.includes('blade');
  const isWeapon = isGun || isKnife;

  if (isWeapon) {
    const weaponType = isGun ? 'FIREARM / GUN' : 'BLADED WEAPON / KNIFE';
    triggerWeaponAlert(weaponType, alert);
  }

  // 2. Update Overlay Status
  dom.threatStatusTag.textContent = `THREAT STATUS: ${threat}`;
  dom.threatStatusTag.style.color = (threat === 'CRITICAL' || threat === 'HIGH') ? 'var(--alert-red)' : 'var(--alert-amber)';

  if (alert.track_id) {
    dom.personTrackingTag.textContent = `TRACKED PERSONS: ${alert.track_id}`;
  }

  renderIncidentsList();
}

function triggerWeaponAlert(weaponType, alert) {
  // Use innerHTML so HTML entities render (e.g. &mdash;)
  dom.weaponTitle.innerHTML = `${weaponType} DETECTED &mdash; CRITICAL SECURITY ALERT`;
  dom.weaponFacility.textContent = `FACILITY LOCATION: Commercial Floor / Public Area Sector A \u2022 CAM-01`;
  dom.weaponInstruction.textContent = `ATTENTION SECURITY PERSONNEL & OWNER: An active ${weaponType.toLowerCase()} detection occurred. Immediately dispatch on-site armed response protocol and notify facility management.`;
  dom.weaponAlert.hidden = false;
}

function getEvidenceUrl(item) {
  const path = item.evidence_url || item.snapshot || item.evidence_path;
  if (!path) return null;
  const clean = path.replace(/\\/g, '/');
  if (clean.startsWith('http://') || clean.startsWith('https://')) return clean;
  if (clean.startsWith('/evidence/')) return `${BASE_URL}${clean}`;
  if (clean.includes('evidence/')) {
    const sub = clean.substring(clean.indexOf('evidence/'));
    return `${BASE_URL}/${sub}`;
  }
  const fname = clean.split('/').pop();
  return `${BASE_URL}/evidence/${fname}`;
}

function renderIncidentsList() {
  const container = dom.incidentsStream;
  if (state.incidents.length === 0) {
    dom.noIncidents.style.display = 'flex';
    dom.incidentCount.textContent = '0 LOGGED';
    return;
  }

  dom.noIncidents.style.display = 'none';
  dom.incidentCount.textContent = `${state.incidents.length} LOGGED`;

  container.innerHTML = '';
  state.incidents.forEach((item, index) => {
    const card = document.createElement('article');
    const threat = (item.threat_level || 'HIGH').toUpperCase();
    card.className = `incident-card threat-${threat}`;

    const timeStr = new Date(item.timestamp || Date.now()).toLocaleTimeString();
    const title = item.classification || item.incident_type || 'SECURITY ALERT';
    const explanation = item.message || 'Incident detected by computer vision layer.';
    const action = item.recommended_action || '';
    const trackBadge = item.track_id ? `Subject: Person #${item.track_id}` : 'General Sector';
    const evidenceUrl = getEvidenceUrl(item);

    let mediaHtml = '';
    if (evidenceUrl) {
      mediaHtml = `
        <div class="incident-thumbnail-container" data-idx="${index}" title="Click to inspect snapshot">
          <img class="incident-thumbnail" src="${escapeHtml(evidenceUrl)}" alt="Captured Evidence Snapshot" loading="lazy" />
          <span class="incident-thumbnail-tag">EVIDENCE SNAPSHOT</span>
        </div>
      `;
    }

    card.innerHTML = `
      <div class="incident-card-top">
        <span class="badge-threat ${threat}">${threat}</span>
        <span class="incident-time">${timeStr} &bull; CAM 01</span>
      </div>
      <div class="incident-title">${escapeHtml(title)}</div>
      ${mediaHtml}
      <div class="incident-text">${escapeHtml(explanation)}</div>
      ${action ? `<div class="incident-action-box"><strong>ACTION:</strong> ${escapeHtml(action)}</div>` : ''}
      <div class="incident-card-footer">
        <span class="track-tag">${trackBadge}</span>
        <button class="btn-inspect" data-idx="${index}">Inspect Snapshot</button>
      </div>
    `;

    card.querySelector('.btn-inspect').addEventListener('click', () => {
      openEvidenceModal(item);
    });

    const thumbEl = card.querySelector('.incident-thumbnail-container');
    if (thumbEl) {
      thumbEl.addEventListener('click', () => {
        openEvidenceModal(item);
      });
    }

    container.appendChild(card);
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ==========================================================================
   Evidence Inspection Modal
   ========================================================================== */
function openEvidenceModal(item) {
  dom.modalTime.textContent = new Date(item.timestamp || Date.now()).toLocaleString();
  dom.modalClassification.textContent = item.classification || item.incident_type || 'SECURITY DETECTION';
  dom.modalThreat.textContent = (item.threat_level || 'HIGH').toUpperCase();
  dom.modalTrack.textContent = item.track_id ? `Person #${item.track_id}` : 'CAM-01 Sector';
  dom.modalDesc.textContent = item.message || 'Detection logged by monitoring system.';
  dom.modalAction.textContent = item.recommended_action || 'Inspect sector and follow security protocol.';

  const evidenceUrl = getEvidenceUrl(item);
  if (evidenceUrl) {
    dom.modalImg.src = evidenceUrl;
  } else {
    dom.modalImg.src = `data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="320" viewBox="0 0 640 320"><rect width="100%" height="100%" fill="%23050505"/><text x="50%" y="50%" fill="%23666666" font-family="monospace" font-size="14" text-anchor="middle">SNAPSHOT ARCHIVED ON LOCAL SERVER</text></svg>`;
  }

  dom.snapshotModal.hidden = false;
}

function closeEvidenceModal() {
  dom.snapshotModal.hidden = true;
}

/* ==========================================================================
   Local Server Test Simulation Dispatcher
   ========================================================================== */
async function dispatchLocalSimulation(incidentType, objectDetected) {
  try {
    const payload = {
      incident_type: incidentType,
      object_detected: objectDetected,
      confidence: 0.94,
      camera_id: 1,
      other_info: {
        track_id: Math.floor(Math.random() * 4) + 1,
        rack_zone: 'Main_Display_Rack_1',
        interaction_duration: (Math.random() * 3 + 2).toFixed(1),
      },
    };

    console.info('[ANVESHAK LOCAL] Dispatching test simulation:', payload);
    const res = await fetch(`${BASE_URL}/api/events/simulate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (res.ok) {
      console.info('[ANVESHAK LOCAL] Simulation accepted by backend.');
    }
  } catch (err) {
    console.error('Local server simulation failed:', err);
  }
}

/* ==========================================================================
   Application Initialization
   ========================================================================== */
function init() {
  initClock();
  initCameraDisplay();
  connectAlertsWebSocket();
  pollCameraStatus();
  setInterval(pollCameraStatus, 3500);

  // Camera toggle control (Turn ON / Turn OFF)
  if (dom.btnCameraToggle) {
    dom.btnCameraToggle.addEventListener('click', toggleCamera);
  }

  // Weapon banner dismiss
  dom.btnAckWeapon.addEventListener('click', () => {
    dom.weaponAlert.hidden = true;
  });

  // Evidence modal controls
  dom.btnCloseModal.addEventListener('click', closeEvidenceModal);
  dom.btnDismissModal.addEventListener('click', closeEvidenceModal);

  // Clear modal on overlay click
  dom.snapshotModal.addEventListener('click', (e) => {
    if (e.target === dom.snapshotModal) closeEvidenceModal();
  });

  // Clear log
  dom.incidentCount.addEventListener('click', () => {
    state.incidents = [];
    renderIncidentsList();
  });

  // Local test buttons
  document.querySelectorAll('.btn-test').forEach((btn) => {
    btn.addEventListener('click', () => {
      const eventType = btn.getAttribute('data-event');
      const obj = btn.getAttribute('data-obj');
      dispatchLocalSimulation(eventType, obj);
    });
  });

  console.info(`ANVESHAK Security Interface running on ${BASE_URL}. California FB typography active.`);
}

window.addEventListener('DOMContentLoaded', init);
