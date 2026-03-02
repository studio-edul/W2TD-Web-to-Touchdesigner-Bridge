/**
 * W2TD WebSocket Client
 * Connects directly to TouchDesigner WebSocket DAT.
 * Sends flat JSON that TD can parse easily.
 */
const WSClient = (() => {
  let ws = null;
  let serverUrl = '';
  let connected = false;
  let reconnectTimer = null;
  let reconnectAttempts = 0;
  const MAX_RECONNECT_DELAY = 10000;

  let onStatusChange = null;
  let onErrorDetail = null;
  let onConfig = null;
  let onWebRTCSignal = null; // callback(msg) for webrtc_answer / webrtc_ice / webrtc_state
  let onHaptic = null; // callback(pattern) for haptic feedback
  let onDataAck = null; // callback() for data acknowledgment
  
  // Heartbeat
  let heartbeatInterval = null;
  let heartbeatTimeout = null;
  const HEARTBEAT_INTERVAL = 5000; // 5 seconds
  const HEARTBEAT_TIMEOUT = 10000; // 10 seconds (2 missed pongs = disconnect)

  // Packet counting
  let sentCount = 0;
  let lastCountTime = Date.now();
  let packetsPerSec = 0;

  /**
   * Connect to TouchDesigner WebSocket DAT
   */
  function connect(url, callbacks = {}) {
    onStatusChange = callbacks.onStatusChange || null;
    onErrorDetail = callbacks.onErrorDetail || null;
    onConfig = callbacks.onConfig || null;
    onWebRTCSignal = callbacks.onWebRTCSignal || null;
    onHaptic = callbacks.onHaptic || null;
    onDataAck = callbacks.onDataAck || null;
    reconnectAttempts = 0; // reset in case previous session was rejected

    // Strip any existing protocol prefix, then re-add the correct one
    url = url.replace(/^(wss?|https?):\/\//, '');
    url = (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + url;
    serverUrl = url;
    _createConnection();
  }

  function _createConnection() {
    if (ws) {
      ws.close();
      ws = null;
    }

    _updateStatus('connecting');

    try {
      ws = new WebSocket(serverUrl);
    } catch (e) {
      const msg = 'WebSocket 생성 실패: ' + (e.message || e);
      console.error('[WS]', msg);
      _reportError(msg);
      _updateStatus('error');
      _scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      connected = true;
      reconnectAttempts = 0;
      _updateStatus('connected');
      _reportError(null);
      console.log('[WS] Connected to TD:', serverUrl);
      _startHeartbeat();
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'ack') {
          if (onStatusChange) onStatusChange('connected');
          console.log('[WS] TD ack, slot:', msg.slot, '| TD version:', msg.td_version || 'unknown');
        } else if (msg.type === 'config') {
          if (onConfig) onConfig(msg);
        } else if (msg.type === 'webrtc_answer' || msg.type === 'webrtc_ice' || msg.type === 'webrtc_state' ||
                   msg.type === 'webrtc_answer_cam' || msg.type === 'webrtc_ice_cam' || msg.type === 'cam_receiver_ready') {
          if (onWebRTCSignal) onWebRTCSignal(msg);
        } else if (msg.type === 'haptic') {
          // Haptic feedback (pattern or state)
          if (onHaptic) {
            // Pass entire message object (supports both pattern and state)
            onHaptic(msg);
          }
        } else if (msg.type === 'ping') {
          // TD heartbeat ping → respond with pong
          send({ type: 'pong' });
        } else if (msg.type === 'pong') {
          // TD heartbeat pong response → reset timeout
          _resetHeartbeatTimeout();
        } else if (msg.type === 'data_ack') {
          // TD data acknowledgment → show indicator
          if (onDataAck) onDataAck();
        } else if (msg.type === 'rejected') {
          // Server full — cancel reconnect and surface the reason
          if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
          reconnectAttempts = 999; // prevent further auto-reconnect
          _reportError(msg.reason || 'Server full');
          if (onStatusChange) onStatusChange('rejected');
          ws.close(1000);
        }
      } catch (e) { /* ignore non-JSON */ }
    };

    ws.onclose = (event) => {
      connected = false;
      _stopHeartbeat();
      const code = event.code;
      const reason = event.reason || '';
      const msg = _getCloseMessage(code, reason, serverUrl);
      _reportError(msg);
      _updateStatus(code === 1000 ? 'disconnected' : 'error');
      console.log('[WS] Closed:', code, reason || '(no reason)');
      if (code !== 1000) _scheduleReconnect();
    };

    ws.onerror = () => {
      _updateStatus('error');
      if (!ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
        _reportError('연결 거부/타임아웃: ' + serverUrl + ' - 서버 없음, 방화벽, IP/포트 확인');
      }
    };
  }

  function _getCloseMessage(code, reason, url) {
    const hints = {
      1006: 'Connection failed (no server response). Check: IP/port, firewall, TD Web Server DAT active, TLS OFF for ngrok',
      1002: 'Protocol error (TD may not support WebSocket)',
      1011: 'Server-side error',
      1015: 'TLS error (wss:// related)',
    };
    const hint = hints[code] || ('code ' + code);
    return reason ? reason + ' | ' + hint : hint + ' | URL: ' + url;
  }

  function _reportError(msg) {
    if (onErrorDetail) onErrorDetail(msg);
  }

  function _scheduleReconnect() {
    if (reconnectTimer) return;
    const delay = Math.min(1000 * Math.pow(1.5, reconnectAttempts), MAX_RECONNECT_DELAY);
    reconnectAttempts++;
    _updateStatus('reconnecting');

    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      _createConnection();
    }, delay);
  }

  function _updateStatus(status) {
    if (onStatusChange) onStatusChange(status);
  }

  /**
   * Send raw JSON string to TD
   */
  function send(data) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    try {
      ws.send(JSON.stringify(data));
      sentCount++;
      _updatePacketRate();
      return true;
    } catch (e) {
      console.error('[WS] Send error:', e);
      return false;
    }
  }

  /**
   * Send sensor data as flat JSON for easy TD parsing
   * Format: { type, ax, ay, az, gα, gβ, gγ, oα, oβ, oγ, lat, lon }
   */
  function sendSensorData(sensorData) {
    const msg = { type: 'sensor' };

    // Only include selected sensors (non-null)
    if (sensorData.accel) {
      msg.ax = sensorData.accel.x;
      msg.ay = sensorData.accel.y;
      msg.az = sensorData.accel.z;
    }
    if (sensorData.gyro) {
      msg.ga = sensorData.gyro.alpha;
      msg.gb = sensorData.gyro.beta;
      msg.gg = sensorData.gyro.gamma;
    }
    if (sensorData.orient) {
      msg.oa = sensorData.orient.alpha;
      msg.ob = sensorData.orient.beta;
      msg.og = sensorData.orient.gamma;
    }
    if (sensorData.geo) {
      msg.lat = sensorData.geo.lat;
      msg.lon = sensorData.geo.lon;
    }

    return send(msg);
  }

  /**
   * Send touch data
   * Format: { type, count, t0x, t0y, t0s, t1x, t1y, t1s, ... }
   */
  function sendTouchData(touchData) {
    const msg = {
      type: 'touch',
      count: touchData.count,
    };
    touchData.touches.forEach((t, idx) => {
      msg[`t${idx}x`] = t.x;
      msg[`t${idx}y`] = t.y;
      msg[`t${idx}s`] = t.state;
    });
    return send(msg);
  }

  function _updatePacketRate() {
    const now = Date.now();
    const elapsed = now - lastCountTime;
    if (elapsed >= 1000) {
      packetsPerSec = Math.round(sentCount / (elapsed / 1000));
      sentCount = 0;
      lastCountTime = now;
    }
  }

  function _startHeartbeat() {
    _stopHeartbeat();
    // Send ping every HEARTBEAT_INTERVAL
    heartbeatInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        send({ type: 'ping' });
        // Start timeout only if one isn't already running
        // (cleared on pong; if still pending, the old deadline stands)
        if (!heartbeatTimeout) {
          _startHeartbeatTimeout();
        }
      }
    }, HEARTBEAT_INTERVAL);
  }

  function _stopHeartbeat() {
    if (heartbeatInterval) {
      clearInterval(heartbeatInterval);
      heartbeatInterval = null;
    }
    if (heartbeatTimeout) {
      clearTimeout(heartbeatTimeout);
      heartbeatTimeout = null;
    }
  }

  function _startHeartbeatTimeout() {
    heartbeatTimeout = setTimeout(() => {
      heartbeatTimeout = null;
      console.warn('[WS] Heartbeat timeout — no pong received, closing');
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close(1006, 'Heartbeat timeout');
      }
    }, HEARTBEAT_TIMEOUT);
  }

  function _resetHeartbeatTimeout() {
    if (heartbeatTimeout) {
      clearTimeout(heartbeatTimeout);
      heartbeatTimeout = null;
    }
  }

  function disconnect() {
    _stopHeartbeat();
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    reconnectAttempts = 0;
    if (ws) {
      ws.onclose = null;
      ws.close();
      ws = null;
    }
    connected = false;
    _updateStatus('disconnected');
  }

  return {
    connect,
    disconnect,
    send,
    sendSensorData,
    sendTouchData,
    isConnected: () => connected,
    getPacketsPerSec: () => packetsPerSec,
  };
})();
