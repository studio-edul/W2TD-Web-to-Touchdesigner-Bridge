/**
 * WOB WebRTC Module
 * Handles camera/mic capture and WebRTC signaling via existing WebSocket.
 * Signaling server = TD Web Server DAT (no separate signaling server needed).
 */
const WebRTCModule = (() => {
  const DEFAULT_ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    // freeTURN (무료, 가입 불필요) — cross-network/터널용
    { urls: 'turn:freeturn.net:3478', username: 'free', credential: 'free' },
    { urls: 'turns:freeturn.net:5349', username: 'free', credential: 'free' },
    // openrelay 백업 (고정 인증은 일부 deprecated 가능)
    { urls: 'turn:openrelay.metered.ca:80', username: 'openrelayproject', credential: 'openrelayproject' },
    { urls: 'turns:openrelay.metered.ca:443', username: 'openrelayproject', credential: 'openrelayproject' },
  ];

  let pc = null;           // RTCPeerConnection
  let localStream = null;  // MediaStream from getUserMedia
  let cameraActive = false;
  let micActive = false;
  let _onStateChange = null; // callback(state) where state = 'connecting'|'connected'|'failed'|'closed'
  let _lastError = null;   // last getUserMedia error name (e.g. 'NotAllowedError')
  let _audioCtx = null;
  let _analyser = null;
  let _onLog = null;       // optional fn(msg) for debug log
  let _iceRecvCount = 0;

  function _log(msg) {
    if (_onLog) _onLog(msg);
    console.log('[WOB WebRTC]', msg);
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Start camera and/or mic, create RTCPeerConnection, send offer via WS.
   * @param {object} opts - { camera, mic, echoCancellation, noiseSuppression, autoGainControl }
   */
  async function start({
    camera = true,
    mic = true,
    echoCancellation = false,
    noiseSuppression = false,
    autoGainControl = false,
    iceServers = null,
    iceTransportPolicy = null,
  } = {}) {
    _lastError = null;
    _iceRecvCount = 0;
    if (pc) await stop();

    const constraints = {
      video: camera,
      audio: mic ? {
        echoCancellation,
        noiseSuppression,
        autoGainControl,
      } : false,
    };
    try {
      localStream = await navigator.mediaDevices.getUserMedia(constraints);
      cameraActive = camera && localStream.getVideoTracks().length > 0;
      micActive = mic && localStream.getAudioTracks().length > 0;
      _log('getUserMedia OK — camera:' + cameraActive + ' mic:' + micActive);
    } catch (e) {
      _lastError = e.name || 'unknown';
      console.error('[WOB WebRTC] getUserMedia failed:', e.name, e.message);
      _setState('failed');
      return false;
    }

    // 2. Show local preview if camera is active
    _updatePreview(localStream);

    // 2b. Set up audio analyser for mic level visualization
    if (micActive && localStream.getAudioTracks().length > 0) {
      try {
        _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const source = _audioCtx.createMediaStreamSource(localStream);
        _analyser = _audioCtx.createAnalyser();
        _analyser.fftSize = 256;
        _analyser.smoothingTimeConstant = 0.8;
        source.connect(_analyser);
      } catch (e) { console.warn('[WOB WebRTC] Audio analyser setup failed:', e); }
    }

    // 3. Create peer connection
    const ice = Array.isArray(iceServers) && iceServers.length ? iceServers : DEFAULT_ICE_SERVERS;
    const rtcConfig = { iceServers: ice };
    if (iceTransportPolicy === 'relay') {
      rtcConfig.iceTransportPolicy = 'relay';
    }
    pc = new RTCPeerConnection(rtcConfig);

    // Add local tracks
    localStream.getTracks().forEach(track => pc.addTrack(track, localStream));

    // ICE candidates → send via WebSocket
    let iceCount = 0;
    pc.onicecandidate = ({ candidate }) => {
      if (!candidate) return; // null = end-of-candidates, TD handles this
      iceCount++;
      if (iceCount <= 3) _log('ICE candidate #' + iceCount + ' sent');
      WSClient.send({
        type: 'webrtc_ice',
        candidate: candidate.candidate,
        sdpMLineIndex: candidate.sdpMLineIndex,
        sdpMid: candidate.sdpMid,
      });
    };

    pc.onconnectionstatechange = () => {
      const s = pc.connectionState;
      console.log('[WOB WebRTC] connectionState:', s);
      _setState(s);
      if (s === 'failed' || s === 'closed') stop();
    };

    pc.oniceconnectionstatechange = () => {
      console.log('[WOB WebRTC] iceConnectionState:', pc.iceConnectionState);
    };

    _setState('connecting');

    // 4. Create and send offer
    try {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const sent = WSClient.send({ type: 'webrtc_offer', sdp: offer.sdp });
      _log(sent ? 'Offer sent to TD' : 'Offer FAILED — WebSocket not connected');
    } catch (e) {
      console.error('[WOB WebRTC] createOffer failed:', e);
      _setState('failed');
    }
  }

  /** Stop all streams and close peer connection. */
  async function stop() {
    if (_audioCtx) { _audioCtx.close(); _audioCtx = null; }
    _analyser = null;
    if (localStream) {
      localStream.getTracks().forEach(t => t.stop());
      localStream = null;
    }
    if (pc) {
      pc.close();
      pc = null;
    }
    cameraActive = false;
    micActive = false;
    _updatePreview(null);
    _setState('closed');
    console.log('[WOB WebRTC] Stopped');
  }

  /** Handle webrtc_answer message from TD (via WebSocket). */
  async function handleAnswer(sdp) {
    if (!pc) return;
    try {
      await pc.setRemoteDescription({ type: 'answer', sdp });
      console.log('[WOB WebRTC] Remote description set (answer)');
    } catch (e) {
      console.error('[WOB WebRTC] setRemoteDescription failed:', e);
    }
  }

  /** Handle webrtc_ice message from TD (via WebSocket). */
  async function handleIce({ candidate, sdpMLineIndex, sdpMid }) {
    if (!pc || !candidate) return;
    _iceRecvCount++;
    if (_iceRecvCount <= 3) _log('ICE from TD #' + _iceRecvCount);
    try {
      await pc.addIceCandidate(new RTCIceCandidate({ candidate, sdpMLineIndex, sdpMid }));
    } catch (e) {
      _log('addIceCandidate failed: ' + (e.message || e));
    }
  }

  /** Register a state change callback: fn(state) */
  function onStateChange(fn) {
    _onStateChange = fn;
  }

  /** Register debug log callback: fn(msg) — appears in Log viewer */
  function setOnLog(fn) {
    _onLog = fn;
  }

  function isActive() {
    return cameraActive || micActive;
  }

  function isCameraActive() { return cameraActive; }
  function isMicActive() { return micActive; }

  /** Get current mic level (0–1) for visualization. */
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

  // ── Private helpers ────────────────────────────────────────────────────────

  function _setState(state) {
    if (_onStateChange) _onStateChange(state);
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

  return { start, stop, handleAnswer, handleIce, onStateChange, setOnLog, isActive, isCameraActive, isMicActive,
           getMicLevel, getLastError: () => _lastError };
})();
