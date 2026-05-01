"""
W2TD Position Estimator v2
==========================
Improved real-time 3D position tracking using numpy + scipy.

Improvements over v1:
  - scipy Butterworth causal lowpass  (better noise rejection than EMA)
    Falls back to EMA automatically if scipy is unavailable.
  - Retroactive ZUPT drift correction
    When stationary is detected, buffered velocity history is retroactively
    corrected, removing accumulated drift in position.
  - 2nd-order position integration  (p += v·dt + ½·a·dt²)
  - numpy-based rotation matrix

TD Setup (same as v1):
  1. Create a Base COMP (container)
  2. Inside it, create a DAT Execute DAT
     — Set "DATs" to: sensor_table
     — Enable "Table Change"
     — Paste this file as its content
  3. position_table is auto-created inside the same container
     Columns: slot | x | y | z | vx | vy | vz | stationary

  Reset from Python console:
      op('container/dat_execute').module.reset_slot(1)
      op('container/dat_execute').module.reset_all()

Coordinate system: X = East, Y = North, Z = up  (metres)
"""

import math
import time
import numpy as np
from collections import deque

try:
    from scipy.signal import butter, sosfilt_zi, sosfilt as _sosfilt
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False
    print('[W2TD Position v2] scipy not found — falling back to EMA filter. '
          'Install scipy for better noise rejection: pip install scipy')

# =============================================
# CONFIGURATION — edit these values to tune
# =============================================
SAMPLE_RATE      = 30      # Hz — expected sensor rate (used for filter design)

# --- Butterworth lowpass (scipy) ---
LPF_CUTOFF       = 8.0     # Hz — cutoff; motion is ~0-4 Hz, noise above this
LPF_ORDER        = 3       # filter order; higher = sharper rolloff, more latency

# --- EMA fallback (if scipy unavailable) ---
LPF_ALPHA        = 0.9     # 0 = max smooth, 1 = no filter

# --- Stationary detection ---
ZUPT_WINDOW      = 4       # rolling window size
ZUPT_MAG_THRESH  = 0.5     # m/s²   — mean accel magnitude threshold
ZUPT_VAR_THRESH  = 0.05    # (m/s²)² — accel variance threshold
ZUPT_GYRO_THRESH = 5.0     # deg/s  — gyro magnitude threshold
STOP_CONFIRM_FRAMES = 2    # moving → stationary: consecutive candidate frames

# --- Movement detection (stationary → moving) ---
# Lower = more sensitive (detects movement sooner); Higher = less jitter
MOVE_CONFIRM_FRAMES = 6    # stationary → moving: consecutive candidate frames

# --- Retroactive ZUPT drift correction ---
RETRO_FRAMES     = 12      # max frames to correct retroactively at each stop

# --- Velocity ---
VELOCITY_DECAY   = 0.7     # fraction remaining after 1 second (dt-based)
GRAVITY          = 9.81    # m/s²
MAX_DT           = 0.1     # seconds — dt upper clamp

# --- Anti-rebound ---
V_STOP           = 0.15    # m/s   — per-axis velocity clamp threshold
A_EPS            = 0.12    # m/s²  — near-zero accel deadband
V_EPS            = 0.04    # m/s   — near-zero velocity deadband
# =============================================


# ── Butterworth SOS coefficients (computed once, shared) ─────────────────────

_SOS = None

def _get_sos():
    global _SOS
    if _SOS is None and _HAS_SCIPY:
        nyq = 0.5 * SAMPLE_RATE
        wn  = min(LPF_CUTOFF / nyq, 0.99)
        _SOS = butter(LPF_ORDER, wn, btype='low', output='sos')
    return _SOS


# ── Per-slot estimator ────────────────────────────────────────────────────────

class PositionEstimator:

    def __init__(self):
        self.reset()

    # ------------------------------------------------------------------
    def reset(self):
        self.vx = self.vy = self.vz = 0.0
        self.px = self.py = self.pz = 0.0
        self.ax_f = self.ay_f = self.az_f = 0.0   # filtered linear accel
        self.last_t     = None
        self.stationary = True
        self.stop_count = 0
        self.move_count = 0
        self.history  = deque(maxlen=ZUPT_WINDOW)  # (ax_f, ay_f, az_f)
        self.v_buffer = deque(maxlen=RETRO_FRAMES) # (vx, vy, vz, dt)
        # Butterworth per-axis state
        self.zi_x = self.zi_y = self.zi_z = None
        self.using_butter = False

    # ------------------------------------------------------------------
    def _init_filter(self, seed_x, seed_y, seed_z):
        """Initialise filter state seeded to first sample (suppresses startup transient)."""
        sos = _get_sos()
        if sos is not None:
            zi = sosfilt_zi(sos)          # shape (n_sections, 2)
            self.zi_x = zi * seed_x
            self.zi_y = zi * seed_y
            self.zi_z = zi * seed_z
            self.using_butter = True
        else:
            self.using_butter = False
            self.ax_f = seed_x
            self.ay_f = seed_y
            self.az_f = seed_z

    # ------------------------------------------------------------------
    def _reset_filter_to_zero(self):
        """Reset filter state so stationary residual does not leak back in."""
        sos = _get_sos()
        if sos is not None:
            zi = sosfilt_zi(sos)
            self.zi_x = zi * 0.0
            self.zi_y = zi * 0.0
            self.zi_z = zi * 0.0
            self.using_butter = True
        self.ax_f = self.ay_f = self.az_f = 0.0

    # ------------------------------------------------------------------
    def _filter(self, lx, ly, lz):
        """Apply filter to one sample; updates self.ax_f/ay_f/az_f."""
        sos = _get_sos()
        if sos is not None and self.zi_x is not None:
            ox, self.zi_x = _sosfilt(sos, np.array([lx]), zi=self.zi_x)
            oy, self.zi_y = _sosfilt(sos, np.array([ly]), zi=self.zi_y)
            oz, self.zi_z = _sosfilt(sos, np.array([lz]), zi=self.zi_z)
            self.ax_f = float(ox[0])
            self.ay_f = float(oy[0])
            self.az_f = float(oz[0])
        else:
            self.ax_f += LPF_ALPHA * (lx - self.ax_f)
            self.ay_f += LPF_ALPHA * (ly - self.ay_f)
            self.az_f += LPF_ALPHA * (lz - self.az_f)

    # ------------------------------------------------------------------
    def _retroactive_zupt(self):
        """
        Retroactive drift correction at ZUPT trigger.

        Assumption: velocity should be 0 at the moment ZUPT fires.
        The drift (self.v at this moment) accumulated linearly since the last
        ZUPT event.  We subtract a linearly increasing correction from each
        buffered frame, then update the current position accordingly.
        """
        n = len(self.v_buffer)
        if n < 2:
            return

        v_end = np.array([self.vx, self.vy, self.vz])
        if np.linalg.norm(v_end) < 1e-6:
            return

        # Position correction: undo the linearly-drifting excess velocity
        dp = np.zeros(3)
        for i, (vxi, vyi, vzi, dti) in enumerate(self.v_buffer):
            excess = (i + 1) / n * v_end    # excess velocity at frame i
            dp -= excess * dti              # undo its position contribution

        self.px += dp[0]
        self.py += dp[1]
        self.pz += dp[2]
        self.v_buffer.clear()

    # ------------------------------------------------------------------
    def update(self, ax_raw, ay_raw, az_raw, oa, ob, og, ga, gb, gg):
        """
        ax_raw, ay_raw, az_raw : accelerationIncludingGravity  (m/s²)
        oa, ob, og             : DeviceOrientation alpha/beta/gamma (degrees)
        ga, gb, gg             : rotationRate alpha/beta/gamma (deg/s)
        Returns (px, py, pz) in metres.
        """
        now = time.monotonic()

        if self.last_t is None:
            self.last_t = now
            lx, ly, lz = _linear_accel_world(ax_raw, ay_raw, az_raw, oa, ob, og)
            self._init_filter(lx, ly, lz)
            return self.px, self.py, self.pz

        dt = min(now - self.last_t, MAX_DT)
        self.last_t = now

        # ── Step 1: gravity removal → world-frame linear acceleration ──────
        lx, ly, lz = _linear_accel_world(ax_raw, ay_raw, az_raw, oa, ob, og)

        # ── Step 2: filter (Butterworth or EMA) ────────────────────────────
        self._filter(lx, ly, lz)

        # ── Step 3: rolling ZUPT window ────────────────────────────────────
        self.history.append((self.ax_f, self.ay_f, self.az_f))
        if len(self.history) < ZUPT_WINDOW:
            return self.px, self.py, self.pz

        # ── Step 4: ZUPT hysteresis state machine ──────────────────────────
        candidate = _is_stationary(self.history, ga, gb, gg)
        if candidate:
            self.stop_count += 1
            self.move_count  = 0
        else:
            self.move_count  += 1
            self.stop_count   = 0

        prev_stationary = self.stationary
        if self.stationary:
            if self.move_count >= MOVE_CONFIRM_FRAMES:
                self.stationary = False
        else:
            if self.stop_count >= STOP_CONFIRM_FRAMES:
                self.stationary = True

        just_stopped = self.stationary and not prev_stationary

        # ── Step 5: velocity update ────────────────────────────────────────
        if self.stationary:
            if just_stopped:
                self._retroactive_zupt()        # retroactive position correction
            self.vx = self.vy = self.vz = 0.0
            self.ax_f = self.ay_f = self.az_f = 0.0   # clear filter residual

        else:
            # Integrate velocity
            prev_vx, prev_vy, prev_vz = self.vx, self.vy, self.vz
            new_vx = self.vx + self.ax_f * dt
            new_vy = self.vy + self.ay_f * dt
            new_vz = self.vz + self.az_f * dt

            # Anti-rebound clamp: per-axis sign-flip prevention around stop.
            if self.vx * new_vx < 0 and (abs(self.vx) < V_STOP or abs(new_vx) < V_STOP):
                new_vx = 0.0
                self.ax_f = 0.0
            if self.vy * new_vy < 0 and (abs(self.vy) < V_STOP or abs(new_vy) < V_STOP):
                new_vy = 0.0
                self.ay_f = 0.0
            if self.vz * new_vz < 0 and (abs(self.vz) < V_STOP or abs(new_vz) < V_STOP):
                new_vz = 0.0
                self.az_f = 0.0

            self.vx, self.vy, self.vz = new_vx, new_vy, new_vz

            # Velocity decay (dt-based, sample-rate-independent)
            decay = VELOCITY_DECAY ** dt
            self.vx *= decay
            self.vy *= decay
            self.vz *= decay

            # Deadband near rest: suppress tiny residual drift.
            if abs(self.vx) < V_EPS and abs(self.ax_f) < A_EPS:
                self.vx = 0.0
                self.ax_f = 0.0
            if abs(self.vy) < V_EPS and abs(self.ay_f) < A_EPS:
                self.vy = 0.0
                self.ay_f = 0.0
            if abs(self.vz) < V_EPS and abs(self.az_f) < A_EPS:
                self.vz = 0.0
                self.az_f = 0.0

            # Buffer for retroactive correction at next ZUPT
            self.v_buffer.append((self.vx, self.vy, self.vz, dt))

            # 2nd-order integration with v at start of interval
            half_dt2 = 0.5 * dt * dt
            self.px += prev_vx * dt + self.ax_f * half_dt2
            self.py += prev_vy * dt + self.ay_f * half_dt2
            self.pz += prev_vz * dt + self.az_f * half_dt2

            return self.px, self.py, self.pz

        # ── Step 6: filter reset on first stationary frame ─────────────────
        if just_stopped:
            self._reset_filter_to_zero()

        return self.px, self.py, self.pz


# ── Math helpers ──────────────────────────────────────────────────────────────

def _linear_accel_world(ax_raw, ay_raw, az_raw, alpha_deg, beta_deg, gamma_deg):
    """
    Remove gravity and transform to fixed world frame using numpy.

    R = Rz(α)·Rx(β)·Ry(γ)  (device → world)
    World frame: X = East, Y = North, Z = up

    Device convention (measured):
      Flat face-up at rest: az ≈ -9.81  (gravity vector, not reaction force)
      Moving UP → az decreases  → negate wz after gravity cancellation
    """
    a = math.radians(alpha_deg)
    b = math.radians(beta_deg)
    g = math.radians(gamma_deg)

    sa, ca = math.sin(a), math.cos(a)
    sb, cb = math.sin(b), math.cos(b)
    sg, cg = math.sin(g), math.cos(g)

    R = np.array([
        [ca*cg - sa*sb*sg,  -sa*cb,  ca*sg + sa*sb*cg],
        [sa*cg + ca*sb*sg,   ca*cb,  sa*sg - ca*sb*cg],
        [-cb*sg,              sb,    cb*cg            ],
    ])

    raw = np.array([ax_raw, ay_raw, az_raw])
    w = R @ raw

    # Gravity cancellation + Z-axis inversion for this device
    w[2] = -(w[2] + GRAVITY)

    return float(w[0]), float(w[1]), float(w[2])


def _is_stationary(history, ga, gb, gg):
    """
    True when all three conditions hold:
      1. Mean linear-accel magnitude is low  (rules out constant acceleration)
      2. Variance of magnitude is low        (rules out vibration / active motion)
      3. Gyro magnitude is low               (rules out rotation)
    """
    vals = np.array(history)                         # (ZUPT_WINDOW, 3)
    mags = np.linalg.norm(vals, axis=1)
    mean = mags.mean()

    if mean > ZUPT_MAG_THRESH:
        return False

    variance = mags.var()
    gyro_mag = math.sqrt(ga*ga + gb*gb + gg*gg)

    return variance < ZUPT_VAR_THRESH and gyro_mag < ZUPT_GYRO_THRESH


# ── Output table helpers ──────────────────────────────────────────────────────

_HEADERS = ['slot', 'x', 'y', 'z', 'vx', 'vy', 'vz', 'speed', 'stationary']

_estimators   = {}
_output_table = None


def _ensure_headers(table):
    if table.numRows == 0:
        table.setSize(1, len(_HEADERS))
    if table.numCols < len(_HEADERS):
        table.setSize(max(table.numRows, 1), len(_HEADERS))
    try:
        if all(str(table[0, i]) == _HEADERS[i] for i in range(len(_HEADERS))):
            return
    except Exception:
        pass
    for i, h in enumerate(_HEADERS):
        table[0, i] = h


def _get_output_table():
    global _output_table
    if _output_table is not None:
        try:
            _ = _output_table.numRows
            return _output_table
        except Exception:
            _output_table = None
    try:
        p = parent()  # type: ignore[name-defined]
        if p is not None:
            t = p.op('position_table')
            if t is not None:
                _ensure_headers(t)
                _output_table = t
                return t
            t = p.create(tableDAT, 'position_table')  # type: ignore[name-defined]
            _ensure_headers(t)
            print('[W2TD Position v2] Created position_table.')
            _output_table = t
            return t
    except Exception as e:
        print(f'[W2TD Position v2] Could not get/create position_table: {e}')
    return op('position_table')


def _write_output(table, slot, est):
    if table is None:
        return
    row_idx = None
    for r in range(1, table.numRows):
        try:
            if int(table[r, 0]) == slot:
                row_idx = r
                break
        except Exception:
            continue
    if row_idx is None:
        table.appendRow([0] * 8)
        row_idx = table.numRows - 1
    try:
        speed = float(np.linalg.norm([est.vx, est.vy, est.vz]))
        table[row_idx, 0] = slot
        table[row_idx, 1] = round(est.px, 5)
        table[row_idx, 2] = round(est.py, 5)
        table[row_idx, 3] = round(est.pz, 5)
        table[row_idx, 4] = round(est.vx, 5)
        table[row_idx, 5] = round(est.vy, 5)
        table[row_idx, 6] = round(est.vz, 5)
        table[row_idx, 7] = round(speed, 5)
        table[row_idx, 8] = 1 if est.stationary else 0
    except Exception as e:
        print(f'[W2TD Position v2] Write error slot {slot}: {e}')


def _remove_slot_row(table, slot):
    if table is None:
        return
    for r in range(table.numRows - 1, 0, -1):
        try:
            if int(table[r, 0]) == slot:
                table.deleteRow(r)
                break
        except Exception:
            continue


def _read_sensor_row(dat, row, headers):
    try:
        return {
            'slot':      int(dat[row, headers['slot']]),
            'connected': int(float(dat[row, headers['connected']])),
            'ax': float(dat[row, headers['ax']]),
            'ay': float(dat[row, headers['ay']]),
            'az': float(dat[row, headers['az']]),
            'oa': float(dat[row, headers['oa']]),
            'ob': float(dat[row, headers['ob']]),
            'og': float(dat[row, headers['og']]),
            'ga': float(dat[row, headers['ga']]),
            'gb': float(dat[row, headers['gb']]),
            'gg': float(dat[row, headers['gg']]),
        }
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

def reset_slot(slot_number):
    """Reset position and velocity for one slot."""
    e = _estimators.get(int(slot_number))
    if e:
        e.reset()
        print(f'[W2TD Position v2] Slot {slot_number} reset.')
    else:
        print(f'[W2TD Position v2] Slot {slot_number} not active.')


def reset_all():
    """Reset all active slot estimators."""
    for e in _estimators.values():
        e.reset()
    print(f'[W2TD Position v2] All {len(_estimators)} slot(s) reset.')


# ── DAT Execute callbacks ─────────────────────────────────────────────────────

def onTableChange(dat):
    """Entry point — called by DAT Execute whenever sensor_table changes."""
    try:
        table = _get_output_table()

        if dat.numRows < 2:
            # All devices disconnected — clear everything
            for slot in list(_estimators.keys()):
                del _estimators[slot]
            if table is not None:
                for r in range(table.numRows - 1, 0, -1):
                    table.deleteRow(r)
            return

        headers = {str(dat[0, c]): c for c in range(dat.numCols)}
        required = ['slot', 'connected', 'ax', 'ay', 'az', 'oa', 'ob', 'og', 'ga', 'gb', 'gg']
        if any(k not in headers for k in required):
            return

        active_slots = set()

        for row in range(1, dat.numRows):
            d = _read_sensor_row(dat, row, headers)
            if d is None:
                continue

            slot = d['slot']

            if d['connected'] == 0:
                if slot in _estimators:
                    del _estimators[slot]
                    _remove_slot_row(table, slot)
                continue

            active_slots.add(slot)

            if slot not in _estimators:
                _estimators[slot] = PositionEstimator()

            est = _estimators[slot]
            est.update(
                d['ax'], d['ay'], d['az'],
                d['oa'], d['ob'], d['og'],
                d['ga'], d['gb'], d['gg'],
            )
            _write_output(table, slot, est)

        # Remove stale slots: check _estimators AND position_table directly
        # (position_table may have leftover rows from before a script reload)
        for slot in list(_estimators.keys()):
            if slot not in active_slots:
                del _estimators[slot]
        if table is not None:
            for r in range(table.numRows - 1, 0, -1):
                try:
                    if int(table[r, 0]) not in active_slots:
                        table.deleteRow(r)
                except Exception:
                    continue

    except Exception as e:
        global _output_table
        _output_table = None  # 캐시 리셋 → 다음 호출 시 재탐색
        t = _get_output_table()
        print(f'[W2TD Position v2] onTableChange error: {e} | table={t} path={getattr(t, "path", None)} nodeType={getattr(t, "nodeType", None)}')


def onRowChange(dat, rows):    pass
def onColChange(dat, cols):    pass
def onCellChange(dat, cells, prev): pass
def onSizeChange(dat):              pass
