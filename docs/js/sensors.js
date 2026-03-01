/**
 * WOB Sensor Module
 * Detects available sensors, handles permissions, collects and normalizes data.
 */
const SensorModule = (() => {
  const availability = {
    motion: false,
    orientation: false,
    geolocation: false,
    touch: false,
  };

  const selected = {
    motion: true,
    orientation: true,
    geolocation: false,
    touch: true,
  };

  const data = {
    accel: { x: 0, y: 0, z: 0 },
    gyro: { alpha: 0, beta: 0, gamma: 0 },
    orient: { alpha: 0, beta: 0, gamma: 0 },
    geo: { lat: 0, lon: 0 },
  };

  let sensorsEnabled = false;
  let motionListener = null;
  let orientListener = null;
  let geoWatchId = null;
  let motionDataReceived = false;
  let orientDataReceived = false;

  // Simulation
  let simulationMode = false;
  let simInterval = null;
  let simTime = 0;

  const ACCEL_MAX = 9.81;
  const GYRO_MAX = 360;

  // Debug callback
  let onDebug = null;

  function debug(msg) {
    console.log('[Sensors]', msg);
    if (onDebug) onDebug(msg);
  }

  function detect() {
    availability.motion = typeof DeviceMotionEvent !== 'undefined';
    availability.orientation = typeof DeviceOrientationEvent !== 'undefined';
    availability.geolocation = 'geolocation' in navigator;
    availability.touch = 'ontouchstart' in window || typeof TouchEvent !== 'undefined';
    return { ...availability };
  }

  function isMobileDevice() {
    return /Android|iPhone|iPad|iPod/i.test(navigator.userAgent) ||
           ('ontouchstart' in window);
  }

  function needsPermissionRequest() {
    return (
      typeof DeviceMotionEvent !== 'undefined' &&
      typeof DeviceMotionEvent.requestPermission === 'function'
    );
  }

  /**
   * Request iOS permissions - MUST be called directly from user tap
   */
  async function requestPermissions() {
    const results = { motion: false, orientation: false, geo: false };

    // iOS DeviceMotion permission
    if (typeof DeviceMotionEvent !== 'undefined' &&
        typeof DeviceMotionEvent.requestPermission === 'function') {
      try {
        debug('Requesting DeviceMotion permission...');
        const perm = await DeviceMotionEvent.requestPermission();
        results.motion = perm === 'granted';
        debug('Motion permission: ' + perm);
      } catch (e) {
        debug('Motion permission error: ' + e.message);
      }
    } else {
      results.motion = availability.motion;
      debug('Motion: no permission needed (non-iOS)');
    }

    // iOS DeviceOrientation permission
    if (typeof DeviceOrientationEvent !== 'undefined' &&
        typeof DeviceOrientationEvent.requestPermission === 'function') {
      try {
        debug('Requesting DeviceOrientation permission...');
        const perm = await DeviceOrientationEvent.requestPermission();
        results.orientation = perm === 'granted';
        debug('Orientation permission: ' + perm);
      } catch (e) {
        debug('Orientation permission error: ' + e.message);
      }
    } else {
      results.orientation = availability.orientation;
      debug('Orientation: no permission needed');
    }

    // Geolocation
    if (availability.geolocation && selected.geolocation) {
      try {
        await new Promise((resolve, reject) => {
          navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 5000 });
        });
        results.geo = true;
      } catch (e) {
        debug('Geo permission error: ' + e.message);
      }
    }

    return results;
  }

  function toggleSensor(key) {
    if (key in selected) {
      selected[key] = !selected[key];
      if (sensorsEnabled && key === 'geolocation') {
        if (selected.geolocation && geoWatchId === null) {
          startGeolocation();
        } else if (!selected.geolocation && geoWatchId !== null) {
          navigator.geolocation.clearWatch(geoWatchId);
          geoWatchId = null;
          data.geo.lat = 0;
          data.geo.lon = 0;
        }
      }
    }
    return { ...selected };
  }

  function setSensorSelected(key, value) {
    if (key in selected) selected[key] = value;
  }

  /**
   * Start listening - call AFTER requestPermissions on iOS
   */
  function startListening() {
    // Clean up previous listeners first
    stopListening();
    sensorsEnabled = true;
    motionDataReceived = false;
    orientDataReceived = false;

    if (!isMobileDevice()) {
      debug('PC detected - simulation mode');
      startSimulation();
      return;
    }

    debug('Starting sensor listeners...');

    // DeviceMotion
    if (availability.motion) {
      motionListener = (e) => {
        const a = e.accelerationIncludingGravity;
        if (a) {
          if (!motionDataReceived) {
            motionDataReceived = true;
            debug('Motion data flowing! accel=' +
              (a.x != null ? a.x.toFixed(2) : 'null') + ',' +
              (a.y != null ? a.y.toFixed(2) : 'null') + ',' +
              (a.z != null ? a.z.toFixed(2) : 'null'));
          }
          // Raw m/s² (gravity ~9.81 included)
          data.accel.x = a.x || 0;
          data.accel.y = a.y || 0;
          data.accel.z = a.z || 0;
        }

        const r = e.rotationRate;
        if (r) {
          // Raw deg/s
          data.gyro.alpha = r.alpha || 0;
          data.gyro.beta  = r.beta  || 0;
          data.gyro.gamma = r.gamma || 0;
        }
      };
      window.addEventListener('devicemotion', motionListener);
      debug('devicemotion listener added');
    } else {
      debug('DeviceMotionEvent not available');
    }

    // DeviceOrientation
    if (availability.orientation) {
      orientListener = (e) => {
        if (!orientDataReceived && e.alpha !== null) {
          orientDataReceived = true;
          debug('Orientation data flowing! a=' +
            (e.alpha ? e.alpha.toFixed(1) : 'null'));
        }
        // Raw degrees
        data.orient.alpha = e.alpha || 0;  // 0 ~ 360
        data.orient.beta  = e.beta  || 0;  // -180 ~ 180
        data.orient.gamma = e.gamma || 0;  // -90 ~ 90
      };
      window.addEventListener('deviceorientation', orientListener);
      debug('deviceorientation listener added');
    }

    // Geolocation
    if (availability.geolocation && selected.geolocation) {
      startGeolocation();
    }

    // Check if data arrives after 2 seconds
    setTimeout(() => {
      if (sensorsEnabled && !simulationMode) {
        if (!motionDataReceived && !orientDataReceived) {
          debug('WARNING: No sensor data after 2s. Permission may be denied.');
        }
      }
    }, 2000);
  }

  function startGeolocation() {
    geoWatchId = navigator.geolocation.watchPosition(
      (pos) => {
        data.geo.lat = pos.coords.latitude;
        data.geo.lon = pos.coords.longitude;
      },
      (err) => debug('Geo error: ' + err.message),
      { enableHighAccuracy: true, maximumAge: 1000 }
    );
  }

  function startSimulation() {
    simulationMode = true;
    simInterval = setInterval(() => {
      simTime += 0.03;
      // Simulate raw m/s² (gravity ~9.81 on z when flat)
      data.accel.x = Math.sin(simTime * 1.2) * 2.5;
      data.accel.y = Math.cos(simTime * 0.8) * 2.0;
      data.accel.z = Math.sin(simTime * 0.5) * 1.0 + 9.81;
      // Simulate raw deg/s
      data.gyro.alpha = Math.sin(simTime * 2.0) * 45;
      data.gyro.beta  = Math.cos(simTime * 1.5) * 30;
      data.gyro.gamma = Math.sin(simTime * 1.8) * 40;
      // Simulate raw degrees
      data.orient.alpha = ((Math.sin(simTime * 0.3) + 1) / 2) * 360;  // 0~360
      data.orient.beta  = Math.sin(simTime * 0.4) * 90;                // -90~90
      data.orient.gamma = Math.sin(simTime * 0.5) * 45;                // -45~45
    }, 30);
  }

  function stopListening() {
    sensorsEnabled = false;
    simulationMode = false;

    if (simInterval) { clearInterval(simInterval); simInterval = null; }
    if (motionListener) {
      window.removeEventListener('devicemotion', motionListener);
      motionListener = null;
    }
    if (orientListener) {
      window.removeEventListener('deviceorientation', orientListener);
      orientListener = null;
    }
    if (geoWatchId !== null) {
      navigator.geolocation.clearWatch(geoWatchId);
      geoWatchId = null;
    }

    // Reset data
    data.accel.x = data.accel.y = data.accel.z = 0;
    data.gyro.alpha = data.gyro.beta = data.gyro.gamma = 0;
    data.orient.alpha = data.orient.beta = data.orient.gamma = 0;
    data.geo.lat = data.geo.lon = 0;
  }

  function getData() {
    return {
      accel: selected.motion ? { ...data.accel } : null,
      gyro: selected.motion ? { ...data.gyro } : null,
      orient: selected.orientation ? { ...data.orient } : null,
      geo: selected.geolocation ? { ...data.geo } : null,
    };
  }

  function getAllData() {
    return {
      accel: { ...data.accel },
      gyro: { ...data.gyro },
      orient: { ...data.orient },
      geo: { ...data.geo },
    };
  }

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  return {
    detect,
    needsPermissionRequest,
    requestPermissions,
    startListening,
    stopListening,
    toggleSensor,
    setSensorSelected,
    getData,
    getAllData,
    getAvailability: () => ({ ...availability }),
    getSelected: () => ({ ...selected }),
    isEnabled: () => sensorsEnabled,
    isSimulating: () => simulationMode,
    setDebugCallback: (cb) => { onDebug = cb; },
    hasDataFlowing: () => motionDataReceived || orientDataReceived,
  };
})();
