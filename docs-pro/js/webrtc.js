/**
 * W2TD WebRTC Module
 * Mic  → RTCPeerConnection(micPc)  → TD WebRTC DAT → Audio Stream In CHOP
 * Cam  → RTCPeerConnection(camPc)  → Web Render TOP (cam_receiver.html)
 * Signaling for both uses the existing WebSocket (TD Web Server DAT).
 */
const WebRTCModule = (() => {
  // ── Camera resolution presets — updated at runtime via setResolution() ───────
  const _CAM_RESOLUTION_MAP = {
    'non-commercial': { width: 1280, height: 720, maxBitrate: 2000000 },
    'fhd': { width: 1920, height: 1080, maxBitrate: 4000000 },
  };
  let _camResolution = _CAM_RESOLUTION_MAP['fhd']; // default until config arrives from TD
  let _camResolutionKey = 'fhd';

  const DEFAULT_ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' }
  ];

  // ── Mic (→ TD WebRTC DAT) ──────────────────────────────────────────────────
  let micPc = null;
  let micStream = null;
  let micActive = false;
  let _onStateChange = null;
  let _micIceRecvCount = 0;

  // ── Camera (→ Web Render TOP via cam_receiver.html) ───────────────────────
  // Front (user/selfie) and Rear (environment) as separate connections
  let camFrontPc = null, camFrontStream = null;
  let camRearPc = null, camRearStream = null;
  let _onCamStateChange = null;
  let _camFrontIceRecv = 0, _camRearIceRecv = 0;

  // ── Shared ────────────────────────────────────────────────────────────────
  let _lastError = null;
  let _audioCtx = null;
  let _analyser = null;
  let _onLog = null;
  let _onTdVideoTrack = null; // callback(videoEl, track) when TD sends video downlink

  // ── Orientation lock ───────────────────────────────────────────────────────
  let _orientationLocked = false;

  function _lockCameraOrientation() {
    if (!screen.orientation?.lock) return;
    screen.orientation.lock('portrait-primary')
      .then(() => { _orientationLocked = true; })
      .catch(() => { _orientationLocked = false; });
  }

  function _clearOrientationLock() {
    if (_orientationLocked) {
      try { screen.orientation.unlock(); } catch (e) { }
      _orientationLocked = false;
    }
  }

  function _log(msg) {
    if (_onLog) _onLog(msg);
    console.log('[W2TD WebRTC]', msg);
  }

  /**
   * Enhance Opus codec parameters in SDP for better audio quality.
   * Sets higher bitrate, enables forward error correction (FEC),
   * and disables discontinuous transmission (DTX) to reduce crackling.
   */
  function _enhanceOpusSdp(sdp) {
    if (!sdp) return sdp;
    // Find the Opus payload type from rtpmap line
    const opusMatch = sdp.match(/a=rtpmap:(\d+)\s+opus\/48000/i);
    if (!opusMatch) return sdp;
    const pt = opusMatch[1];
    // Look for existing fmtp line for this payload type
    const fmtpRegex = new RegExp(`a=fmtp:${pt}\\s+(.*)`, 'i');
    const fmtpMatch = sdp.match(fmtpRegex);
    const opusParams = {
      'maxaveragebitrate': '64000',   // 64kbps (default ~32kbps)
      'useinbandfec': '1',            // Forward Error Correction
      'usedtx': '0',                  // Disable discontinuous TX (prevents silent gaps)
    };
    if (fmtpMatch) {
      // Parse existing params and merge
      const existing = fmtpMatch[1];
      const parts = existing.split(';').map(s => s.trim());
      const paramMap = {};
      parts.forEach(p => {
        const [k, v] = p.split('=');
        if (k) paramMap[k.trim()] = v ? v.trim() : '';
      });
      Object.assign(paramMap, opusParams);
      const newFmtp = `a=fmtp:${pt} ` + Object.entries(paramMap).map(([k, v]) => `${k}=${v}`).join(';');
      sdp = sdp.replace(fmtpRegex, newFmtp);
    } else {
      // No fmtp line exists — add one after the rtpmap line
      const newFmtp = `a=fmtp:${pt} ` + Object.entries(opusParams).map(([k, v]) => `${k}=${v}`).join(';');
      sdp = sdp.replace(opusMatch[0], opusMatch[0] + '\r\n' + newFmtp);
    }
    return sdp;
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
    autoGainControl = false,
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
    autoGainControl = false,
    iceServers = null,
    iceTransportPolicy = null,
  } = {}) {
    _lastError = null;
    _micIceRecvCount = 0;
    if (micPc) { micPc.close(); micPc = null; }

    if (!micStream && mic) {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation, noiseSuppression, autoGainControl },
          video: false,
        });
        micActive = micStream.getAudioTracks().length > 0;
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

    // Add mic tracks if available, otherwise add recvonly transceiver
    // so TD can still send audio downlink even when mic is off
    if (micStream && micStream.getAudioTracks().length > 0) {
      micStream.getTracks().forEach(track => micPc.addTrack(track, micStream));
    } else {
      micPc.addTransceiver('audio', { direction: 'recvonly' });
      micPc.addTransceiver('video', { direction: 'recvonly' });
      _log('No mic — added recvonly audio+video transceivers for TD downlink');
    }

    // Listen for incoming tracks from TD (TD -> Mobile audio/video streaming)
    micPc.ontrack = (event) => {
      const track = event.track;
      const stream = event.streams[0] || new MediaStream([track]);
      _log('Received track from TD: ' + track.kind);

      if (track.kind === 'audio') {
        // Audio downlink from TD → dedicated <audio> element
        let audioEl = document.getElementById('webrtc-td-audio');
        if (!audioEl) {
          audioEl = document.createElement('audio');
          audioEl.id = 'webrtc-td-audio';
          audioEl.autoplay = true;
          audioEl.playsInline = true;
          document.body.appendChild(audioEl);
        }
        audioEl.srcObject = stream;
        audioEl.play().catch(e => console.warn('[W2TD WebRTC] TD audio play failed:', e));
        // Set jitter buffer hint on audio receiver for smoother playback
        try {
          const receivers = micPc.getReceivers();
          const audioRecv = receivers.find(r => r.track && r.track.kind === 'audio');
          if (audioRecv && 'playoutDelayHint' in audioRecv) {
            audioRecv.playoutDelayHint = 0.15; // 150ms buffer to absorb jitter
            _log('Audio receiver playoutDelayHint set to 150ms');
          }
        } catch (e) { /* playoutDelayHint not supported */ }
      } else if (track.kind === 'video') {
        // Video downlink from TD → delegate display to app.js via callback
        let videoEl = document.getElementById('webrtc-td-stream');
        if (!videoEl) {
          videoEl = document.createElement('video');
          videoEl.id = 'webrtc-td-stream';
          videoEl.autoplay = true;
          videoEl.playsInline = true;
          videoEl.muted = false;
        }
        videoEl.srcObject = stream;
        videoEl.play().catch(e => console.warn('[W2TD WebRTC] TD video play failed:', e));
        _log('TD video track received');
        if (_onTdVideoTrack) _onTdVideoTrack(videoEl, track);
      }
    };

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
      const enhancedOffer = _enhanceOpusSdp(offer.sdp);
      await micPc.setLocalDescription({ type: 'offer', sdp: enhancedOffer });
      const sent = WSClient.send({ type: 'webrtc_offer', sdp: enhancedOffer });
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

  /** Renegotiate: create new offer on existing micPc to pick up TD's new audio tracks. */
  async function renegotiate() {
    if (!micPc || micPc.connectionState === 'closed') {
      _log('Renegotiate: no active PC');
      return;
    }
    try {
      const offer = await micPc.createOffer();
      await micPc.setLocalDescription(offer);
      const sent = WSClient.send({ type: 'webrtc_reoffer', sdp: offer.sdp });
      _log(sent ? 'Renegotiation offer sent to TD' : 'Renegotiation offer FAILED — WS not connected');
    } catch (e) {
      console.error('[W2TD WebRTC] renegotiate failed:', e);
      _log('Renegotiate failed: ' + (e.message || e));
    }
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

  /**
   * Handle TD-initiated offer (renegotiation).
   * TD calls createOffer after adding Audio Stream Out CHOP,
   * so the SDP now includes TD's outgoing audio track.
   * Browser sets remote description, creates answer, sends it back.
   */
  async function handleOffer(sdp) {
    if (!micPc || micPc.connectionState === 'closed') {
      _log('handleOffer: no active PC, ignoring TD offer');
      return;
    }
    try {
      await micPc.setRemoteDescription({ type: 'offer', sdp });
      const answer = await micPc.createAnswer();
      // Enhance Opus parameters for better audio quality before setting local description
      const enhancedSdp = _enhanceOpusSdp(answer.sdp);
      await micPc.setLocalDescription({ type: 'answer', sdp: enhancedSdp });
      const sent = WSClient.send({ type: 'webrtc_reanswer', sdp: enhancedSdp });
      _log(sent ? 'TD offer handled, answer sent (Opus enhanced)' : 'TD offer handled but answer FAILED — WS not connected');
    } catch (e) {
      console.error('[W2TD WebRTC] handleOffer failed:', e);
      _log('handleOffer failed: ' + (e.message || e));
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
  const CAM_REAR = 'rear';

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

  /** Acquire camera stream — facingMode: 'user' (front) or 'environment' (rear). */
  async function acquireCamera(facingMode = 'environment') {
    _lastError = null;
    const isFront = facingMode === 'user';
    const stream = isFront ? camFrontStream : camRearStream;
    if (stream && stream.getVideoTracks().length > 0) return true;
    if (stream) { stream.getTracks().forEach(t => t.stop()); }
    if (isFront) camFrontStream = null; else camRearStream = null;
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: facingMode },
          width: { ideal: _camResolution.width, max: Math.max(_camResolution.width, _camResolution.height) },
          height: { ideal: _camResolution.height, max: Math.max(_camResolution.width, _camResolution.height) },
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

  /** Start camera stream (front or rear) and send offer to TD. */
  async function startCamera(facingMode = 'environment', opts = {}) {
    _lastError = null;
    _lockCameraOrientation();
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
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facingMode },
            width: { ideal: _camResolution.width, max: Math.max(_camResolution.width, _camResolution.height) },
            height: { ideal: _camResolution.height, max: Math.max(_camResolution.width, _camResolution.height) },
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
      const sent = WSClient.send({ type: 'webrtc_offer_cam', sdp: offer.sdp, camType });
      _log(sent ? 'Cam ' + camType + ' offer sent' : 'Cam offer FAILED');
      return sent ? true : false;
    } catch (e) {
      _setCamState('failed');
      return false;
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
    _clearOrientationLock();
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

  function onStateChange(fn) { _onStateChange = fn; }
  function onCamStateChange(fn) { _onCamStateChange = fn; }
  function setOnLog(fn) { _onLog = fn; }

  // ── Private helpers ────────────────────────────────────────────────────────

  function _setMicState(state) { if (_onStateChange) _onStateChange(state); }
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
    const rearVid = document.getElementById('webrtc-preview-rear');
    const frontVid = document.getElementById('webrtc-preview-front');
    const hasRear = !!(camRearStream && camRearStream.getVideoTracks().length > 0);
    const hasFront = !!(camFrontStream && camFrontStream.getVideoTracks().length > 0);
    if (rearVid) {
      if (hasRear) { rearVid.srcObject = camRearStream; rearVid.classList.remove('hidden'); }
      else { rearVid.srcObject = null; rearVid.classList.add('hidden'); }
    }
    if (frontVid) {
      if (hasFront) { frontVid.srcObject = camFrontStream; frontVid.classList.remove('hidden'); }
      else { frontVid.srcObject = null; frontVid.classList.add('hidden'); }
    }
  }

  /** Update camera resolution from TD config and apply to active tracks. */
  async function setResolution(resString) {
    const key = (resString || '').toLowerCase().trim();
    const preset = _CAM_RESOLUTION_MAP[key];
    if (!preset) return;
    _camResolutionKey = key;
    if (preset.width === _camResolution.width && preset.height === _camResolution.height) {
      _log(`Camera resolution: ${key} (${preset.width}x${preset.height}) — no change`);
      return;
    }
    _camResolution = preset;
    _log(`Camera resolution config: ${key} → target ${preset.width}x${preset.height}`);
    for (const [label, stream] of [['rear', camRearStream], ['front', camFrontStream]]) {
      if (!stream) continue;
      const track = stream.getVideoTracks()[0];
      if (!track) continue;
      try {
        await track.applyConstraints({
          width: { ideal: preset.width, max: Math.max(preset.width, preset.height) },
          height: { ideal: preset.height, max: Math.max(preset.width, preset.height) },
        });
        const s = track.getSettings();
        _log(`Camera ${label} actual: ${s.width || '?'}x${s.height || '?'} (target ${preset.width}x${preset.height})`);
      } catch (e) {
        console.warn('[W2TD WebRTC] setResolution applyConstraints failed:', e.message);
      }
    }
  }

  /** Return current resolution config and actual track settings for diagnostic display. */
  function getCamResolutionInfo() {
    const getActual = (stream) => {
      const track = stream && stream.getVideoTracks()[0];
      if (!track) return null;
      const s = track.getSettings();
      return { width: s.width || 0, height: s.height || 0 };
    };
    return {
      key: _camResolutionKey,
      target: { width: _camResolution.width, height: _camResolution.height },
      actualRear: getActual(camRearStream),
      actualFront: getActual(camFrontStream),
    };
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

  /**
   * Pro: Toggle flashlight (torch) on/off.
   * Requires active rear camera stream.
   * iOS Safari: video element must be actively playing for torch to work.
   * Returns Promise<boolean> indicating success.
   */
  async function toggleFlashlight(state) {
    const stream = camRearStream;
    if (!stream) {
      console.warn('[W2TD WebRTC] Flashlight: No rear camera stream active');
      return false;
    }
    const track = stream.getVideoTracks()[0];
    if (!track) {
      console.warn('[W2TD WebRTC] Flashlight: No video track found');
      return false;
    }
    // iOS Safari: ensure video element is playing so torch constraint is honoured
    const rearVid = document.getElementById('webrtc-preview-rear');
    if (rearVid && rearVid.paused) {
      try { await rearVid.play(); } catch (_) { /* best-effort */ }
    }
    // Check torch capability before attempting
    if (typeof track.getCapabilities === 'function') {
      const caps = track.getCapabilities();
      if (!caps.torch) {
        console.warn('[W2TD WebRTC] Flashlight: torch not supported by this device/browser');
        return false;
      }
    }
    try {
      await track.applyConstraints({
        advanced: [{ torch: !!state }]
      });
      _log(`Flashlight ${state ? 'ON' : 'OFF'}`);
      return true;
    } catch (e) {
      console.error('[W2TD WebRTC] Flashlight toggle failed:', e);
      return false;
    }
  }

  return {
    // Mic
    acquireMic, start, stop, disconnect, renegotiate,
    handleAnswer, handleOffer, handleIce,
    onStateChange,
    isMicActive: () => micActive,
    isPCActive: () => micPc !== null,
    // Camera
    requestCameraPermission, acquireCamera, startCamera, stopCamera, disconnectCamera,
    stopCameraFront, stopCameraRear,
    handleCameraAnswer, handleCameraIce,
    onCamStateChange,
    setResolution, getCamResolutionInfo,
    CAM_FRONT, CAM_REAR,
    isCameraFrontActive: () => !!(camFrontStream && camFrontStream.getVideoTracks().length),
    isCameraRearActive: () => !!(camRearStream && camRearStream.getVideoTracks().length),
    isCameraActive: () => !!(camFrontStream?.getVideoTracks().length || camRearStream?.getVideoTracks().length),
    isCamPCActive: () => camFrontPc !== null || camRearPc !== null,
    // Shared
    isActive: () => micActive || !!(camFrontStream?.getVideoTracks().length || camRearStream?.getVideoTracks().length),
    setOnLog,
    getMicLevel,
    getLastError: () => _lastError,
    // Pro
    toggleFlashlight,
    setOnTdVideoTrack: (fn) => { _onTdVideoTrack = fn; },
    isTdVideoActive: () => {
      const v = document.getElementById('webrtc-td-stream');
      return !!(v && v.srcObject);
    },
  };
})();
