/**
 * WOB Main App Controller
 * Direct WebSocket connection to TouchDesigner.
 * Settings (sample rate, wake lock, haptic) are pushed from TD via config message.
 */
(() => {
  let broadcasting = false;
  let sampleRate = 30;
  let broadcastInterval = null;
  let wakeLock = null;
  let touchPadActive = false;
  let hapticEnabled = true;
  let devMode = true; // true = full UI, false = minimal/auto mode
  let vizInitialized = false;
  let cameraEnabled = false; // config: auto-enable camera on connect
  let micEnabled = false;    // config: wob_config sensor_microphone에서 로드
  let audioEchoCancellation = false;  // config: 0=raw, 1=on
  let audioNoiseSuppression = false;
  let audioAutoGain = false;
  let iceServersFromConfig = null;   // from wob_config ice_servers (JSON)
  let iceTransportPolicyFromConfig = null;  // 'relay' | 'all' | null

  function _isTunnelConnection() {
    const addr = (els.tdAddress && els.tdAddress.value || '').toLowerCase();
    return addr.includes('trycloudflare.com') || addr.includes('cloudflare') || addr.includes('.cfargotunnel.com');
  }

  const $ = (id) => document.getElementById(id);
  const els = {};

  // Sensor definitions for UI
  const sensorDefs = [
    { key: 'motion', name: 'Motion (Accel + Gyro)', icon: '&#x1F4F1;' },
    { key: 'orientation', name: 'Orientation', icon: '&#x1F9ED;' },
    { key: 'geolocation', name: 'Geolocation (GPS)', icon: '&#x1F4CD;' },
    { key: 'touch', name: 'Touch Point', icon: '&#x1F4BB;' },
  ];

  function cacheDom() {
    els.modal = $('connection-modal');
    els.mainUI = $('main-ui');
    els.tdAddress = $('td-address');
    els.btnConnect = $('btn-connect');
    els.connectionStatus = $('connection-status');
    els.connectionLabel = $('connection-label');
    els.connectionError = $('connection-error');
    els.packetRate = $('packet-rate');
    els.sensorPanel = $('sensor-panel');
    els.btnFullscreenTouch = $('btn-fullscreen-touch');
    els.sensorList = $('sensor-list');
    els.btnEnableSensors = $('btn-enable-sensors');
    els.vizContainer = $('viz-container');
    els.vizCanvas = $('viz-canvas');
    els.broadcastStatus = $('broadcast-status');
    els.btnBroadcast = $('btn-broadcast');
    els.btnTrigger = $('btn-trigger');
    els.touchPad = $('touch-pad');
    els.touchCanvas = $('touch-canvas');
    els.btnExitTouch = $('btn-exit-touch');
    els.debugInfo = $('debug-info');
    els.userStartOverlay = $('user-start-overlay');
    els.btnUserStart = $('btn-user-start');
    els.wobLoading = $('wob-loading');
    els.logViewerOverlay = $('log-viewer-overlay');
    els.logViewerContent = $('log-viewer-content');
  }

  function loadSettings() {
    const saved = localStorage.getItem('wob-settings');
    if (saved) {
      try {
        const s = JSON.parse(saved);
        if (s.tdAddress) els.tdAddress.value = s.tdAddress;
        if (s.sensorSelection) {
          for (const [key, val] of Object.entries(s.sensorSelection)) {
            SensorModule.setSensorSelected(key, val);
          }
        }
      } catch (e) { /* ignore */ }
    }
  }

  function saveSettings() {
    localStorage.setItem('wob-settings', JSON.stringify({
      tdAddress: els.tdAddress.value,
      sensorSelection: SensorModule.getSelected(),
    }));
  }

  /**
   * Apply config pushed from TD via {type:'config'} message.
   * wob_config keys: sample_rate, wake_lock, haptic, sensors, dev_mode
   */
  function applyConfig(cfg) {
    if (cfg.sample_rate != null) {
      const rate = parseInt(cfg.sample_rate);
      if (rate > 0 && rate !== sampleRate) {
        sampleRate = rate;
        addLog(`Config: sample_rate=${rate}Hz`, 'info');
        if (broadcasting) { stopBroadcast(); startBroadcast(); }
      }
    }
    if (cfg.wake_lock != null) {
      if (parseInt(cfg.wake_lock)) requestWakeLock();
      else releaseWakeLock();
    }
    if (cfg.haptic != null) {
      hapticEnabled = !!parseInt(cfg.haptic);
    }
    let sensorChanged = false;
    ['motion', 'orientation', 'geolocation', 'touch'].forEach(key => {
      const v = cfg[`sensor_${key}`];
      if (v != null) { SensorModule.setSensorSelected(key, !!parseInt(v)); sensorChanged = true; }
    });
    if (sensorChanged) renderSensorList();
    if (cfg.dev_mode != null) {
      localStorage.setItem('wob-dev-mode', String(cfg.dev_mode));
      applyDevMode(!!parseInt(cfg.dev_mode));
    }
    if (cfg.sensor_camera != null) {
      cameraEnabled = !!parseInt(cfg.sensor_camera);
    }
    if (cfg.sensor_microphone != null) {
      micEnabled = !!parseInt(cfg.sensor_microphone);
      renderSensorList();
    }
    let audioProcChanged = false;
    if (cfg.audio_echo_cancellation != null) {
      const v = !!parseInt(cfg.audio_echo_cancellation);
      if (v !== audioEchoCancellation) { audioEchoCancellation = v; audioProcChanged = true; }
    }
    if (cfg.audio_noise_suppression != null) {
      const v = !!parseInt(cfg.audio_noise_suppression);
      if (v !== audioNoiseSuppression) { audioNoiseSuppression = v; audioProcChanged = true; }
    }
    if (cfg.audio_auto_gain != null) {
      const v = !!parseInt(cfg.audio_auto_gain);
      if (v !== audioAutoGain) { audioAutoGain = v; audioProcChanged = true; }
    }
    if (audioProcChanged && micEnabled && WebRTCModule.isMicActive()) {
      _startWebRTC();
    }
    if (cfg.ice_servers != null) {
      try {
        iceServersFromConfig = typeof cfg.ice_servers === 'string'
          ? JSON.parse(cfg.ice_servers) : cfg.ice_servers;
      } catch (e) { iceServersFromConfig = null; }
    }
    if (cfg.ice_transport_policy != null) {
      iceTransportPolicyFromConfig = cfg.ice_transport_policy === 'relay' ? 'relay' : null;
    }
  }

  function _webrtcStartOpts(opts) {
    const o = { ...opts };
    if (iceServersFromConfig && Array.isArray(iceServersFromConfig) && iceServersFromConfig.length) {
      o.iceServers = iceServersFromConfig;
    }
    if (iceTransportPolicyFromConfig) {
      o.iceTransportPolicy = iceTransportPolicyFromConfig;
    }
    return o;
  }

  // ── Dev Mode ─────────────────────────────────────────────────────────────

  function applyDevMode(on) {
    devMode = on;
    // Config arrived — hide any loading screen that was blocking the UI
    els.wobLoading.classList.add('hidden');

    if (on) {
      // Full UI: show sensor panel, transition out of non-dev touch pad
      if (els.sensorPanel) els.sensorPanel.style.display = '';
      _removeDevOverlay();
      els.userStartOverlay.classList.add('hidden'); // clean up if switching from user mode
      if (touchPadActive) {
        touchPadActive = false;
        els.touchPad.classList.add('hidden');
        els.btnExitTouch.classList.remove('hidden');
        TouchModule.destroy();
      }
      els.mainUI.classList.remove('hidden');
      _initViz();
    } else {
      // Minimal mode: hide main UI entirely, go straight to touch pad
      if (els.sensorPanel) els.sensorPanel.style.display = 'none';
      els.mainUI.classList.add('hidden');
      if (!touchPadActive) _showTouchPadDirectly();
    }
  }

  function _removeDevOverlay() {
    const el = document.getElementById('devmode-overlay');
    if (el) el.remove();
  }

  function _initViz() {
    if (vizInitialized) return;
    vizInitialized = true;
    Visualization.init(els.vizCanvas);
    startVizTouch();
  }

  /**
   * Show touch pad directly without main UI (dev_mode=0).
   * Handles iOS sensor permission via first-touch gesture.
   */
  function _showTouchPadDirectly() {
    touchPadActive = true;
    els.touchPad.classList.remove('hidden');
    els.btnExitTouch.classList.add('hidden'); // no exit in minimal mode
    resizeTouchCanvas();

    const startSensorsAndBroadcast = () => {
      if (!SensorModule.isEnabled()) SensorModule.startListening();
    };

    if (SensorModule.needsPermissionRequest()) {
      // iOS: DeviceMotionEvent.requestPermission() must be in a direct button-click handler.
      // Show a dedicated START button — this is the most reliable iOS gesture trigger.
      els.userStartOverlay.classList.remove('hidden');
      els.btnUserStart.addEventListener('click', async function() {
        els.userStartOverlay.classList.add('hidden');
        await SensorModule.requestPermissions();
        startSensorsAndBroadcast();
      }, { once: true });
    } else {
      startSensorsAndBroadcast();
    }

    TouchModule.init(els.touchCanvas, (snapshot) => {
      Visualization.drawTouches(els.touchCanvas, snapshot.touches, false);
      handleTouchData(snapshot);
    });
  }

  function init() {
    cacheDom();
    addLog('WOB 시작 (protocol: ' + window.location.protocol + ')', 'info');
    // Apply cached dev mode instantly to prevent flash of wrong UI
    const _cached = localStorage.getItem('wob-dev-mode');
    if (_cached !== null) {
      devMode = !!parseInt(_cached);
      if (!devMode && els.sensorPanel) els.sensorPanel.style.display = 'none';
    }
    loadSettings();
    bindEvents();
    initLogViewer();
    if (typeof WebRTCModule !== 'undefined' && WebRTCModule.setOnLog) {
      WebRTCModule.setOnLog((msg) => addLog('WebRTC ' + msg, 'info'));
    }
    renderSensorList();
    SensorModule.setDebugCallback((msg) => updateDebug(msg));

    const td = new URLSearchParams(window.location.search).get('td');
    if (td) {
      addLog('Auto-connect: ' + td, 'info');
      els.tdAddress.value = td;
      history.replaceState(null, '', window.location.pathname);
      handleConnect(true); // autoConnect=true → use loading screen on first QR-scan
    } else {
      addLog('No ?td= param - enter address manually', 'warn');
    }
  }

  function showLogViewer() {
    if (els.logViewerOverlay) {
      els.logViewerOverlay.classList.remove('hidden');
      _renderLog();
    }
  }
  function hideLogViewer() {
    if (els.logViewerOverlay) els.logViewerOverlay.classList.add('hidden');
  }
  function initLogViewer() {
    const overlay = els.logViewerOverlay;
    const box = document.getElementById('log-viewer-box');
    if (overlay) {
      overlay.addEventListener('click', (e) => { if (e.target === overlay) hideLogViewer(); });
      if (box) box.addEventListener('click', (e) => e.stopPropagation());
    }
  }

  function bindEvents() {
    els.btnConnect.addEventListener('click', handleConnect);
    if (els.btnShowLog = $('btn-show-log')) els.btnShowLog.addEventListener('click', showLogViewer);
    if (els.btnShowLogTop = $('btn-show-log-top')) els.btnShowLogTop.addEventListener('click', showLogViewer);
    if (els.btnCloseLog = $('btn-close-log')) els.btnCloseLog.addEventListener('click', hideLogViewer);
    els.btnEnableSensors.addEventListener('click', handleEnableSensors);
    els.btnFullscreenTouch.addEventListener('click', enterTouchPad);
    els.btnExitTouch.addEventListener('click', exitTouchPad);
    els.btnBroadcast.addEventListener('click', toggleBroadcast);
    els.btnTrigger.addEventListener('pointerdown', () => els.btnTrigger.classList.add('triggered'));
    els.btnTrigger.addEventListener('pointerup', sendTrigger);
    els.btnTrigger.addEventListener('pointercancel', () => els.btnTrigger.classList.remove('triggered'));
    // WebRTC state changes → re-render sensor list to reflect mic state
    WebRTCModule.onStateChange((state) => {
      renderSensorList();
      addLog('WebRTC: ' + state, state === 'connected' ? 'info' : state === 'failed' ? 'error' : 'warn');
    });

    setInterval(updatePacketRate, 1000);
  }

  function renderSensorList() {
    const avail = SensorModule.detect();
    const selected = SensorModule.getSelected();

    els.sensorList.innerHTML = '';
    sensorDefs.forEach((s) => {
      const li = document.createElement('li');
      const isAvailable = avail[s.key];
      const isSelected = selected[s.key];

      if (!isAvailable) {
        li.className = 'unavailable';
      } else if (isSelected) {
        li.className = 'available selected';
      } else {
        li.className = 'available deselected';
      }

      li.innerHTML = `<span class="sensor-icon">${s.icon}</span> ${s.name}`;

      if (isAvailable) {
        li.addEventListener('click', () => {
          SensorModule.toggleSensor(s.key);
          haptic(15);
          renderSensorList();
          saveSettings();
        });
      }

      els.sensorList.appendChild(li);
    });

    // Camera item — Pro license required, always shown as unavailable
    {
      const li = document.createElement('li');
      li.className = 'unavailable';
      li.innerHTML = `<span class="sensor-icon">&#x1F4F7;</span> Camera <small>(Pro)</small>`;
      els.sensorList.appendChild(li);
    }

    // Mic item — toggleable via WebRTC
    {
      const li = document.createElement('li');
      const micAvail = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
      if (!micAvail) {
        li.className = 'unavailable';
      } else if (micEnabled) {
        li.className = 'available selected' + (WebRTCModule.isMicActive() ? ' rtc-connected' : '');
      } else {
        li.className = 'available deselected';
      }
      li.innerHTML = `<span class="sensor-icon">&#x1F3A4;</span> Microphone`;
      if (micAvail) {
        li.addEventListener('click', async () => {
          await handleMicToggle();
        });
      }
      els.sensorList.appendChild(li);
    }
  }

  function handleConnect(autoConnect = false) {
    const addr = els.tdAddress.value.trim();
    if (!addr) {
      alert('TouchDesigner 주소를 입력하세요.');
      return;
    }

    saveSettings();
    haptic();

    addLog('Connecting to: ' + addr, 'info');
    const wsUrl = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + addr.replace(/^(wss?|https?):\/\//, '');
    addLog('WebSocket URL: ' + wsUrl, 'info');
    WSClient.connect(addr, {
      onStatusChange: (status) => {
        updateConnectionStatus(status);
        addLog('WS status: ' + status, status === 'connected' ? 'info' : status === 'error' ? 'error' : 'warn');
        if (status === 'connected') {
          WSClient.send({ type: 'hello' });
          addLog('Hello sent to TD', 'info');
          if (!SensorModule.isEnabled() && devMode) {
            addLog('Enable Sensors 후 Start Broadcast를 눌러 전송 시작', 'warn');
          }
        }
        // If connection fails while loading screen is up, fall back to modal
        if ((status === 'error' || status === 'rejected' || status === 'disconnected') &&
            !els.wobLoading.classList.contains('hidden')) {
          els.wobLoading.classList.add('hidden');
          els.modal.classList.add('active');
        }
      },
      onErrorDetail: (msg) => {
        updateConnectionError(msg);
        if (msg) addLog(msg, 'error');
      },
      onConfig: (cfg) => applyConfig(cfg),
      onWebRTCSignal: (msg) => {
        if (msg.type === 'webrtc_answer') WebRTCModule.handleAnswer(msg.sdp);
        else if (msg.type === 'webrtc_ice') WebRTCModule.handleIce(msg);
      },
    });

    els.modal.classList.remove('active');
    resizeTouchCanvas();
    window.addEventListener('resize', resizeTouchCanvas);

    // On first QR-scan (no cached devMode), we don't know user vs dev mode yet.
    // Show a loading screen so config can arrive before any UI is shown — prevents flash.
    const hasCachedMode = localStorage.getItem('wob-dev-mode') !== null;
    if (autoConnect && !hasCachedMode) {
      els.wobLoading.classList.remove('hidden'); // applyDevMode() will hide it
    } else if (devMode) {
      // Full UI: show main interface + initialize visualization
      els.mainUI.classList.remove('hidden');
      _initViz();
    } else {
      // Minimal mode: skip main UI, go straight to touch pad
      _showTouchPadDirectly();
    }

    requestWakeLock(); // default on; TD can override via config
  }

  function handleDisconnect() {
    stopBroadcast();
    stopVizTouch();
    SensorModule.stopListening();
    WSClient.disconnect();
    releaseWakeLock();
    touchPadActive = false;
    vizInitialized = false;
    els.touchPad.classList.add('hidden');
    els.btnExitTouch.classList.remove('hidden');
    els.userStartOverlay.classList.add('hidden');
    els.wobLoading.classList.add('hidden');
    els.mainUI.classList.add('hidden');
    els.modal.classList.add('active');
  }

  async function handleEnableSensors() {
    haptic();

    if (SensorModule.isEnabled()) {
      SensorModule.stopListening();
      if (WebRTCModule.isMicActive()) await WebRTCModule.stop();
      els.btnEnableSensors.textContent = 'Enable Sensors';
      els.btnEnableSensors.classList.remove('btn-active');
      updateDebug('Sensors deactivated');
      renderSensorList();
      return;
    }

    if (SensorModule.needsPermissionRequest()) {
      if (!window.isSecureContext) {
        updateDebug('iOS 센서 권한은 HTTPS 필요.');
        return;
      }
      updateDebug('Requesting permissions...');
      const perms = await SensorModule.requestPermissions();
      updateDebug('Permissions: ' + JSON.stringify(perms));
    } else {
      updateDebug('No permission request needed (non-iOS)');
    }

    SensorModule.startListening();

    if (WSClient.isConnected() && micEnabled && !WebRTCModule.isMicActive()) {
      if (_isTunnelConnection()) {
        showToast('Warning: Mic over tunnel may fail. Cross-network requires a TURN server.', 4500);
      }
      const ok = await WebRTCModule.start(_webrtcStartOpts({
        camera: cameraEnabled, mic: micEnabled,
        echoCancellation: audioEchoCancellation,
        noiseSuppression: audioNoiseSuppression,
        autoGainControl: audioAutoGain,
      }));
      if (ok === false) {
        micEnabled = false;
        const err = WebRTCModule.getLastError();
        if (err === 'NotAllowedError' || err === 'PermissionDeniedError') {
          showToast('Mic permission denied — allow microphone in browser settings');
          addLog('마이크 권한 거부됨 — 브라우저 설정에서 허용해주세요', 'error');
        } else if (err === 'NotFoundError') {
          showToast('Microphone not found');
        } else {
          showToast('Mic activation failed');
        }
      }
    }

    if (SensorModule.isSimulating()) {
      els.btnEnableSensors.textContent = 'Deactivate (Simulating)';
    } else {
      els.btnEnableSensors.textContent = 'Deactivate Sensors';
    }
    els.btnEnableSensors.classList.add('btn-active');

    startVizLoop();
    renderSensorList();
  }

  let vizLoopId = null;
  function startVizLoop() {
    if (vizLoopId) return;
    function loop() {
      const data = SensorModule.getData();
      if (WebRTCModule.isMicActive()) data.micLevel = WebRTCModule.getMicLevel();
      Visualization.update(data);
      vizLoopId = requestAnimationFrame(loop);
    }
    loop();
  }

  function toggleBroadcast() {
    if (broadcasting) stopBroadcast();
    else startBroadcast();
  }

  function showBroadcastStatus(msg, isError) {
    if (!els.broadcastStatus) return;
    els.broadcastStatus.textContent = msg;
    els.broadcastStatus.className = 'broadcast-status' + (isError ? ' error' : '');
  }

  function startBroadcast() {
    if (!WSClient.isConnected()) {
      const msg = '1. TouchDesigner에 연결하세요 (Connect to TD)';
      showBroadcastStatus(msg, true);
      return;
    }
    if (!SensorModule.isEnabled()) {
      const msg = '2. 먼저 [Enable Sensors] 버튼을 눌러 센서를 활성화하세요';
      showBroadcastStatus(msg, true);
      return;
    }

    showBroadcastStatus('', false);
    haptic();
    broadcasting = true;
    els.btnBroadcast.textContent = 'Stop Broadcast';
    els.btnBroadcast.classList.add('broadcasting');
    if (els.packetRate) els.packetRate.classList.add('broadcasting');
    updateDebug('Broadcasting... ' + sampleRate + ' Hz');

    const interval = Math.round(1000 / sampleRate);
    broadcastInterval = setInterval(() => {
      WSClient.sendSensorData(SensorModule.getData());
    }, interval);
  }

  function stopBroadcast() {
    broadcasting = false;
    if (broadcastInterval) {
      clearInterval(broadcastInterval);
      broadcastInterval = null;
    }
    els.btnBroadcast.textContent = 'Start Broadcast';
    els.btnBroadcast.classList.remove('broadcasting');
    if (els.packetRate) els.packetRate.classList.remove('broadcasting');
    showBroadcastStatus('', false);
    updateDebug('Broadcast 중지됨');
  }

  function sendTrigger() {
    els.btnTrigger.classList.remove('triggered');
    if (!WSClient.isConnected()) return;
    WSClient.send({ type: 'trigger' });
    haptic(50);
  }

  function handleTouchData(snapshot) {
    if (broadcasting && WSClient.isConnected() && SensorModule.getSelected().touch) {
      WSClient.sendTouchData(snapshot);
    }
  }

  function startVizTouch() {
    if (!els.vizContainer) return;
    TouchModule.init(els.vizContainer, (snapshot) => {
      handleTouchData(snapshot);
    });
  }

  function stopVizTouch() {
    TouchModule.destroy();
  }

  function enterTouchPad() {
    touchPadActive = true;
    stopVizTouch();
    els.touchPad.classList.remove('hidden');
    els.btnExitTouch.classList.remove('hidden'); // always visible in dev_mode=1
    resizeTouchCanvas();

    TouchModule.init(els.touchCanvas, (snapshot) => {
      Visualization.drawTouches(els.touchCanvas, snapshot.touches, devMode);
      handleTouchData(snapshot);
    });
    haptic();
  }

  function exitTouchPad() {
    touchPadActive = false;
    els.touchPad.classList.add('hidden');
    TouchModule.destroy();
    startVizTouch();
    haptic();
  }

  function resizeTouchCanvas() {
    if (!els.touchCanvas) return;
    const dpr = window.devicePixelRatio || 1;
    els.touchCanvas.width = window.innerWidth * dpr;
    els.touchCanvas.height = window.innerHeight * dpr;
    els.touchCanvas.style.width = window.innerWidth + 'px';
    els.touchCanvas.style.height = window.innerHeight + 'px';
  }

  function updateConnectionStatus(status) {
    const dot = els.connectionStatus;
    const label = els.connectionLabel;
    dot.className = 'status-dot ' + status;
    const labels = {
      connected: 'Connected to TD',
      disconnected: 'Disconnected',
      connecting: 'Connecting...',
      reconnecting: 'Reconnecting...',
      error: 'Connection Error',
      rejected: 'Server Full',
    };
    label.textContent = labels[status] || status;
    if (status === 'rejected') {
      _showRejectedOverlay();
    }
    if (status !== 'error' && status !== 'rejected' && els.connectionError) {
      els.connectionError.textContent = '';
      els.connectionError.classList.add('hidden');
    }
  }

  function _showRejectedOverlay() {
    let overlay = document.getElementById('rejected-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'rejected-overlay';
      overlay.innerHTML = `
        <div class="rejected-box">
          <div class="rejected-icon">&#x1F6AB;</div>
          <h2>연결이 가득 찼어요</h2>
          <p>현재 최대 접속 인원이 모두 사용 중입니다.<br>잠시 후 다시 시도해 주세요.</p>
          <button id="btn-retry" class="btn btn-primary" style="margin-top:20px">다시 시도</button>
        </div>`;
      document.body.appendChild(overlay);
      overlay.querySelector('#btn-retry').addEventListener('click', () => {
        overlay.remove();
        handleConnect();
      });
    }
  }

  function updateConnectionError(msg) {
    if (!els.connectionError) return;
    if (msg) {
      els.connectionError.textContent = msg;
      els.connectionError.classList.remove('hidden');
    } else {
      els.connectionError.textContent = '';
      els.connectionError.classList.add('hidden');
    }
  }

  function updatePacketRate() {
    if (els.packetRate) {
      els.packetRate.textContent = WSClient.getPacketsPerSec() + ' pkt/s';
    }
  }

  const LOG_MAX = 30;
  const logLines = [];

  function addLog(msg, level) {
    const time = new Date().toTimeString().slice(0, 8);
    const line = { time, msg, level: level || 'info' };
    logLines.push(line);
    if (logLines.length > LOG_MAX) logLines.shift();
    _renderLog();
    console.log('[WOB]', msg);
  }

  function _renderLog() {
    const html = logLines.slice().reverse().map(l => {
      const color = l.level === 'error' ? '#ff6677' : l.level === 'warn' ? '#ffaa33' : '#6a9f6a';
      return `<span style="color:${color}">[${l.time}] ${_esc(l.msg)}</span>`;
    }).join('\n');
    if (els.debugInfo) els.debugInfo.innerHTML = html;
    if (els.logViewerContent && !els.logViewerOverlay.classList.contains('hidden')) {
      els.logViewerContent.innerHTML = html;
    }
  }

  function _esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
  }

  function showToast(msg, duration = 2800) {
    let el = document.getElementById('wob-toast');
    if (el) el.remove();
    el = document.createElement('div');
    el.id = 'wob-toast';
    el.className = 'wob-toast';
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => {
      if (el.parentNode) el.remove();
    }, duration);
  }

  function updateDebug(msg) {
    addLog(msg, 'info');
  }

  async function requestWakeLock() {
    if ('wakeLock' in navigator) {
      try {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => console.log('Wake Lock released'));
      } catch (e) {
        console.warn('Wake Lock failed:', e);
      }
    }
  }

  function releaseWakeLock() {
    if (wakeLock) { wakeLock.release(); wakeLock = null; }
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && wakeLock === null) {
      requestWakeLock();
    }
  });

  function haptic(duration = 30) {
    if (hapticEnabled && navigator.vibrate) {
      navigator.vibrate(duration);
    }
  }

  // ── WebRTC ──────────────────────────────────────────────────────────────

  async function _startWebRTC() {
    if (!WSClient.isConnected()) return;
    const ok = await WebRTCModule.start(_webrtcStartOpts({ camera: cameraEnabled, mic: micEnabled }));
    if (ok === false && micEnabled) {
      const err = WebRTCModule.getLastError();
      let msg = '마이크 활성화 실패';
      if (err === 'NotAllowedError' || err === 'PermissionDeniedError') msg = '마이크 권한 거부';
      else if (err === 'NotFoundError') msg = '마이크를 찾을 수 없습니다';
      showToast(msg);
    }
  }

  async function handleCameraToggle() {
    haptic();
    if (WebRTCModule.isCameraActive()) {
      await WebRTCModule.stop();
      cameraEnabled = false;
    } else {
      cameraEnabled = true;
      await WebRTCModule.start(_webrtcStartOpts({
        camera: true, mic: micEnabled,
        echoCancellation: audioEchoCancellation,
        noiseSuppression: audioNoiseSuppression,
        autoGainControl: audioAutoGain,
      }));
    }
    renderSensorList();
  }

  async function handleMicToggle() {
    haptic();
    // Toggle direction based on micEnabled (user intent), not isMicActive() (stream state).
    // Using isMicActive() causes wrong direction when config auto-start failed (micEnabled=true but no stream).
    if (micEnabled) {
      micEnabled = false;
      if (WebRTCModule.isMicActive()) await WebRTCModule.stop();
      renderSensorList();
      return;
    }
    // Enable path: 선택만 변경. WebRTC는 Enable Sensors 시에만 시작 (권한 팝업은 그때만)
    micEnabled = true;
    renderSensorList();

    if (SensorModule.isEnabled() && WSClient.isConnected() && !WebRTCModule.isMicActive()) {
      if (_isTunnelConnection()) {
        showToast('Warning: Mic over tunnel may fail. Cross-network requires a TURN server.', 4500);
      }
      const ok = await WebRTCModule.start(_webrtcStartOpts({
        camera: cameraEnabled, mic: true,
        echoCancellation: audioEchoCancellation,
        noiseSuppression: audioNoiseSuppression,
        autoGainControl: audioAutoGain,
      }));
      if (ok === false) {
        micEnabled = false;
        const err = WebRTCModule.getLastError();
        let toastMsg = 'Mic activation failed';
        if (err === 'NotAllowedError' || err === 'PermissionDeniedError') {
          toastMsg = 'Mic permission denied — allow microphone in browser settings';
          addLog('마이크 권한 거부됨 — 브라우저 설정에서 허용해주세요', 'error');
        } else if (err === 'NotFoundError') {
          toastMsg = 'Microphone not found';
          addLog('마이크를 찾을 수 없습니다 (장치 없음)', 'error');
        } else {
          addLog('마이크 시작 실패: ' + (err || 'unknown'), 'error');
        }
        showToast(toastMsg);
        renderSensorList();
      }
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
