/**
 * W2TD Main App Controller
 * Direct WebSocket connection to TouchDesigner.
 * Settings (sample rate, wake lock, haptic) are pushed from TD via config message.
 */
const W2TD_VERSION = '1.0.0';

(() => {
  let broadcasting = false;
  let sampleRate = 30;
  let broadcastInterval = null;
  let wakeLock = null;
  let touchPadActive = false;
  let hapticEnabled = true;
  let bgColorEnabled = true;
  let flashlightEnabled = true;
  let hapticFeedbackEnabled = true;
  let audioTxEnabled = true;
  let videoTxEnabled = true;
  let devMode = true; // true = full UI, false = minimal/auto mode
  let vizInitialized = false;
  let cameraFrontEnabled = false;
  let cameraRearEnabled = false;
  let micEnabled = false;
  let audioEchoCancellation = false;  // config: 0=raw, 1=on
  let audioNoiseSuppression = false;
  let audioAutoGain = false;
  let iceServersFromConfig = null;   // from w2td_config ice_servers (JSON)
  let iceTransportPolicyFromConfig = null;  // 'relay' | 'all' | null
  let showTouchPoints = true;
  // Display mode gate (w2td_config → videoout): 'none'=disabled, 'color'=bg color, 'td'=TD video, 'js'=JS sketch.
  // Default null = not configured yet — don't gate anything until TD explicitly sets a mode.
  let displayMode = null;
  let canvasTopbarVisible = true;
  let cachedCanvasCode = '';
  let lastBgColor = localStorage.getItem('w2td-last-bg-color') || '';  // color 모드 즉시 적용용
  let _tdVideoElUser = null;  // dev_mode=0에서 생성된 fullscreen 비디오 엘리먼트 참조
  let _devFullscreenMode = null; // dev_mode=1 전용: 현재 수동 진입한 전체화면 모드 ('td'/'js'/'color'/null)

  function _isTunnelConnection() {
    const addr = (els.tdAddress && els.tdAddress.value || '').toLowerCase();
    // Short tunnel ID (no dot) is also a tunnel connection
    const noProt = addr.replace(/^(wss?|https?):\/\//, '');
    return !noProt.includes('.') || addr.includes('trycloudflare.com') || addr.includes('cloudflare') || addr.includes('.cfargotunnel.com');
  }

  const $ = (id) => document.getElementById(id);
  const els = {};

  // Sensor definitions for UI
  const sensorDefs = [
    { key: 'motion', name: 'Motion', icon: '&#x1F4F1;' },
    { key: 'orientation', name: 'Orientation', icon: '&#x1F9ED;' },
    { key: 'geolocation', name: 'GPS', icon: '&#x1F4CD;' },
    { key: 'touch', name: 'Touch Point', icon: '&#x1F4BB;' },
  ];

  function cacheDom() {
    els.modal = $('connection-modal');
    els.mainUI = $('main-ui');
    els.tdAddress = $('td-address');
    els.clientName = $('client-name');
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
    els.touchPad = $('touch-pad');
    els.touchCanvas = $('touch-canvas');
    els.btnExitTouch = $('btn-exit-touch');
    els.btnToggleTouchPoints = $('btn-toggle-touch-points');
    els.debugInfo = $('debug-info');
    els.userStartOverlay = $('user-start-overlay');
    els.btnUserStart = $('btn-user-start');
    els.w2tdLoading = $('w2td-loading');
    els.logViewerOverlay = $('log-viewer-overlay');
    els.logViewerContent = $('log-viewer-content');
    els.btnCameraMonitor = $('btn-camera-monitor');
    els.cameraMonitor = $('camera-monitor');
    els.btnExitCameraMonitor = $('btn-exit-camera-monitor');
    els.camResStatus = $('cam-res-status');
    els.btnTdStream = $('btn-td-stream');
    els.tdStreamMonitor = $('td-stream-monitor');
    els.btnExitTdStream = $('btn-exit-td-stream');
    els.tdStreamVideoArea = els.tdStreamMonitor ? els.tdStreamMonitor.querySelector('.td-stream-video-area') : null;
  }

  function _detectDeviceName() {
    const ua = navigator.userAgent;
    if (/iPad/.test(ua)) return 'iPad';
    if (/iPhone/.test(ua)) return 'iPhone';
    if (/iPod/.test(ua)) return 'iPod';
    const androidModel = ua.match(/Android [^;]+;\s*([^)]+)\)/);
    if (androidModel) return androidModel[1].trim().replace(/\s+Build.*$/, '');
    if (/Android/.test(ua)) return 'Android';
    return '';
  }

  function loadSettings() {
    const saved = localStorage.getItem('w2td-settings');
    if (saved) {
      try {
        const s = JSON.parse(saved);
        if (s.tdAddress) els.tdAddress.value = s.tdAddress;
        if (s.clientName && els.clientName) els.clientName.value = s.clientName;
        if (s.sensorSelection) {
          for (const [key, val] of Object.entries(s.sensorSelection)) {
            SensorModule.setSensorSelected(key, val);
          }
        }
        if (s.showTouchPoints !== undefined) {
          showTouchPoints = s.showTouchPoints;
        }
      } catch (e) { /* ignore */ }
    }
    // Auto-populate device name if empty
    if (els.clientName && !els.clientName.value) {
      els.clientName.value = _detectDeviceName();
    }
  }

  function saveSettings() {
    localStorage.setItem('w2td-settings', JSON.stringify({
      tdAddress: els.tdAddress.value,
      clientName: els.clientName ? els.clientName.value : '',
      sensorSelection: SensorModule.getSelected(),
      showTouchPoints: showTouchPoints,
    }));
  }

  /**
   * Apply config pushed from TD via {type:'config'} message.
   * w2td_config keys: sample_rate, wake_lock, haptic, sensors, dev_mode
   */
  function applyConfig(cfg) {
    if (cfg.sample_rate != null) {
      const rate = parseInt(cfg.sample_rate);
      if (rate > 0 && rate !== sampleRate) {
        sampleRate = rate;
        addLog(`Config: sample_rate=${rate}Hz`, 'info');
        if (broadcasting) { stopBroadcast(); _startDataBroadcast(); }
      }
    }
    if (cfg.wake_lock != null) {
      if (parseInt(cfg.wake_lock)) requestWakeLock();
      else releaseWakeLock();
    }
    if (cfg.haptic != null) {
      hapticEnabled = !!parseInt(cfg.haptic);
    }
    if (cfg.hapticfeedback != null) hapticFeedbackEnabled = !!parseInt(cfg.hapticfeedback);
    if (cfg.backgroundcolor != null) bgColorEnabled = !!parseInt(cfg.backgroundcolor);
    if (cfg.flashlight != null) flashlightEnabled = !!parseInt(cfg.flashlight);
    if (cfg.audio_tx != null) audioTxEnabled = !!parseInt(cfg.audio_tx);
    if (cfg.video_tx != null) videoTxEnabled = !!parseInt(cfg.video_tx);
    let sensorChanged = false;
    ['motion', 'orientation', 'geolocation', 'touch'].forEach(key => {
      const v = cfg[`sensor_${key}`];
      if (v != null) { SensorModule.setSensorSelected(key, !!parseInt(v)); sensorChanged = true; }
    });
    if (sensorChanged) renderSensorList();
    if (cfg.dev_mode != null) {
      localStorage.setItem('w2td-dev-mode', String(cfg.dev_mode));
      applyDevMode(!!parseInt(cfg.dev_mode));
    }
    if (cfg.sensor_rear_camera != null) {
      const on = !!parseInt(cfg.sensor_rear_camera);
      if (!on && cameraRearEnabled) {
        cameraRearEnabled = false;
        WebRTCModule.stopCameraRear();
      } else if (on && !cameraRearEnabled) {
        cameraRearEnabled = true;
      }
      renderSensorList();
    }
    if (cfg.sensor_front_camera != null) {
      const on = !!parseInt(cfg.sensor_front_camera);
      if (!on && cameraFrontEnabled) {
        cameraFrontEnabled = false;
        WebRTCModule.stopCameraFront();
      } else if (on && !cameraFrontEnabled) {
        cameraFrontEnabled = true;
      }
      renderSensorList();
    }
    if (cfg.sensor_microphone != null) {
      const micOn = !!parseInt(cfg.sensor_microphone);
      const wasOn = micEnabled;
      micEnabled = micOn;
      if (wasOn && !micOn && WebRTCModule.isMicActive()) {
        WebRTCModule.stop();
      }
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
    if (cfg.show_dots != null) {
      showTouchPoints = !!parseInt(cfg.show_dots);
      updateTouchPointsToggleUI();
    }
    if (cfg.cam_resolution != null) {
      WebRTCModule.setResolution(cfg.cam_resolution);
      _updateCamResolutionUI();
    }
    if (cfg.canvas_topbar != null) {
      canvasTopbarVisible = !!parseInt(cfg.canvas_topbar);
      _applyCanvasTopbarVisibility();
    }
    if (cfg.videoout != null) {
      const next = String(cfg.videoout);
      if (next !== displayMode) {
        displayMode = next;
        addLog(`Config: videoout=${next}`, 'info');
        _applyDisplayMode();
      }
    }
  }

  /**
   * Enforce videoout on current UI. Gates bg_color, canvas sketch, TD video
   * as a mutually exclusive layer switch.
   *   'none'  = disabled   → stop sketch, close TD stream monitor
   *   'color' = bg color   → stop sketch, close TD stream monitor
   *   'td'    = TD video   → stop sketch, reset body bg
   *   'js'    = JS canvas  → reset body bg, close TD stream, run cached sketch
   */
  function _applyDisplayMode() {
    const isTd    = displayMode === 'td';
    const isColor = displayMode === 'color';
    const isJs    = displayMode === 'js';
    // 'color', 'td', 'js' 모드 = 전체화면 표시 모드 → mainUI 숨김
    const isDisplayMode = isTd || isColor || isJs;

    // ── dev_mode=1: 자동 전체화면 전환 없음. mainUI 유지, Fullscreen 버튼만 표시 ──
    if (devMode) {
      if (!isDisplayMode) {
        // 'none' 모드 복귀: 활성 전체화면 있으면 종료
        if (_devFullscreenMode) _exitDevFullscreen();
        else if (els.mainUI) els.mainUI.classList.remove('hidden');
      }
      // JS 캔버스: 로드는 하되 자동 전체화면 전환은 하지 않음
      if (!isJs) {
        if (typeof CanvasRunner !== 'undefined') CanvasRunner.stop();
      } else if (cachedCanvasCode && typeof CanvasRunner !== 'undefined') {
        CanvasRunner.load(cachedCanvasCode);
      }
      if (!isTd && _tdVideoElUser) _tdVideoElUser.style.display = 'none';
      _applyCanvasTopbarVisibility();
      _updateFullscreenButtonVisibility();
      return;
    }

    // ── dev_mode=0: 기존 자동 전환 동작 ─────────────────────────────────

    // ── 배경색 처리 ────────────────────────────────────────────────────────
    if (isColor) {
      // color 모드 진입: 저장된 색상 즉시 적용 (없으면 검은색 기본값)
      const colorToApply = lastBgColor || '#000000';
      document.body.style.backgroundColor = colorToApply;
      const tp = $('touch-pad');
      if (tp) tp.style.backgroundColor = colorToApply;
    } else if (!isTd) {
      // td 모드가 아닌 경우 body 배경 초기화 (td 모드일 때는 video가 덮으므로 유지)
      document.body.style.backgroundColor = '';
      const tp = $('touch-pad');
      if (tp) tp.style.backgroundColor = '';
    }

    // ── TD 영상 element 정리 ───────────────────────────────────────────────
    if (!isTd && _tdVideoElUser) {
      _tdVideoElUser.style.display = 'none';
    }

    // ── JS 캔버스 ──────────────────────────────────────────────────────────
    if (!isJs) {
      if (typeof CanvasRunner !== 'undefined') CanvasRunner.stop();
    } else if (cachedCanvasCode && typeof CanvasRunner !== 'undefined') {
      CanvasRunner.load(cachedCanvasCode);
    }

    // ── mainUI 표시/숨김 ──────────────────────────────────────────────────
    if (els.mainUI) {
      if (isDisplayMode) {
        els.mainUI.classList.add('hidden');
      } else {
        els.mainUI.classList.remove('hidden');
      }
    }

    // ── TD 스트림 모니터 (dev_mode=0) ─────────────────────────────────────
    if (isTd) {
      if (_tdVideoElUser) _tdVideoElUser.style.display = '';
    } else {
      if (els.tdStreamMonitor && !els.tdStreamMonitor.classList.contains('hidden')) {
        els.tdStreamMonitor.classList.add('hidden');
      }
    }

    _applyCanvasTopbarVisibility();
    _updateFullscreenButtonVisibility();
  }

  function _applyCanvasTopbarVisibility() {
    const hide = (displayMode === 'js') && !canvasTopbarVisible;
    document.body.classList.toggle('hide-topbar-for-sketch', hide);
  }

  function _updateCamResolutionUI() {
    if (!els.camResStatus) return;
    const info = WebRTCModule.getCamResolutionInfo();
    const key = info.key.toUpperCase();
    const tgt = `${info.target.width}x${info.target.height}`;
    const rearTxt = info.actualRear ? `${info.actualRear.width}x${info.actualRear.height}` : '—';
    const frontTxt = info.actualFront ? `${info.actualFront.width}x${info.actualFront.height}` : '—';
    const parts = [`Config: ${key} (target ${tgt})`];
    if (info.actualRear) parts.push(`Rear: ${rearTxt}`);
    if (info.actualFront) parts.push(`Front: ${frontTxt}`);
    els.camResStatus.textContent = parts.join('  |  ');
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
    els.w2tdLoading.classList.add('hidden');

    if (on) {
      // Full UI: show sensor panel, transition out of non-dev touch pad
      if (els.sensorPanel) els.sensorPanel.style.display = '';
      _removeDevOverlay();
      els.userStartOverlay.classList.add('hidden'); // clean up if switching from user mode
      if (touchPadActive) {
        touchPadActive = false;
        els.touchPad.classList.add('hidden');
        els.btnExitTouch.classList.remove('hidden');
        if (els.btnToggleTouchPoints) {
          els.btnToggleTouchPoints.classList.add('hidden');
        }
        _disableTouchLock();
        TouchModule.destroy();
      }
      els.mainUI.classList.remove('hidden');
      _initViz();
      // Sync Enable Sensors button to current sensor/broadcast state
      // (sensors may already be active from user mode)
      if (SensorModule.isEnabled()) {
        els.btnEnableSensors.textContent = SensorModule.isSimulating()
          ? 'Stop (Simulating)' : 'Stop';
        els.btnEnableSensors.classList.add('btn-active');
        startVizLoop();
      }
      renderSensorList();
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
    // btnToggleTouchPoints stays hidden in user mode; visibility controlled by show_dots config
    _enableTouchLock();
    resizeTouchCanvas();

    const startSensorsAndBroadcast = () => {
      if (!SensorModule.isEnabled()) SensorModule.startListening();
      if (WSClient.isConnected()) _startDataBroadcast();
    };

    if (SensorModule.needsPermissionRequest()) {
      // iOS: DeviceMotionEvent.requestPermission() must be in a direct button-click handler.
      // Show a dedicated START button — this is the most reliable iOS gesture trigger.
      els.userStartOverlay.classList.remove('hidden');
      els.btnUserStart.addEventListener('click', async function () {
        els.userStartOverlay.classList.add('hidden');
        // Integrated permission request: sensors + mic + wakeLock
        await requestAllPermissions();
        startSensorsAndBroadcast();
      }, { once: true });
    } else {
      // Non-iOS: request permissions sequentially
      requestAllPermissions().then(() => {
        startSensorsAndBroadcast();
      });
    }

    TouchModule.init(els.touchCanvas, (snapshot) => {
      if (showTouchPoints) {
        Visualization.drawTouches(els.touchCanvas, snapshot.touches, false);
      } else {
        // Clear canvas if touch points are hidden
        const ctx = els.touchCanvas.getContext('2d');
        ctx.clearRect(0, 0, els.touchCanvas.width, els.touchCanvas.height);
      }
      handleTouchData(snapshot);
    });
    updateTouchPointsToggleUI();
  }

  function init() {
    cacheDom();
    addLog('W2TD start v' + W2TD_VERSION + ' (protocol: ' + window.location.protocol + ')', 'info');
    console.log('[W2TD] App version:', W2TD_VERSION);
    // Apply cached dev mode instantly to prevent flash of wrong UI
    const _cached = localStorage.getItem('w2td-dev-mode');
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
    if (els.btnCameraMonitor) els.btnCameraMonitor.addEventListener('click', enterCameraMonitor);
    if (els.btnExitCameraMonitor) els.btnExitCameraMonitor.addEventListener('click', exitCameraMonitor);
    if (els.btnTdStream) els.btnTdStream.addEventListener('click', enterTdStreamMonitor);
    if (els.btnExitTdStream) els.btnExitTdStream.addEventListener('click', exitTdStreamMonitor);
    const btnDevExit = $('btn-dev-fullscreen-exit');
    if (btnDevExit) btnDevExit.addEventListener('click', _exitDevFullscreen);

    // TD video downlink callback — routes display based on devMode
    WebRTCModule.setOnTdVideoTrack((videoEl, track) => {
      if (devMode) {
        // dev_mode=1: show TD Stream button and put video in monitor overlay
        videoEl.style.position = '';
        videoEl.style.zIndex = '0';
        videoEl.style.pointerEvents = '';
        videoEl.style.objectFit = 'cover';
        videoEl.style.width = '100%';
        videoEl.style.height = '100%';
        if (els.tdStreamVideoArea && !els.tdStreamVideoArea.contains(videoEl)) {
          els.tdStreamVideoArea.appendChild(videoEl);
        }
        if (els.btnTdStream) {
          els.btnTdStream.classList.add('td-stream-active');
        }
        _updateFullscreenButtonVisibility();
        addLog('TD video stream received — tap "Fullscreen" to view', 'info');
        // Auto-open the stream monitor if the user has already selected videoout=td
        if (displayMode === 'td' && els.tdStreamMonitor && els.mainUI) {
          els.mainUI.classList.add('hidden');
          els.tdStreamMonitor.classList.remove('hidden');
        }
      } else {
        // dev_mode=0: show as full-screen background behind touch-pad
        videoEl.style.position = 'fixed';
        videoEl.style.top = '0';
        videoEl.style.left = '0';
        videoEl.style.width = '100%';
        videoEl.style.height = '100%';
        videoEl.style.objectFit = 'cover';
        videoEl.style.zIndex = '501';
        videoEl.style.pointerEvents = 'none';
        videoEl.style.display = displayMode === 'td' ? '' : 'none'; // hide if mode already changed
        if (!document.body.contains(videoEl)) document.body.appendChild(videoEl);
        _tdVideoElUser = videoEl;  // track for cleanup on mode change
        if (displayMode === 'td') {
          const tp = document.getElementById('touch-pad');
          if (tp) tp.style.backgroundColor = 'transparent';
          document.body.style.backgroundColor = 'transparent';
        }
      }
      track.onended = () => {
        videoEl.srcObject = null;
        if (devMode) {
          if (els.btnTdStream) {
            els.btnTdStream.classList.remove('td-stream-active');
          }
          _updateFullscreenButtonVisibility();
          // td 모드일 때만 모니터 종료 처리 (다른 모드로 이미 전환된 경우 스킵)
          if (displayMode === 'td') exitTdStreamMonitor();
        } else {
          videoEl.style.display = 'none';
          // td 모드에서 이탈한 경우에만 배경 초기화 (다른 모드로 전환 후 트랙 종료 시 무시)
          if (displayMode === 'td') {
            document.body.style.backgroundColor = '';
            const tp2 = document.getElementById('touch-pad');
            if (tp2) tp2.style.backgroundColor = '';
          }
        }
      };
    });
    if (els.btnToggleTouchPoints) {
      els.btnToggleTouchPoints.addEventListener('click', toggleTouchPoints);
    }
    // Mic state changes → re-render sensor list
    WebRTCModule.onStateChange((state) => {
      renderSensorList();
      addLog('WebRTC mic: ' + state, state === 'connected' ? 'info' : state === 'failed' ? 'error' : 'warn');
    });
    // Camera state changes → re-render sensor list
    WebRTCModule.onCamStateChange((state) => {
      renderSensorList();
      addLog('WebRTC cam: ' + state, state === 'connected' ? 'info' : state === 'failed' ? 'error' : 'warn');
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

    // Rear Camera
    {
      const li = document.createElement('li');
      const camAvail = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
      if (!camAvail) li.className = 'unavailable';
      else if (cameraRearEnabled) li.className = 'available selected' + (WebRTCModule.isCameraRearActive() ? ' rtc-connected' : '');
      else li.className = 'available deselected';
      li.innerHTML = `<span class="sensor-icon">&#x1F4F7;</span> Rear`;
      if (camAvail) li.addEventListener('click', () => handleRearCameraToggle());
      els.sensorList.appendChild(li);
    }
    // Front Camera (selfie)
    {
      const li = document.createElement('li');
      const camAvail = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
      if (!camAvail) li.className = 'unavailable';
      else if (cameraFrontEnabled) li.className = 'available selected' + (WebRTCModule.isCameraFrontActive() ? ' rtc-connected' : '');
      else li.className = 'available deselected';
      li.innerHTML = `<span class="sensor-icon">&#x1F4F9;</span> Front`;
      if (camAvail) li.addEventListener('click', () => handleFrontCameraToggle());
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
    let addr = els.tdAddress.value.trim();
    if (!addr) {
      alert('Please enter the TouchDesigner address.');
      return;
    }

    // Auto-append .trycloudflare.com if address has no dot (short tunnel ID)
    const addrNoProt = addr.replace(/^(wss?|https?):\/\//, '');
    if (!addrNoProt.includes('.')) {
      addr = addrNoProt + '.trycloudflare.com';
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
          if (SensorModule.isEnabled() && WSClient.isConnected()) {
            _startDataBroadcast();
          }
          // Send client name if provided
          const clientName = els.clientName ? els.clientName.value.trim() : '';
          if (clientName) {
            WSClient.send({ type: 'client_name', name: clientName });
            addLog(`Client name sent: ${clientName}`, 'info');
          }

          // Send screen resolution info
          // CSS pixel dimensions (viewport size)
          const cssWidth = window.innerWidth;
          const cssHeight = window.innerHeight;
          const devicePixelRatio = window.devicePixelRatio || 1.0;

          // Physical pixel dimensions (actual screen resolution)
          const physicalWidth = Math.round(cssWidth * devicePixelRatio);
          const physicalHeight = Math.round(cssHeight * devicePixelRatio);

          // Screen dimensions (device screen size)
          const screenWidth = window.screen.width;
          const screenHeight = window.screen.height;

          const screenInfo = {
            type: 'screen_info',
            // CSS viewport size (web-optimized resolution)
            width: cssWidth,
            height: cssHeight,
            // Physical pixel resolution
            physicalWidth: physicalWidth,
            physicalHeight: physicalHeight,
            // Device screen size
            screenWidth: screenWidth,
            screenHeight: screenHeight,
            devicePixelRatio: devicePixelRatio
          };
          WSClient.send(screenInfo);
          addLog(`Screen info sent: ${cssWidth}x${cssHeight} CSS (${physicalWidth}x${physicalHeight} physical, DPR: ${devicePixelRatio})`, 'info');

          if (!SensorModule.isEnabled() && devMode) {
            addLog('Press Enable Sensors to start broadcasting', 'warn');
          }
        }
        // If connection fails while loading screen is up, fall back to modal
        if ((status === 'error' || status === 'rejected' || status === 'disconnected') &&
          !els.w2tdLoading.classList.contains('hidden')) {
          els.w2tdLoading.classList.add('hidden');
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
        else if (msg.type === 'webrtc_offer') WebRTCModule.handleOffer(msg.sdp);
        else if (msg.type === 'webrtc_ice') WebRTCModule.handleIce(msg);
        else if (msg.type === 'webrtc_renegotiate') WebRTCModule.renegotiate();
        else if (msg.type === 'webrtc_answer_cam') WebRTCModule.handleCameraAnswer(msg.sdp, msg.camType);
        else if (msg.type === 'webrtc_ice_cam') WebRTCModule.handleCameraIce(msg);
        else if (msg.type === 'cam_receiver_ready') _maybeStartCamera();
      },
      onHaptic: (data) => {
        handleHapticFeedback(data);
      },
      onDataAck: () => {
        updateDataAckIndicator();
      },
      // Pro: Background color sync (strobe/flash effect)
      onBgColor: (color, duration) => {
        if (!bgColorEnabled) return;
        if (typeof AudioModule === 'undefined') return; // Pro feature check
        // videoout gate: bg color only applies in 'color' mode (or when unset)
        if (displayMode !== null && displayMode !== 'color') return;
        // Store last color for instant apply on mode switch
        if (color) {
          lastBgColor = color;
          localStorage.setItem('w2td-last-bg-color', color);
        }
        document.body.style.backgroundColor = color;
        // Apply to touch pad overlay as well (it covers body with its own background)
        const tp = $('touch-pad');
        if (tp) tp.style.backgroundColor = color;
        if (duration > 0) {
          setTimeout(() => {
            document.body.style.backgroundColor = '';
            if (tp) tp.style.backgroundColor = '';
          }, duration);
        }
      },
      // Pro: Live JS sketch injection from TD (render-canvas)
      onCanvasCode: (code) => {
        if (typeof CanvasRunner === 'undefined') return;
        const clean = code && String(code).trim();
        cachedCanvasCode = clean ? code : '';
        if (!clean) {
          CanvasRunner.stop();
          addLog('Canvas sketch cleared', 'info');
          _updateFullscreenButtonVisibility();
          return;
        }
        addLog(`Canvas sketch received (${code.length} chars)`, 'info');
        // videoout gate: only run in 'js' mode (or when unset). Cached above for later.
        if (displayMode !== null && displayMode !== 'js') {
          addLog(`Sketch cached (videoout=${displayMode}, not js)`, 'info');
          return;
        }
        CanvasRunner.load(code);
        _updateFullscreenButtonVisibility();
      },
      // Pro: Flashlight control
      onFlashlight: (state) => {
        if (!flashlightEnabled) return;
        addLog(`Flashlight signal received: state=${state}`, 'info');
        if (typeof WebRTCModule === 'undefined' || !WebRTCModule.toggleFlashlight) {
          addLog('Flashlight: WebRTCModule not available', 'warn');
          return;
        }
        WebRTCModule.toggleFlashlight(state).then(success => {
          if (success) {
            addLog(`Flashlight ${state ? 'ON' : 'OFF'}`, 'info');
          } else {
            addLog('Flashlight: Requires active rear camera', 'warn');
          }
        });
      },
    });

    els.modal.classList.remove('active');
    resizeTouchCanvas();
    window.addEventListener('resize', resizeTouchCanvas);

    // On first QR-scan (no cached devMode), we don't know user vs dev mode yet.
    // Show a loading screen so config can arrive before any UI is shown — prevents flash.
    const hasCachedMode = localStorage.getItem('w2td-dev-mode') !== null;
    if (autoConnect && !hasCachedMode) {
      els.w2tdLoading.classList.remove('hidden'); // applyDevMode() will hide it
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
    els.w2tdLoading.classList.add('hidden');
    els.mainUI.classList.add('hidden');

    // Stop haptic vibration on disconnect
    if (hapticInterval !== null) {
      clearInterval(hapticInterval);
      hapticInterval = null;
      hapticState = 0;
      if (navigator.vibrate) {
        navigator.vibrate(0);
      }
    }
    els.modal.classList.add('active');
  }

  async function _maybeStartWebRTC() {
    if (!WSClient.isConnected() || !SensorModule.isEnabled() ||
      WebRTCModule.isPCActive() || !broadcasting) return;
    if (_isTunnelConnection()) {
      // Warning removed since TURN server is now built-in
    }
    const ok = await WebRTCModule.start(_webrtcStartOpts({
      mic: micEnabled,
      echoCancellation: audioEchoCancellation,
      noiseSuppression: audioNoiseSuppression,
      autoGainControl: audioAutoGain,
      audioTx: audioTxEnabled,
      videoTx: videoTxEnabled,
    }));
    if (ok === false) {
      micEnabled = false;
      const err = WebRTCModule.getLastError();
      if (err === 'NotAllowedError' || err === 'PermissionDeniedError') {
        showToast('Mic permission denied — allow microphone in browser settings');
        addLog('Mic permission denied — allow microphone in browser settings', 'error');
      } else if (err === 'NotFoundError') {
        showToast('Microphone not found');
        addLog('Microphone not found (no device)', 'error');
      } else {
        showToast('Mic activation failed');
        addLog('Mic activation failed: ' + (err || 'unknown'), 'error');
      }
    }
    renderSensorList();
  }

  async function handleEnableSensors() {
    haptic();

    if (SensorModule.isEnabled()) {
      stopBroadcast();
      SensorModule.stopListening();
      if (WebRTCModule.isMicActive()) await WebRTCModule.stop();
      if (WebRTCModule.isCamPCActive()) WebRTCModule.stopCamera();
      els.btnEnableSensors.textContent = 'Start';
      els.btnEnableSensors.classList.remove('btn-active');
      updateDebug('Sensors deactivated');
      renderSensorList();
      return;
    }

    if (SensorModule.needsPermissionRequest()) {
      if (!window.isSecureContext) {
        updateDebug('iOS sensor permissions require HTTPS.');
        return;
      }
    }

    const _sel = SensorModule.getSelected();
    if (_sel.motion || _sel.orientation || _sel.geolocation) {
      updateDebug('Requesting permissions...');
      const perms = await SensorModule.requestPermissions();
      updateDebug('Permissions: ' + JSON.stringify(perms));
    }

    SensorModule.startListening();

    // On real mobile, warn if motion data doesn't flow after 3.5s
    if (!SensorModule.isSimulating()) {
      setTimeout(() => {
        if (!SensorModule.isEnabled()) return;
        if (!SensorModule.hasDataFlowing() && SensorModule.isMotionEventFiring()) {
          showToast(
            'Motion sensor blocked by browser. ' +
            'Go to Chrome Settings \u2192 Site Settings \u2192 Motion sensors \u2192 Allow',
            6000
          );
        }
      }, 3500);
    }

    if (micEnabled && !WebRTCModule.isMicActive()) {
      const ok = await WebRTCModule.acquireMic({
        echoCancellation: audioEchoCancellation,
        noiseSuppression: audioNoiseSuppression,
        autoGainControl: audioAutoGain,
      });
      if (ok === false) {
        micEnabled = false;
        const err = WebRTCModule.getLastError();
        if (err === 'NotAllowedError' || err === 'PermissionDeniedError') {
          showToast('Mic permission denied — allow microphone in browser settings');
        } else if (err === 'NotFoundError') {
          showToast('Microphone not found');
        } else {
          showToast('Mic activation failed');
        }
      }
    }

    if (cameraRearEnabled && !WebRTCModule.isCameraRearActive()) {
      const ok = await WebRTCModule.acquireCamera('environment');
      if (!ok) {
        cameraRearEnabled = false;
        const err = WebRTCModule.getLastError();
        if (err === 'NotAllowedError' || err === 'PermissionDeniedError') showToast('Camera permission denied');
        else if (err === 'NotFoundError') showToast('Camera not found');
        else showToast('Rear camera activation failed');
      }
    }
    if (cameraFrontEnabled && !WebRTCModule.isCameraFrontActive()) {
      const ok = await WebRTCModule.acquireCamera('user');
      if (!ok) {
        cameraFrontEnabled = false;
        const err = WebRTCModule.getLastError();
        if (err === 'NotAllowedError' || err === 'PermissionDeniedError') showToast('Camera permission denied');
        else if (err === 'NotFoundError') showToast('Camera not found');
        else showToast('Front camera activation failed');
      }
    }

    if (SensorModule.isSimulating()) {
      els.btnEnableSensors.textContent = 'Stop (Simulating)';
    } else {
      els.btnEnableSensors.textContent = 'Stop';
    }
    els.btnEnableSensors.classList.add('btn-active');

    startVizLoop();
    renderSensorList();

    if (WSClient.isConnected()) {
      _startDataBroadcast();
    }
  }

  async function _maybeStartCamera() {
    if (!WSClient.isConnected() || !broadcasting) return;
    if (cameraRearEnabled) {
      const ok = await WebRTCModule.startCamera('environment', _webrtcStartOpts({}));
      if (ok === false) {
        const err = WebRTCModule.getLastError();
        if (err) addLog('Cam rear start failed: ' + err, 'warn');
      }
    }
    if (cameraFrontEnabled) {
      const ok = await WebRTCModule.startCamera('user', _webrtcStartOpts({}));
      if (ok === false) {
        const err = WebRTCModule.getLastError();
        if (err) addLog('Cam front start failed: ' + err, 'warn');
      }
    }
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

  function showBroadcastStatus(msg, isError) {
    if (!els.broadcastStatus) return;
    els.broadcastStatus.textContent = msg;
    els.broadcastStatus.className = 'broadcast-status' + (isError ? ' error' : '');
  }

  async function _startDataBroadcast() {
    if (!WSClient.isConnected()) return;
    if (!SensorModule.isEnabled()) return;
    if (broadcasting) return; // already running — avoid duplicate intervals

    showBroadcastStatus('', false);
    broadcasting = true;
    if (els.packetRate) els.packetRate.classList.add('broadcasting');
    updateDebug('Broadcasting... ' + sampleRate + ' Hz');

    const interval = Math.round(1000 / sampleRate);
    broadcastInterval = setInterval(() => {
      WSClient.sendSensorData(SensorModule.getData());
    }, interval);

    await _maybeStartWebRTC();
    await _maybeStartCamera();
  }

  function stopBroadcast() {
    broadcasting = false;
    if (broadcastInterval) {
      clearInterval(broadcastInterval);
      broadcastInterval = null;
    }
    WebRTCModule.disconnect();
    WebRTCModule.disconnectCamera();
    if (els.packetRate) els.packetRate.classList.remove('broadcasting');
    showBroadcastStatus('', false);
    updateDebug('Broadcast stopped');
    renderSensorList();
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

  // Prevent browser swipe navigation and system gestures while touch pad is active.
  // Multi-touch touchstart blocks pinch/2-finger-swipe; touchmove blocks all scroll.
  function _onDocTouchStart(e) { if (e.touches.length >= 2) e.preventDefault(); }
  function _onDocTouchMove(e) { e.preventDefault(); }

  function _enableTouchLock() {
    document.addEventListener('touchstart', _onDocTouchStart, { passive: false });
    document.addEventListener('touchmove', _onDocTouchMove, { passive: false });
  }
  function _disableTouchLock() {
    document.removeEventListener('touchstart', _onDocTouchStart);
    document.removeEventListener('touchmove', _onDocTouchMove);
  }

  function enterTouchPad() {
    touchPadActive = true;
    stopVizTouch();
    if (els.mainUI) els.mainUI.classList.add('hidden');
    els.touchPad.classList.remove('hidden');
    els.btnExitTouch.classList.remove('hidden'); // always visible in dev_mode=1
    if (els.btnToggleTouchPoints) {
      els.btnToggleTouchPoints.classList.remove('hidden'); // show toggle button
    }
    resizeTouchCanvas();

    TouchModule.init(els.touchCanvas, (snapshot) => {
      if (showTouchPoints) {
        Visualization.drawTouches(els.touchCanvas, snapshot.touches, devMode);
      } else {
        // Clear canvas if touch points are hidden
        const ctx = els.touchCanvas.getContext('2d');
        ctx.clearRect(0, 0, els.touchCanvas.width, els.touchCanvas.height);
      }
      handleTouchData(snapshot);
    });
    updateTouchPointsToggleUI();
    _enableTouchLock();
    haptic();
  }

  function exitTouchPad() {
    touchPadActive = false;
    els.touchPad.classList.add('hidden');
    if (els.mainUI) els.mainUI.classList.remove('hidden');
    if (els.btnToggleTouchPoints) {
      els.btnToggleTouchPoints.classList.add('hidden'); // hide toggle button
    }
    TouchModule.destroy();
    _disableTouchLock();
    startVizTouch();
    haptic();
  }

  /**
   * Fullscreen view action — dispatches based on videoout:
   *   'td' (TD video): opens td-stream-monitor overlay (existing behavior)
   *   'js' (JS sketch): toggles body.sketch-fullscreen to hide main UI chrome
   *                     so the render-canvas shows unobstructed
   *   otherwise: toast "nothing to show"
   */
  function enterTdStreamMonitor() {
    haptic();
    if (displayMode === 'td') {
      // TD 영상 모드: td-stream-monitor 열기
      const _vEl = document.getElementById('webrtc-td-stream');
      addLog(`TD enter: videoEl=${!!_vEl} srcObject=${!!(_vEl && _vEl.srcObject)}`, 'info');
      if (_vEl && els.tdStreamVideoArea) {
        if (!els.tdStreamVideoArea.contains(_vEl)) {
          _vEl.style.position = '';
          _vEl.style.zIndex = '0';
          _vEl.style.objectFit = 'cover';
          _vEl.style.width = '100%';
          _vEl.style.height = '100%';
          els.tdStreamVideoArea.appendChild(_vEl);
        }
        if (_vEl.srcObject && _vEl.paused) {
          _vEl.play().catch(e => addLog(`TD video play failed: ${e.message}`, 'warn'));
        }
      }
      if (els.mainUI) els.mainUI.classList.add('hidden');
      if (els.tdStreamMonitor) els.tdStreamMonitor.classList.remove('hidden');
      _devFullscreenMode = 'td';
    } else if (displayMode === 'js') {
      // JS 스케치 모드: 전체화면
      const sketchActive = typeof CanvasRunner !== 'undefined' && CanvasRunner.isActive();
      if (!sketchActive) { showToast('No JS sketch running'); return; }
      if (els.mainUI) els.mainUI.classList.add('hidden');
      document.body.classList.add('sketch-fullscreen');
      _showDevExitBtn();
      _devFullscreenMode = 'js';
    } else if (displayMode === 'color') {
      // Color 모드: 배경색 전체화면
      if (els.mainUI) els.mainUI.classList.add('hidden');
      document.body.style.backgroundColor = lastBgColor || '#000000';
      _showDevExitBtn();
      _devFullscreenMode = 'color';
    }
  }

  function exitTdStreamMonitor() {
    if (!els.tdStreamMonitor) return;
    els.tdStreamMonitor.classList.add('hidden');
    _devFullscreenMode = null;
    if (els.mainUI) els.mainUI.classList.remove('hidden');
  }

  function _exitDevFullscreen() {
    if (_devFullscreenMode === 'td') {
      exitTdStreamMonitor();
    } else if (_devFullscreenMode === 'js') {
      document.body.classList.remove('sketch-fullscreen');
      _hideDevExitBtn();
      if (els.mainUI) els.mainUI.classList.remove('hidden');
      _devFullscreenMode = null;
    } else if (_devFullscreenMode === 'color') {
      document.body.style.backgroundColor = '';
      _hideDevExitBtn();
      if (els.mainUI) els.mainUI.classList.remove('hidden');
      _devFullscreenMode = null;
    }
  }

  function _showDevExitBtn() {
    const el = $('dev-fullscreen-exit');
    if (el) el.classList.remove('hidden');
  }
  function _hideDevExitBtn() {
    const el = $('dev-fullscreen-exit');
    if (el) el.classList.add('hidden');
  }

  function _updateFullscreenButtonVisibility() {
    if (!els.btnTdStream) return;
    if (devMode && (displayMode === 'td' || displayMode === 'js' || displayMode === 'color')) {
      // dev_mode=1: 모드가 설정된 순간 버튼 노출 (수동 진입 대기)
      els.btnTdStream.classList.remove('hidden');
      const labels = { td: 'TD Stream', js: 'JS Sketch', color: 'Color View' };
      els.btnTdStream.textContent = labels[displayMode] || 'Fullscreen';
    } else {
      els.btnTdStream.classList.add('hidden');
      document.body.classList.remove('sketch-fullscreen');
    }
  }

  function enterCameraMonitor() {
    if (!WebRTCModule.isCameraActive()) {
      showToast('Enable camera first (Rear or Front)');
      haptic();
      return;
    }
    haptic();
    _updateCamResolutionUI();
    els.mainUI.classList.add('hidden');
    els.cameraMonitor.classList.remove('hidden');
  }

  function exitCameraMonitor() {
    haptic();
    els.cameraMonitor.classList.add('hidden');
    els.mainUI.classList.remove('hidden');
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
          <h2>Connection Full</h2>
          <p>All slots are currently in use.<br>Please try again in a moment.</p>
          <button id="btn-retry" class="btn btn-primary" style="margin-top:20px">Retry</button>
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
    console.log('[W2TD]', msg);
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
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');
  }

  function showToast(msg, duration = 2800) {
    let el = document.getElementById('w2td-toast');
    if (el) el.remove();
    el = document.createElement('div');
    el.id = 'w2td-toast';
    el.className = 'w2td-toast';
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

  // Haptic state management (for CHOP-based continuous vibration)
  let hapticState = 0;  // 0 = stop, 1 = vibrate
  let hapticInterval = null;
  const HAPTIC_INTERVAL_MS = 100;  // Vibrate every 100ms when state=1

  /**
   * Handle haptic feedback from TD.
   * Supports two modes:
   * 1. Pattern mode: {"type": "haptic", "pattern": [200, 100, 200]}
   * 2. State mode: {"type": "haptic", "state": 0 or 1} (CHOP-based)
   */
  function handleHapticFeedback(data) {
    if (!hapticFeedbackEnabled) return;
    // Check Vibration API support
    if (!navigator.vibrate) {
      console.log('[W2TD] Vibration API not supported');
      return;
    }

    // State-based mode (CHOP): state = 0 (stop) or 1 (vibrate continuously)
    if (data.state !== undefined) {
      const newState = data.state === 1 ? 1 : 0;

      if (newState !== hapticState) {
        hapticState = newState;

        // Stop existing vibration interval
        if (hapticInterval !== null) {
          clearInterval(hapticInterval);
          hapticInterval = null;
          navigator.vibrate(0);  // Stop vibration
        }

        // Start continuous vibration if state = 1
        if (hapticState === 1) {
          // Vibrate immediately
          navigator.vibrate(HAPTIC_INTERVAL_MS);

          // Continue vibrating at intervals
          hapticInterval = setInterval(() => {
            if (hapticState === 1) {
              navigator.vibrate(HAPTIC_INTERVAL_MS);
            } else {
              clearInterval(hapticInterval);
              hapticInterval = null;
            }
          }, HAPTIC_INTERVAL_MS);

          addLog('Haptic: ON (continuous)', 'info');
        } else {
          addLog('Haptic: OFF', 'info');
        }
      }
      return;
    }

    // Pattern-based mode (legacy): pattern = [200, 100, 200]
    const pattern = data.pattern;
    if (!pattern || !Array.isArray(pattern) || pattern.length === 0) {
      console.warn('[W2TD] Invalid haptic pattern:', pattern);
      return;
    }

    // Stop any continuous vibration before playing pattern
    if (hapticInterval !== null) {
      clearInterval(hapticInterval);
      hapticInterval = null;
      hapticState = 0;
    }

    try {
      // Convert pattern to integers (safety check)
      const intPattern = pattern.map(v => Math.max(0, Math.min(Number(v) || 0, 10000)));

      // iOS Safari may not support pattern arrays, fallback to single value
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
      if (isIOS && intPattern.length > 1) {
        // iOS: use first value only
        navigator.vibrate(intPattern[0]);
        addLog(`Haptic (iOS): ${intPattern[0]}ms`, 'info');
      } else {
        // Android/Desktop: full pattern support
        navigator.vibrate(intPattern);
        addLog(`Haptic pattern: ${intPattern.join(', ')}ms`, 'info');
      }
    } catch (e) {
      console.error('[W2TD] Haptic error:', e);
      addLog('Haptic failed: ' + e.message, 'error');
    }
  }

  function haptic(duration = 30) {
    // Temporarily disabled: local UI tap vibration feedback.
    return;
  }

  // ── WebRTC ──────────────────────────────────────────────────────────────

  async function _startWebRTC() {
    if (!WSClient.isConnected()) return;
    const ok = await WebRTCModule.start(_webrtcStartOpts({ mic: micEnabled, audioTx: audioTxEnabled, videoTx: videoTxEnabled }));
    if (ok === false && micEnabled) {
      const err = WebRTCModule.getLastError();
      let msg = 'Mic activation failed';
      if (err === 'NotAllowedError' || err === 'PermissionDeniedError') msg = 'Mic permission denied';
      else if (err === 'NotFoundError') msg = 'Microphone not found';
      showToast(msg);
    }
  }

  async function handleRearCameraToggle() {
    haptic();
    if (cameraRearEnabled) {
      cameraRearEnabled = false;
      WebRTCModule.stopCameraRear();
      renderSensorList();
      return;
    }
    if (cameraFrontEnabled) {
      cameraFrontEnabled = false;
      WebRTCModule.stopCameraFront();
    }
    cameraRearEnabled = true;
    renderSensorList();
    if (!WSClient.isConnected()) {
      showToast('Connect to TouchDesigner first');
      cameraRearEnabled = false;
      renderSensorList();
      return;
    }
    const ok = await WebRTCModule.acquireCamera('environment');
    if (ok === false) {
      cameraRearEnabled = false;
      const err = WebRTCModule.getLastError();
      if (err === 'NotAllowedError' || err === 'PermissionDeniedError') showToast('Camera permission denied');
      else if (err === 'NotFoundError') showToast('Camera not found');
      else showToast('Rear camera activation failed');
      renderSensorList();
      return;
    }
    await _maybeStartCamera();
    renderSensorList();
  }

  async function handleFrontCameraToggle() {
    haptic();
    if (cameraFrontEnabled) {
      cameraFrontEnabled = false;
      WebRTCModule.stopCameraFront();
      renderSensorList();
      return;
    }
    if (cameraRearEnabled) {
      cameraRearEnabled = false;
      WebRTCModule.stopCameraRear();
    }
    cameraFrontEnabled = true;
    renderSensorList();
    if (!WSClient.isConnected()) {
      showToast('Connect to TouchDesigner first');
      cameraFrontEnabled = false;
      renderSensorList();
      return;
    }
    const ok = await WebRTCModule.acquireCamera('user');
    if (ok === false) {
      cameraFrontEnabled = false;
      const err = WebRTCModule.getLastError();
      if (err === 'NotAllowedError' || err === 'PermissionDeniedError') showToast('Camera permission denied');
      else if (err === 'NotFoundError') showToast('Camera not found');
      else showToast('Front camera activation failed');
      renderSensorList();
      return;
    }
    await _maybeStartCamera();
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
    micEnabled = true;
    renderSensorList();

    // Acquire mic stream immediately (permission popup) if sensors are already on
    if (SensorModule.isEnabled() && !WebRTCModule.isMicActive()) {
      const ok = await WebRTCModule.acquireMic({
        echoCancellation: audioEchoCancellation,
        noiseSuppression: audioNoiseSuppression,
        autoGainControl: audioAutoGain,
      });
      if (ok === false) {
        micEnabled = false;
        const err = WebRTCModule.getLastError();
        if (err === 'NotAllowedError' || err === 'PermissionDeniedError') {
          showToast('Mic permission denied — allow microphone in browser settings');
        } else if (err === 'NotFoundError') {
          showToast('Microphone not found');
        } else {
          showToast('Mic activation failed');
        }
        renderSensorList();
        return;
      }
    }
    // If already broadcasting, connect immediately
    await _maybeStartWebRTC();
  }

  /**
   * Request all permissions in one sequence (for dev_mode=0 integrated start)
   * Requests: sensors, microphone, wakeLock
   */
  async function requestAllPermissions() {
    const results = {
      sensors: false,
      camera: false,
      wakeLock: false,
    };

    try {
      // 1. Sensor permissions (DeviceMotion, DeviceOrientation) — only if needed
      const _sel = SensorModule.getSelected();
      if ((_sel.motion || _sel.orientation || _sel.geolocation) && SensorModule.needsPermissionRequest()) {
        await SensorModule.requestPermissions();
        results.sensors = true;
        addLog('Sensor permissions granted', 'info');
      } else {
        results.sensors = true;
      }

      // 2. Microphone — NOT acquired here to avoid unwanted permission popups.
      //    Mic is acquired later by _maybeStartWebRTC() → WebRTCModule.start()
      //    only when micEnabled=true AND broadcasting is active.
      //    On iOS 15+, getUserMedia works in async chains after user gesture.

      // 3. Camera permission — if rear or front enabled (from config)
      if (cameraRearEnabled || cameraFrontEnabled) {
        try {
          const mode = cameraRearEnabled ? 'environment' : 'user';
          const camOk = await WebRTCModule.acquireCamera(mode);
          if (camOk) {
            results.camera = true;
            addLog('Camera permission granted', 'info');
          } else {
            addLog('Camera permission denied', 'warn');
          }
        } catch (e) {
          addLog('Camera permission error: ' + (e.message || e.name), 'warn');
        }
      }

      // 4. WakeLock permission (Screen Wake Lock API)
      // Note: WakeLock doesn't require explicit permission, but needs user gesture
      try {
        if ('wakeLock' in navigator) {
          const lock = await navigator.wakeLock.request('screen');
          results.wakeLock = true;
          addLog('WakeLock activated', 'info');
          // Release immediately - will be requested again when broadcasting
          lock.release();
        } else {
          addLog('WakeLock not supported', 'info');
        }
      } catch (e) {
        addLog('WakeLock error: ' + (e.message || e.name), 'warn');
      }

      // Summary
      const granted = Object.values(results).filter(v => v).length;
      const total = Object.keys(results).length;
      addLog(`Permissions: ${granted}/${total} granted`, granted === total ? 'info' : 'warn');

    } catch (e) {
      addLog('Permission request error: ' + e.message, 'error');
    }

    return results;
  }

  /**
   * Update data acknowledgment indicator (pulse on status-dot next to "Connected to TD")
   */
  function updateDataAckIndicator() {
    const dot = els.connectionStatus;
    if (!dot || !dot.classList.contains('connected')) return;
    dot.classList.add('ack-pulse');
    setTimeout(() => dot.classList.remove('ack-pulse'), 500);
  }

  /**
   * Toggle touch points visibility in touchpad mode
   */
  function toggleTouchPoints() {
    showTouchPoints = !showTouchPoints;
    saveSettings();
    updateTouchPointsToggleUI();
    haptic();

    // If touchpad is active, clear or redraw immediately
    if (touchPadActive) {
      const snapshot = TouchModule.getSnapshot();
      if (snapshot) {
        if (showTouchPoints) {
          Visualization.drawTouches(els.touchCanvas, snapshot.touches, devMode);
        } else {
          const ctx = els.touchCanvas.getContext('2d');
          ctx.clearRect(0, 0, els.touchCanvas.width, els.touchCanvas.height);
        }
      }
    }
  }

  /**
   * Update touch points toggle button UI state
   */
  function updateTouchPointsToggleUI() {
    if (!els.btnToggleTouchPoints) return;

    if (showTouchPoints) {
      els.btnToggleTouchPoints.classList.add('active');
      els.btnToggleTouchPoints.textContent = 'Show Dots';
      els.btnToggleTouchPoints.setAttribute('title', 'Hide dots');
    } else {
      els.btnToggleTouchPoints.classList.remove('active');
      els.btnToggleTouchPoints.textContent = 'Show Dots';
      els.btnToggleTouchPoints.setAttribute('title', 'Show dots');
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
