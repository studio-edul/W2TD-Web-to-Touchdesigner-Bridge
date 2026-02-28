/**
 * WOB WebRTC Module
 * Mic  → RTCPeerConnection(micPc)  → TD WebRTC DAT → Audio Stream In CHOP
 * Cam  → RTCPeerConnection(camPc)  → Web Render TOP (cam_receiver.html)
 * Signaling for both uses the existing WebSocket (TD Web Server DAT).
 */
const WebRTCModule = (() => {
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
  let camPc     = null;
  let camStream = null;
  let camActive = false;
  let _onCamStateChange = null;
  let _camIceRecvCount  = 0;

  // ── Shared ────────────────────────────────────────────────────────────────
  let _lastError = null;
  let _audioCtx  = null;
  let _analyser  = null;
  let _onLog     = null;

  function _log(msg) {
    if (_onLog) _onLog(msg);
    console.log('[WOB WebRTC]', msg);
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
      console.error('[WOB WebRTC] acquireMic failed:', e.name, e.message);
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
        console.error('[WOB WebRTC] getUserMedia mic failed:', e.name, e.message);
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
      console.log('[WOB WebRTC] mic connectionState:', s);
      _setMicState(s);
      if (s === 'failed' || s === 'closed') stop();
    };

    micPc.oniceconnectionstatechange = () => {
      console.log('[WOB WebRTC] mic iceState:', micPc.iceConnectionState);
    };

    _setMicState('connecting');

    try {
      const offer = await micPc.createOffer();
      await micPc.setLocalDescription(offer);
      const sent = WSClient.send({ type: 'webrtc_offer', sdp: offer.sdp });
      _log(sent ? 'Mic offer sent to TD' : 'Mic offer FAILED — WebSocket not connected');
    } catch (e) {
      console.error('[WOB WebRTC] mic createOffer failed:', e);
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
    console.log('[WOB WebRTC] Mic stopped');
  }

  /** Close mic PC only — keep micStream and analyser alive (for reuse). */
  function disconnect() {
    if (micPc) { micPc.close(); micPc = null; }
    _setMicState('closed');
    console.log('[WOB WebRTC] Mic disconnected (stream kept)');
  }

  async function handleAnswer(sdp) {
    if (!micPc) return;
    try {
      await micPc.setRemoteDescription({ type: 'answer', sdp });
      console.log('[WOB WebRTC] Mic remote description set');
    } catch (e) {
      console.error('[WOB WebRTC] mic setRemoteDescription failed:', e);
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

  // ── Camera public API ──────────────────────────────────────────────────────

  /**
   * Acquire camera stream + create RTCPeerConnection → send webrtc_offer_cam to TD.
   * TD relays the offer to cam_receiver.html (Web Render TOP).
   */
  async function startCamera({
    iceServers         = null,
    iceTransportPolicy = null,
  } = {}) {
    _lastError = null;
    _camIceRecvCount = 0;
    if (camPc) { camPc.close(); camPc = null; }
    if (camStream) { camStream.getTracks().forEach(t => t.stop()); camStream = null; }
    camActive = false;

    try {
      camStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      camActive = camStream.getVideoTracks().length > 0;
      _log('acquireCamera OK — cam:' + camActive);
    } catch (e) {
      _lastError = e.name || 'unknown';
      console.error('[WOB WebRTC] acquireCamera failed:', e.name, e.message);
      _setCamState('failed');
      return false;
    }

    _updatePreview(camStream);

    camPc = new RTCPeerConnection(_buildRtcConfig(iceServers, iceTransportPolicy));
    camStream.getTracks().forEach(track => camPc.addTrack(track, camStream));

    let iceCount = 0;
    camPc.onicecandidate = ({ candidate }) => {
      if (!candidate) return;
      iceCount++;
      if (iceCount <= 3) _log('cam ICE #' + iceCount + ' sent');
      WSClient.send({
        type: 'webrtc_ice_cam',
        candidate: candidate.candidate,
        sdpMLineIndex: candidate.sdpMLineIndex,
        sdpMid: candidate.sdpMid,
      });
    };

    camPc.onconnectionstatechange = () => {
      const s = camPc.connectionState;
      console.log('[WOB WebRTC] cam connectionState:', s);
      _setCamState(s);
      if (s === 'failed' || s === 'closed') stopCamera();
    };

    camPc.oniceconnectionstatechange = () => {
      console.log('[WOB WebRTC] cam iceState:', camPc.iceConnectionState);
    };

    _setCamState('connecting');

    try {
      const offer = await camPc.createOffer();
      await camPc.setLocalDescription(offer);
      const sent = WSClient.send({ type: 'webrtc_offer_cam', sdp: offer.sdp });
      _log(sent ? 'Cam offer sent to TD' : 'Cam offer FAILED — WebSocket not connected');
    } catch (e) {
      console.error('[WOB WebRTC] cam createOffer failed:', e);
      _setCamState('failed');
      return false;
    }
  }

  /** Stop camera: close PC and release stream. */
  function stopCamera() {
    if (camStream) { camStream.getTracks().forEach(t => t.stop()); camStream = null; }
    if (camPc) { camPc.close(); camPc = null; }
    camActive = false;
    _updatePreview(null);
    _setCamState('closed');
    console.log('[WOB WebRTC] Camera stopped');
  }

  async function handleCameraAnswer(sdp) {
    if (!camPc) return;
    try {
      await camPc.setRemoteDescription({ type: 'answer', sdp });
      console.log('[WOB WebRTC] Cam remote description set');
    } catch (e) {
      console.error('[WOB WebRTC] cam setRemoteDescription failed:', e);
    }
  }

  async function handleCameraIce({ candidate, sdpMLineIndex, sdpMid }) {
    if (!camPc || !candidate) return;
    _camIceRecvCount++;
    if (_camIceRecvCount <= 3) _log('cam ICE from TD #' + _camIceRecvCount);
    try {
      await camPc.addIceCandidate(new RTCIceCandidate({ candidate, sdpMLineIndex, sdpMid }));
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
    } catch (e) { console.warn('[WOB WebRTC] Audio analyser setup failed:', e); }
  }

  function _updatePreview(stream) {
    const preview = document.getElementById('webrtc-preview');
    if (!preview) return;
    if (stream && stream.getVideoTracks().length > 0) {
      preview.srcObject = stream;
      preview.classList.remove('hidden');
    } else {
      preview.srcObject = null;
      preview.classList.add('hidden');
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
    startCamera, stopCamera,
    handleCameraAnswer, handleCameraIce,
    onCamStateChange,
    isCameraActive: () => camActive,
    isCamPCActive:  () => camPc !== null,
    // Shared
    isActive:     () => micActive || camActive,
    setOnLog,
    getMicLevel,
    getLastError: () => _lastError,
  };
})();
