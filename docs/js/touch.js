/**
 * W2TD Touch Module
 * Multi-touch tracking with coordinate normalization.
 */
const TouchModule = (() => {
  // Active touches: Map<identifier, {id, x, y, state}>
  const activeTouches = new Map();
  let targetElement = null;
  let onTouchCallback = null;
  let enabled = false;

  /**
   * Initialize touch tracking on a given element
   */
  function init(element, callback) {
    targetElement = element;
    onTouchCallback = callback;

    // Prevent default to avoid scrolling/zooming
    element.addEventListener('touchstart', handleTouchStart, { passive: false });
    element.addEventListener('touchmove', handleTouchMove, { passive: false });
    element.addEventListener('touchend', handleTouchEnd, { passive: false });
    element.addEventListener('touchcancel', handleTouchEnd, { passive: false });

    enabled = true;
  }

  function _isControl(el) {
    return el && (el.tagName === 'BUTTON' || el.closest('.touch-pad-controls'));
  }

  function handleTouchStart(e) {
    if (_isControl(e.target)) return;
    e.preventDefault();
    updateTouches(e.touches, 'start');
  }

  function handleTouchMove(e) {
    if (_isControl(e.target)) return;
    e.preventDefault();
    updateTouches(e.touches, 'move');
  }

  function handleTouchEnd(e) {
    if (_isControl(e.target)) return;
    e.preventDefault();
    // Find ended touches
    const currentIds = new Set();
    for (let i = 0; i < e.touches.length; i++) {
      currentIds.add(e.touches[i].identifier);
    }

    // Mark removed touches
    for (const [id, touch] of activeTouches) {
      if (!currentIds.has(id)) {
        touch.state = 0; // up
        if (onTouchCallback) {
          onTouchCallback(getSnapshot());
        }
        activeTouches.delete(id);
      }
    }

    // Update remaining
    updateTouches(e.touches, 'end');
  }

  function updateTouches(touchList, eventType) {
    if (!targetElement) return;

    const rect = targetElement.getBoundingClientRect();

    for (let i = 0; i < touchList.length; i++) {
      const t = touchList[i];
      const id = t.identifier;

      // Normalize coordinates to 0.0 - 1.0
      const x = clamp((t.clientX - rect.left) / rect.width, 0, 1);
      const y = clamp((t.clientY - rect.top) / rect.height, 0, 1);

      activeTouches.set(id, {
        id,
        x: parseFloat(x.toFixed(4)),
        y: parseFloat(y.toFixed(4)),
        state: 1, // down
      });
    }

    if (onTouchCallback) {
      onTouchCallback(getSnapshot());
    }
  }

  /**
   * Get current touch state snapshot
   */
  function getSnapshot() {
    const touches = [];
    for (const [, touch] of activeTouches) {
      touches.push({ ...touch });
    }
    return {
      touches,
      count: activeTouches.size,
    };
  }

  function destroy() {
    if (targetElement) {
      targetElement.removeEventListener('touchstart', handleTouchStart);
      targetElement.removeEventListener('touchmove', handleTouchMove);
      targetElement.removeEventListener('touchend', handleTouchEnd);
      targetElement.removeEventListener('touchcancel', handleTouchEnd);
    }
    activeTouches.clear();
    enabled = false;
  }

  function clamp(val, min, max) {
    return Math.max(min, Math.min(max, val));
  }

  return {
    init,
    destroy,
    getSnapshot,
    getActiveTouches: () => activeTouches,
    isEnabled: () => enabled,
  };
})();
