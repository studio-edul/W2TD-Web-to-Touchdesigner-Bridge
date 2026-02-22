/**
 * WOB WebRTC Module
 * Handles camera/mic capture and WebRTC signaling via existing WebSocket.
 * Signaling server = TD Web Server DAT (no separate signaling server needed).
 */
const WebRTCModule = (() => {
  const ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    // Free TURN for cross-network fallback
    {
      urls: 'turn:openrelay.metered.ca:80',
      username: 'openrelayproject',
      credential: 'openrelayproject',
    },
    {
      urls: 'turn:openrelay.metered.ca:443',
      username: 'openrelayproject',
      credential: 'openrelayproject',
    },
  ];

  let pc = null;           // RTCPeerConnection
  let localStream = null;  // MediaStream from getUserMedia
  let cameraActive = false;
  let micActive = false;
  let _onStateChange = null; // callback(state) where state = 'connecting'|'connected'|'failed'|'closed'
  let _lastError = null;   // last getUserMedia error name (e.g. 'NotAllowedError')

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Start camera and/or mic, create RTCPeerConnection, send offer via WS.
   * @param {object} opts - { camera: bool, mic: bool }
   */
  async function start({ camera = true, mic = true } = {}) {
    _lastError = null;
    if (pc) await stop();

    // 1. Get user media
    const constraints = { video: camera, audio: mic };
    try {
      localStream = await navigator.mediaDevices.getUserMedia(constraints);
      cameraActive = camera && localStream.getVideoTracks().length > 0;
      micActive = mic && localStream.getAudioTracks().length > 0;
      console.log('[WOB WebRTC] getUserMedia OK — camera:', cameraActive, 'mic:', micActive);
    } catch (e) {
      _lastError = e.name || 'unknown';
      console.error('[WOB WebRTC] getUserMedia failed:', e.name, e.message);
      _setState('failed');
      return false;
    }

    // 2. Show local preview if camera is active
    _updatePreview(localStream);

    // 3. Create peer connection
    pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

    // Add local tracks
    localStream.getTracks().forEach(track => pc.addTrack(track, localStream));

    // ICE candidates → send via WebSocket
    pc.onicecandidate = ({ candidate }) => {
      if (!candidate) return; // null = end-of-candidates, TD handles this
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
      WSClient.send({ type: 'webrtc_offer', sdp: offer.sdp });
      console.log('[WOB WebRTC] Offer sent to TD');
    } catch (e) {
      console.error('[WOB WebRTC] createOffer failed:', e);
      _setState('failed');
    }
  }

  /** Stop all streams and close peer connection. */
  async function stop() {
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
    try {
      await pc.addIceCandidate(new RTCIceCandidate({ candidate, sdpMLineIndex, sdpMid }));
    } catch (e) {
      console.error('[WOB WebRTC] addIceCandidate failed:', e);
    }
  }

  /** Register a state change callback: fn(state) */
  function onStateChange(fn) {
    _onStateChange = fn;
  }

  function isActive() {
    return cameraActive || micActive;
  }

  function isCameraActive() { return cameraActive; }
  function isMicActive() { return micActive; }

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

  return { start, stop, handleAnswer, handleIce, onStateChange, isActive, isCameraActive, isMicActive,
           getLastError: () => _lastError };
})();
