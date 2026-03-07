/**
 * W2TD Pro Audio Module
 * Handles Web Audio API context, audio caching, and synchronized playback.
 * Audio files are served from TouchDesigner's local audio/ directory.
 */
const AudioModule = (() => {
  let audioContext = null;
  let audioCache = new Map(); // filename -> AudioBuffer
  let isUnlocked = false;
  let baseUrl = '/audio/'; // TD Web Server DAT serves from touchdesigner/audio/

  /**
   * Unlock AudioContext on first user interaction (required by browsers).
   * Call this on touch/click events.
   */
  function unlock() {
    if (isUnlocked || audioContext) return;
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      isUnlocked = true;
      console.log('[W2TD Audio] AudioContext unlocked');
    } catch (e) {
      console.error('[W2TD Audio] AudioContext creation failed:', e);
    }
  }

  /**
   * Load and cache an audio file.
   * Returns Promise<AudioBuffer> or null on error.
   */
  async function loadAudio(filename) {
    if (!audioContext) {
      console.warn('[W2TD Audio] AudioContext not unlocked — call unlock() first');
      return null;
    }

    // Return cached buffer if available
    if (audioCache.has(filename)) {
      return audioCache.get(filename);
    }

    try {
      const url = baseUrl + filename;
      console.log(`[W2TD Audio] Fetching: ${url}`);
      const response = await fetch(url);
      if (!response.ok) {
        console.error(`[W2TD Audio] Failed to load ${filename}: HTTP ${response.status} from ${url}`);
        return null;
      }
      const arrayBuffer = await response.arrayBuffer();
      const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
      audioCache.set(filename, audioBuffer);
      console.log(`[W2TD Audio] Cached: ${filename}`);
      return audioBuffer;
    } catch (e) {
      console.error(`[W2TD Audio] Load error for ${filename}:`, e);
      return null;
    }
  }

  /**
   * Play an audio file immediately.
   * If not cached, loads it first (may have delay).
   * Returns Promise<boolean> indicating success.
   */
  async function play(filename, options = {}) {
    if (!audioContext) {
      unlock(); // Try to unlock if not already
      if (!audioContext) {
        console.warn('[W2TD Audio] Cannot play — AudioContext not available (tap screen first)');
        return false;
      }
    }

    // Resume context if suspended (required by some browsers)
    if (audioContext.state === 'suspended') {
      try {
        await audioContext.resume();
      } catch (e) {
        console.warn('[W2TD Audio] AudioContext resume failed (tap screen first):', e);
        return false;
      }
    }
    console.log(`[W2TD Audio] Playing: ${filename} (baseUrl: ${baseUrl}, ctx: ${audioContext.state})`);

    const buffer = await loadAudio(filename);
    if (!buffer) return false;

    try {
      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);

      if (options.volume !== undefined) {
        const gainNode = audioContext.createGain();
        gainNode.gain.value = Math.max(0, Math.min(1, options.volume));
        source.disconnect();
        source.connect(gainNode);
        gainNode.connect(audioContext.destination);
      }

      if (options.startTime !== undefined) {
        // Scheduled playback (for synchronization)
        source.start(audioContext.currentTime + options.startTime);
      } else {
        source.start(0);
      }

      source.onended = () => {
        if (options.onEnded) options.onEnded();
      };

      return true;
    } catch (e) {
      console.error(`[W2TD Audio] Play error for ${filename}:`, e);
      return false;
    }
  }

  /**
   * Preload audio files (call after unlock).
   * Returns Promise that resolves when all files are loaded.
   */
  async function preload(filenames) {
    if (!audioContext) {
      unlock();
      if (!audioContext) return Promise.resolve();
    }
    const promises = filenames.map(f => loadAudio(f));
    await Promise.all(promises);
  }

  /**
   * Clear audio cache.
   */
  function clearCache() {
    audioCache.clear();
  }

  /**
   * Set base URL for audio files (default: '/audio/').
   */
  function setBaseUrl(url) {
    baseUrl = url.endsWith('/') ? url : url + '/';
  }

  return {
    unlock,
    loadAudio,
    play,
    preload,
    clearCache,
    setBaseUrl,
    isUnlocked: () => isUnlocked,
    getContext: () => audioContext,
  };
})();
