/**
 * W2TD Canvas Runner (Pro)
 * Receives JS sketch code from TD over WebSocket and executes it against
 * #render-canvas. Handles HiDPI sizing, auto-teardown of the previous sketch,
 * flat sensor injection, and error reporting back to TD.
 */
const CanvasRunner = (() => {
  let canvasEl = null;
  let vizContainer = null;
  let rafIds = [];
  let userCleanup = null;
  let active = false;
  let resizeListener = null;

  function _canvas() {
    if (!canvasEl) canvasEl = document.getElementById('render-canvas');
    return canvasEl;
  }

  function _vizContainer() {
    if (!vizContainer) vizContainer = document.getElementById('viz-container');
    return vizContainer;
  }

  /**
   * Size canvas to viewport * devicePixelRatio. CSS size stays in CSS px,
   * backing store is physical px — sketches that use canvas.width/height
   * automatically render sharp on HiDPI.
   */
  function _resizeCanvas() {
    const c = _canvas();
    if (!c) return;
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    c.style.width = w + 'px';
    c.style.height = h + 'px';
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
  }

  /**
   * Flat sensor snapshot — keys mirror the TD sensor_table columns
   * so keys sketch authors see match what TD stores.
   */
  function getSensors() {
    const out = {
      ax: 0, ay: 0, az: 0,
      ga: 0, gb: 0, gg: 0,
      oa: 0, ob: 0, og: 0,
      lat: 0, lon: 0,
      touch_count: 0,
    };
    if (typeof SensorModule !== 'undefined') {
      const s = SensorModule.getAllData ? SensorModule.getAllData() : null;
      if (s) {
        if (s.accel)  { out.ax = s.accel.x;  out.ay = s.accel.y;  out.az = s.accel.z; }
        if (s.gyro)   { out.ga = s.gyro.alpha;  out.gb = s.gyro.beta;  out.gg = s.gyro.gamma; }
        if (s.orient) { out.oa = s.orient.alpha; out.ob = s.orient.beta; out.og = s.orient.gamma; }
        if (s.geo)    { out.lat = s.geo.lat; out.lon = s.geo.lon; }
      }
    }
    if (typeof TouchModule !== 'undefined' && TouchModule.getSnapshot) {
      const t = TouchModule.getSnapshot();
      out.touch_count = t.count || 0;
      (t.touches || []).forEach((tt, i) => {
        out[`t${i}x`] = tt.x;
        out[`t${i}y`] = tt.y;
        out[`t${i}s`] = tt.state;
      });
    }
    return out;
  }

  function _requestFrame(cb) {
    const id = requestAnimationFrame((ts) => {
      rafIds = rafIds.filter(x => x !== id);
      try {
        cb(ts);
      } catch (e) {
        _reportError(e);
      }
    });
    rafIds.push(id);
    return id;
  }

  function _cancelAllFrames() {
    rafIds.forEach(id => cancelAnimationFrame(id));
    rafIds = [];
  }

  function _runUserCleanup() {
    if (typeof userCleanup === 'function') {
      try { userCleanup(); } catch (e) { console.warn('[CanvasRunner] cleanup error:', e); }
    }
    userCleanup = null;
  }

  function _show() {
    const c = _canvas();
    if (c) c.classList.remove('hidden');
    const v = _vizContainer();
    if (v) v.classList.add('hidden');
    if (!resizeListener) {
      resizeListener = () => _resizeCanvas();
      window.addEventListener('resize', resizeListener);
      window.addEventListener('orientationchange', resizeListener);
    }
    _resizeCanvas();
  }

  function _hide() {
    const c = _canvas();
    if (c) {
      c.classList.add('hidden');
      const ctx2d = c.getContext && c.getContext('2d');
      if (ctx2d) ctx2d.clearRect(0, 0, c.width, c.height);
    }
    const v = _vizContainer();
    if (v) v.classList.remove('hidden');
    if (resizeListener) {
      window.removeEventListener('resize', resizeListener);
      window.removeEventListener('orientationchange', resizeListener);
      resizeListener = null;
    }
  }

  function _reportError(err) {
    const message = (err && err.message) ? err.message : String(err);
    const stack = (err && err.stack) ? String(err.stack).split('\n').slice(0, 5).join('\n') : '';
    console.error('[CanvasRunner] sketch error:', err);
    if (typeof WSClient !== 'undefined' && WSClient.send) {
      WSClient.send({ type: 'canvas_error', message, stack });
    }
  }

  /**
   * Load and run a sketch. Tears down any previous sketch first.
   * The sketch receives (canvas, requestFrame, getSensors) as arguments
   * and may return a cleanup function that runs on the next load()/stop().
   */
  function load(code) {
    stop();
    if (!code || !String(code).trim()) return;
    _show();
    active = true;
    const c = _canvas();
    try {
      const fn = new Function('canvas', 'requestFrame', 'getSensors', code);
      const ret = fn(c, _requestFrame, getSensors);
      if (typeof ret === 'function') userCleanup = ret;
    } catch (e) {
      _reportError(e);
    }
  }

  function stop() {
    _cancelAllFrames();
    _runUserCleanup();
    if (active) _hide();
    active = false;
  }

  return {
    load,
    stop,
    isActive: () => active,
    getSensors,
  };
})();
