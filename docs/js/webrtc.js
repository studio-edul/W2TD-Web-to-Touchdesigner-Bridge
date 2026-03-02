/**
 * W2TD WebRTC Module
 * Mic  → RTCPeerConnection(micPc)  → TD WebRTC DAT → Audio Stream In CHOP
 * Cam  → RTCPeerConnection(camPc)  → Web Render TOP (cam_receiver.html)
 * Signaling for both uses the existing WebSocket (TD Web Server DAT).
 */
const WebRTCModule = (() => {
  // Portrait = tall(h>w), Landscape = wide(w>h)
  const RESOLUTION_PRESETS = {
    'Non-Commercial': { portrait: { w: 540, h: 960 }, landscape: { w: 960, h: 540 }, maxBitrate: 1500000 },
    'FHD':             { portrait: { w: 1080, h: 1920 }, landscape: { w: 1920, h: 1080 }, maxBitrate: 4000000 },
    '4K':              { portrait: { w: 2160, h: 3840 }, landscape: { w: 3840, h: 2160 }, maxBitrate: 8000000 },
  };
  const DEFAULT_RESOLUTION = 'Non-Commercial';
  const DEFAULT_SCREENMODE = 'Portrait';

  function _getCameraResolution(resolution, screenmode) {
    const res = (resolution || DEFAULT_RESOLUTION).trim();
    const preset = RESOLUTION_PRESETS[res] || RESOLUTION_PRESETS[DEFAULT_RESOLUTION];
    const mode = (screenmode || DEFAULT_SCREENMODE).trim().toLowerCase();
    // Portrait = tall(vertical), Landscape = wide(horizontal) — natural mapping
    const dims = (mode === 'portrait' ? preset.portrait : preset.landscape);
    return { width: dims.w, height: dims.h, maxBitrate: preset.maxBitrate };
  }

  const DEFAULT_ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'turn:freeturn.net:3478',        username: 'free', credential: 'free' },
    { urls: 'turns:freeturn.net:5349',       username: 'free', credential: 'free' },
    { urls: 'turn:openrelay.metered.ca:80',  username: 'openrelayproject', credential: 'openrelayproject' },
    { urls: 'turns:openrelay.metered.ca:443',username: 'openrelayproject', credential: 'openrelayproject' },
  ];

  // ── Mic (→ TD WebRTC DAT) ──────────────────────────────────────────────────
  let micPc     = null;
  let micStream = null;
  let micActive = false;
  let _onStateChange = null;
  let _micIceRecvCount = 0;

  // ── Camera (→ Web Render TOP via cam_receiver.html) ───────────────────────
  // Front (user/selfie) and Rear (environment) as separate connections
  let camFrontPc = null, camFrontStream = null;
  let camRearPc   = null, camRearStream   = null;
  let _onCamStateChange = null;
  let _camFrontIceRecv = 0, _camRearIceRecv = 0;

  // ── Shared ────────────────────────────────────────────────────────────────
  let _lastError = null;
  let _audioCtx  = null;
  let _analyser  = null;
  let _onLog     = null;

  function _log(msg) {
    if (_onLog) _onLog(msg);
    console.log('[W2TD WebRTC]', msg);
  }

  function _logCamResolution(stream, label) {
    const track = stream && stream.getVideoTracks()[0];
    if (!track) return;
    const s = track.getSettings();
    const w = s.width || track.getCapabilities?.()?.width?.max || '?';
    const h = s.height || track.getCapabilities?.()?.height?.max || '?';
    _log(`[Mobile send] ${label}: ${w}x${h}`);
  }

  function _buildRtcConfig(iceServers, iceTransportPolicy) {
    const ice = Array.isArray(iceServers) && iceServers.length ? iceServers : DEFAULT_ICE_SERVERS;
    const cfg = { iceServers: ice };
    if (iceTransportPolicy === 'relay') cfg.iceTransportPolicy = 'relay';
    return cfg;
  }

  // ── Mic public API ─────────────────────────────────────────────────────────

  /**
   * Acquire mic stream (getUserMedia) — call on Enable Sensors for early permission.
   * Idempotent — returns true if stream already acquired.
   */
  async function acquireMic({
    echoCancellation = false,
    noiseSuppression = false,
    autoGainControl  = false,
  } = {}) {
    _lastError = null;
    if (micStream && micStream.getAudioTracks().length > 0) return true;
    if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
    if (_audioCtx) { _audioCtx.close(); _audioCtx = null; }
    _analyser = null;
    micActive = false;
    try {
      micStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation, noiseSuppression, autoGainControl },
        video: false,
      });
      micActive = micStream.getAudioTracks().length > 0;
      _log('acquireMic OK — mic:' + micActive);
    } catch (e) {
      _lastError = e.name || 'unknown';
      console.error('[W2TD WebRTC] acquireMic failed:', e.name, e.message);
      return false;
    }
    if (micActive) _setupAnalyser(micStream);
    return micActive;
  }

  /**
   * Create mic RTCPeerConnection and send offer to TD WebRTC DAT.
   * Camera is handled separately via startCamera().
   */
  async function start({
    mic = true,
    echoCancellation = false,
    noiseSuppression = false,
    autoGainControl  = false,
    iceServers       = null,
    iceTransportPolicy = null,
  } = {}) {
    _lastError = null;
    _micIceRecvCount = 0;
    if (micPc) { micPc.close(); micPc = null; }

    if (!micStream) {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: mic ? { echoCancellation, noiseSuppression, autoGainControl } : false,
          video: false,
        });
        micActive = mic && micStream.getAudioTracks().length > 0;
        _log('getUserMedia (mic) OK — mic:' + micActive);
      } catch (e) {
        _lastError = e.name || 'unknown';
        console.error('[W2TD WebRTC] getUserMedia mic failed:', e.name, e.message);
        _setMicState('failed');
        return false;
      }
      if (micActive && !_analyser) _setupAnalyser(micStream);
    }

    micPc = new RTCPeerConnection(_buildRtcConfig(iceServers, iceTransportPolicy));
    micStream.getTracks().forEach(track => micPc.addTrack(track, micStream));

    let iceCount = 0;
    micPc.onicecandidate = ({ candidate }) => {
      if (!candidate) return;
      iceCount++;
      if (iceCount <= 3) _log('mic ICE #' + iceCount + ' sent');
      WSClient.send({
        type: 'webrtc_ice',
        candidate: candidate.candidate,
        sdpMLineIndex: candidate.sdpMLineIndex,
        sdpMid: candidate.sdpMid,
      });
    };

    micPc.onconnectionstatechange = () => {
      const s = micPc.connectionState;
      console.log('[W2TD WebRTC] mic connectionState:', s);
      _setMicState(s);
      if (s === 'failed' || s === 'closed') stop();
    };

    micPc.oniceconnectionstatechange = () => {
      console.log('[W2TD WebRTC] mic iceState:', micPc.iceConnectionState);
    };

    _setMicState('connecting');

    try {
      const offer = await micPc.createOffer();
      await micPc.setLocalDescription(offer);
      const sent = WSClient.send({ type: 'webrtc_offer', sdp: offer.sdp });
      _log(sent ? 'Mic offer sent to TD' : 'Mic offer FAILED — WebSocket not connected');
    } catch (e) {
      console.error('[W2TD WebRTC] mic createOffer failed:', e);
      _setMicState('failed');
    }
  }

  /** Stop mic: close PC and release stream. */
  async function stop() {
    if (_audioCtx) { _audioCtx.close(); _audioCtx = null; }
    _analyser = null;
    if (micStream) { micStream.getTracks().forEach(t => t.stop()); micStream = null; }
    if (micPc) { micPc.close(); micPc = null; }
    micActive = false;
    _setMicState('closed');
    console.log('[W2TD WebRTC] Mic stopped');
  }

  /** Close mic PC only — keep micStream and analyser alive (for reuse). */
  function disconnect() {
    if (micPc) { micPc.close(); micPc = null; }
    _setMicState('closed');
    console.log('[W2TD WebRTC] Mic disconnected (stream kept)');
  }

  async function handleAnswer(sdp) {
    if (!micPc) return;
    try {
      await micPc.setRemoteDescription({ type: 'answer', sdp });
      console.log('[W2TD WebRTC] Mic remote description set');
    } catch (e) {
      console.error('[W2TD WebRTC] mic setRemoteDescription failed:', e);
    }
  }

  async function handleIce({ candidate, sdpMLineIndex, sdpMid }) {
    if (!micPc || !candidate) return;
    _micIceRecvCount++;
    if (_micIceRecvCount <= 3) _log('mic ICE from TD #' + _micIceRecvCount);
    try {
      await micPc.addIceCandidate(new RTCIceCandidate({ candidate, sdpMLineIndex, sdpMid }));
    } catch (e) {
      _log('mic addIceCandidate failed: ' + (e.message || e));
    }
  }

  // ── Camera public API (Front / Rear) ───────────────────────────────────────

  const CAM_FRONT = 'front';
  const CAM_REAR  = 'rear';

  /** Request camera permission only (for Enable Sensors). Gets stream and releases immediately. */
  async function requestCameraPermission() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return false;
    _lastError = null;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: true });
      s.getTracks().forEach(t => t.stop());
      return true;
    } catch (e) {
      _lastError = e.name || 'unknown';
      return false;
    }
  }

  /** Acquire camera stream — facingMode: 'user' (front) or 'environment' (rear).
   * opts: { cameraResolution, cameraScreenmode } from config */
  async function acquireCamera(facingMode = 'environment', opts = {}) {
    _lastError = null;
    const isFront = facingMode === 'user';
    const stream = isFront ? camFrontStream : camRearStream;
    if (stream && stream.getVideoTracks().length > 0) return true;
    if (stream) { stream.getTracks().forEach(t => t.stop()); }
    if (isFront) camFrontStream = null; else camRearStream = null;
    const res = _getCameraResolution(opts.cameraResolution, opts.cameraScreenmode);
    const maxDim = Math.max(res.width, res.height);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: facingMode },
          width:  { ideal: res.width,  max: maxDim },
          height: { ideal: res.height, max: maxDim },
        },
        audio: false,
      });
      if (isFront) camFrontStream = s; else camRearStream = s;
      _logCamResolution(s, isFront ? 'front' : 'rear');
      _log('acquireCamera OK — ' + (isFront ? 'front' : 'rear'));
      _updatePreview();
      return true;
    } catch (e) {
      _lastError = e.name || 'unknown';
      console.error('[W2TD WebRTC] acquireCamera failed:', e.name, e.message);
      return false;
    }
  }

  /** Start camera stream (front or rear) and send offer to TD.
   * opts: { cameraResolution, cameraScreenmode, iceServers, iceTransportPolicy } */
  async function startCamera(facingMode = 'environment', opts = {}) {
    _lastError = null;
    const isFront = facingMode === 'user';
    const camType = isFront ? CAM_FRONT : CAM_REAR;

    if (isFront) {
      _camFrontIceRecv = 0;
      if (camFrontPc) { camFrontPc.close(); camFrontPc = null; }
    } else {
      _camRearIceRecv = 0;
      if (camRearPc) { camRearPc.close(); camRearPc = null; }
    }

    let stream = isFront ? camFrontStream : camRearStream;
    if (!stream || stream.getVideoTracks().length === 0) {
      if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null; }
      if (isFront) camFrontStream = null; else camRearStream = null;
      const res = _getCameraResolution(opts.cameraResolution, opts.cameraScreenmode);
      const maxDim = Math.max(res.width, res.height);
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingMode },
            width:  { ideal: res.width,  max: maxDim },
            height: { ideal: res.height, max: maxDim },
          },
          audio: false,
        });
        if (isFront) camFrontStream = stream; else camRearStream = stream;
        _logCamResolution(stream, camType);
      } catch (e) {
        _lastError = e.name || 'unknown';
        _setCamState('failed');
        return false;
      }
      _updatePreview();
    }

    const pc = new RTCPeerConnection(_buildRtcConfig(opts.iceServers, opts.iceTransportPolicy));
    if (isFront) camFrontPc = pc; else camRearPc = pc;

    stream.getTracks().forEach(track => pc.addTrack(track, stream));

    pc.onicecandidate = ({ candidate }) => {
      if (!candidate) return;
      WSClient.send({
        type: 'webrtc_ice_cam',
        candidate: candidate.candidate,
        sdpMLineIndex: candidate.sdpMLineIndex,
        sdpMid: candidate.sdpMid,
        camType,
      });
    };

    pc.onconnectionstatechange = () => {
      const s = pc.connectionState;
      _setCamState(s);
      if (s === 'failed' || s === 'closed') {
        if (isFront) stopCameraFront();
        else stopCameraRear();
      }
    };

    _setCamState('connecting');

    try {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await _setCameraSenderParams(pc, opts);
      const sent = WSClient.send({ type: 'webrtc_offer_cam', sdp: offer.sdp, camType });
      _log(sent ? 'Cam ' + camType + ' offer sent' : 'Cam offer FAILED');
      return sent ? true : false;
    } catch (e) {
      _setCamState('failed');
      return false;
    }
  }

  async function _setCameraSenderParams(pc, opts = {}) {
    const sender = pc.getSenders().find(s => s.track && s.track.kind === 'video');
    if (!sender) return;
    try {
      const res = _getCameraResolution(opts.cameraResolution, opts.cameraScreenmode);
      const params = sender.getParameters();
      params.encodings = params.encodings || [{}];
      const track = sender.track;
      const s = track && track.getSettings ? track.getSettings() : {};
      const w = s.width || res.width;
      const h = s.height || res.height;
      const maxPx = Math.max(res.width, res.height);
      const minPx = Math.min(res.width, res.height);
      const scale = Math.max(
        Math.ceil(Math.max(w, h) / maxPx),
        Math.ceil(Math.min(w, h) / minPx),
        1
      );
      params.encodings[0].scaleResolutionDownBy = scale;
      params.encodings[0].maxBitrate = res.maxBitrate;
      params.degradationPreference = 'maintain-resolution';
      await sender.setParameters(params);
      _log(`Cam sender: ${w}x${h} → scale ${scale}, maxBitrate=${res.maxBitrate / 1e6}Mbps`);
    } catch (e) {
      console.warn('[W2TD WebRTC] setParameters failed:', e.message);
    }
  }

  function stopCameraFront() {
    if (camFrontStream) { camFrontStream.getTracks().forEach(t => t.stop()); camFrontStream = null; }
    if (camFrontPc) { camFrontPc.close(); camFrontPc = null; }
    _updatePreview();
  }

  function stopCameraRear() {
    if (camRearStream) { camRearStream.getTracks().forEach(t => t.stop()); camRearStream = null; }
    if (camRearPc) { camRearPc.close(); camRearPc = null; }
    _updatePreview();
  }

  /** Close camera WebRTC connections only — keep streams for reconnect on next Start Broadcast. */
  function disconnectCamera() {
    if (camFrontPc) { camFrontPc.close(); camFrontPc = null; }
    if (camRearPc) { camRearPc.close(); camRearPc = null; }
    _setCamState('closed');
  }

  function stopCamera() {
    stopCameraFront();
    stopCameraRear();
    _updatePreview();
    _setCamState('closed');
  }

  async function handleCameraAnswer(sdp, camType = CAM_REAR) {
    const pc = camType === CAM_FRONT ? camFrontPc : camRearPc;
    if (!pc) return;
    try {
      await pc.setRemoteDescription({ type: 'answer', sdp });
    } catch (e) {
      console.error('[W2TD WebRTC] cam setRemoteDescription failed:', e);
    }
  }

  async function handleCameraIce({ candidate, sdpMLineIndex, sdpMid, camType = CAM_REAR }) {
    const pc = camType === CAM_FRONT ? camFrontPc : camRearPc;
    if (!pc || !candidate) return;
    try {
      await pc.addIceCandidate(new RTCIceCandidate({ candidate, sdpMLineIndex, sdpMid }));
    } catch (e) {
      _log('cam addIceCandidate failed: ' + (e.message || e));
    }
  }

  // ── Shared callbacks ───────────────────────────────────────────────────────

  function onStateChange(fn)    { _onStateChange    = fn; }
  function onCamStateChange(fn) { _onCamStateChange = fn; }
  function setOnLog(fn)         { _onLog = fn; }

  // ── Private helpers ────────────────────────────────────────────────────────

  function _setMicState(state) { if (_onStateChange)    _onStateChange(state); }
  function _setCamState(state) { if (_onCamStateChange) _onCamStateChange(state); }

  function _setupAnalyser(stream) {
    try {
      _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = _audioCtx.createMediaStreamSource(stream);
      _analyser = _audioCtx.createAnalyser();
      _analyser.fftSize = 256;
      _analyser.smoothingTimeConstant = 0.8;
      source.connect(_analyser);
    } catch (e) { console.warn('[W2TD WebRTC] Audio analyser setup failed:', e); }
  }

  function _updatePreview() {
    const rearVid  = document.getElementById('webrtc-preview-rear');
    const frontVid = document.getElementById('webrtc-preview-front');
    const hasRear  = !!(camRearStream  && camRearStream.getVideoTracks().length  > 0);
    const hasFront = !!(camFrontStream && camFrontStream.getVideoTracks().length > 0);
    if (rearVid) {
      if (hasRear) { rearVid.srcObject = camRearStream;  rearVid.classList.remove('hidden'); }
      else         { rearVid.srcObject = null;            rearVid.classList.add('hidden'); }
    }
    if (frontVid) {
      if (hasFront) { frontVid.srcObject = camFrontStream; frontVid.classList.remove('hidden'); }
      else          { frontVid.srcObject = null;            frontVid.classList.add('hidden'); }
    }
  }

  function getMicLevel() {
    if (!_analyser || !_audioCtx) return 0;
    if (_audioCtx.state === 'suspended') _audioCtx.resume();
    const data = new Uint8Array(_analyser.fftSize);
    _analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const n = (data[i] - 128) / 128;
      sum += n * n;
    }
    return Math.min(1, Math.sqrt(sum / data.length));
  }

  return {
    // Mic
    acquireMic, start, stop, disconnect,
    handleAnswer, handleIce,
    onStateChange,
    isMicActive:  () => micActive,
    isPCActive:   () => micPc !== null,
    // Camera
    requestCameraPermission, acquireCamera, startCamera, stopCamera, disconnectCamera,
    stopCameraFront, stopCameraRear,
    handleCameraAnswer, handleCameraIce,
    onCamStateChange,
    CAM_FRONT, CAM_REAR,
    isCameraFrontActive: () => !!(camFrontStream && camFrontStream.getVideoTracks().length),
    isCameraRearActive:  () => !!(camRearStream && camRearStream.getVideoTracks().length),
    isCameraActive:      () => !!(camFrontStream?.getVideoTracks().length || camRearStream?.getVideoTracks().length),
    isCamPCActive:       () => camFrontPc !== null || camRearPc !== null,
    // Shared
    isActive: () => micActive || !!(camFrontStream?.getVideoTracks().length || camRearStream?.getVideoTracks().length),
    setOnLog,
    getMicLevel,
    getLastError: () => _lastError,
  };
})();
