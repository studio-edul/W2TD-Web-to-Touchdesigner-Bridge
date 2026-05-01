"""
W2TD Position Estimator
=======================
Real-time 3D relative position tracking using accelerometer + orientation data.

TD Setup:
  1. Create a Base COMP (container) anywhere in your project
     — e.g. name it 'position_estimator'
  2. Inside that container, create a DAT Execute DAT
     — Set "DATs" parameter to: sensor_table  (use full path if sensor_table
       is not a direct ancestor, e.g. /project1/W2TD/sensor_table)
     — Enable "Table Change" checkbox
     — Paste this script as its content
  3. The script automatically creates a Table DAT named 'position_table'
     inside the same container on the first table change.
     Columns: slot | x | y | z | vx | vy | vz | stationary
  4. Connect position_table -> DAT to CHOP for CHOP access

  To reset position from a Button DAT or TD Python console:
      op('your_container/your_datexecute_name').module.reset_slot(1)
      op('your_container/your_datexecute_name').module.reset_all()

Algorithm:
  1. Extract gravity from orientation angles using W3C ZXY rotation matrix
  2. Remove gravity from raw accelerometer data → linear acceleration
  3. EMA low-pass filter to reduce hand-movement noise
  4. ZUPT: detect stationary state and zero velocity → prevents drift
  5. Integrate velocity and position with delta time
  6. Velocity decay to limit unbounded growth between ZUPT intervals

Coordinate system:
  Same as DeviceOrientation world frame.
  X = East, Y = North, Z = up.
  Position unit: metres, relative to (0,0,0) at connection time.

Note: no numpy required — uses only the standard math module.
"""

import math
import time

# =============================================
# CONFIGURATION — edit these values to tune
# =============================================
LPF_ALPHA = 0.9              # EMA filter strength: 0.0 = max smooth, 1.0 = no filter

# --- Stationary detection ---
ZUPT_WINDOW = 4              # sample window size for variance calculation
ZUPT_ACCEL_MAG_THRESH = 0.5  # not stationary if mean linear-accel magnitude exceeds this (m/s²)
ZUPT_ACCEL_VAR_THRESH = 0.05 # stationary if accel-mag variance below this (m/s²)²
ZUPT_GYRO_THRESH = 5.0       # stationary if gyro magnitude below this (deg/s)
STOP_CONFIRM_FRAMES = 2      # moving → stationary: consecutive candidate frames needed

# --- Movement detection (stationary → moving) ---
# Lower = more sensitive (detects movement sooner); Higher = less jitter
MOVE_CONFIRM_FRAMES = 4      # stationary → moving: consecutive candidate frames needed

VELOCITY_DECAY_PER_SEC = 0.1 # velocity remaining after 1 second (sample-rate-independent)
GRAVITY = 9.81               # m/s²
MAX_DT = 0.1                 # clamp dt to prevent jump on reconnect (seconds)
V_STOP   = 0.15              # anti-rebound threshold (kept for tuning/reference)
GYRO_STOP = 5.0              # legacy threshold (anti-rebound now does sign-flip clamp)
A_EPS = 0.12                 # near-zero accel deadband (m/s²)
V_EPS = 0.04                 # near-zero velocity deadband (m/s)
# =============================================

_estimators = {}   # { slot_number: PositionEstimator }
_output_table = None  # cached reference to position_table DAT


class PositionEstimator:
    def __init__(self):
        self.reset()

    def reset(self):
        self.vx = self.vy = self.vz = 0.0
        self.px = self.py = self.pz = 0.0
        self.ax_f = self.ay_f = self.az_f = 0.0  # EMA-filtered linear accel
        self.last_t = None
        self.history = []    # recent (ax_f, ay_f, az_f) for ZUPT variance window
        self.stationary = True
        self.stop_count = 0
        self.move_count = 0

    def update(self, ax_raw, ay_raw, az_raw, oa, ob, og, ga, gb, gg):
        """
        ax_raw, ay_raw, az_raw : accelerationIncludingGravity (m/s²)
        oa, ob, og             : DeviceOrientation alpha/beta/gamma (degrees)
        ga, gb, gg             : rotationRate alpha/beta/gamma (deg/s)
        Returns (px, py, pz) in metres.
        Output is in world frame: X = East, Y = North, Z = up.
        """
        now = time.monotonic()

        if self.last_t is None:
            self.last_t = now
            # Seed the EMA filter with the first sample
            self.ax_f, self.ay_f, self.az_f = _linear_accel_world(
                ax_raw, ay_raw, az_raw, oa, ob, og
            )
            return self.px, self.py, self.pz

        dt = min(now - self.last_t, MAX_DT)
        self.last_t = now

        # Step 1: Gravity removal + transform to world frame (X=East, Y=North, Z=up)
        #   linear_world = R^T · raw_device - [0, 0, GRAVITY]
        #   (R transforms world→device, so R^T transforms device→world)
        lx, ly, lz = _linear_accel_world(ax_raw, ay_raw, az_raw, oa, ob, og)

        # Step 2: EMA low-pass filter
        self.ax_f += LPF_ALPHA * (lx - self.ax_f)
        self.ay_f += LPF_ALPHA * (ly - self.ay_f)
        self.az_f += LPF_ALPHA * (lz - self.az_f)

        # Step 3: Update variance window
        self.history.append((self.ax_f, self.ay_f, self.az_f))
        if len(self.history) > ZUPT_WINDOW:
            self.history.pop(0)

        # Warmup: skip integration until window is full to avoid integrating
        # unstabilised EMA transients. Position holds at 0,0,0 during this period.
        if len(self.history) < ZUPT_WINDOW:
            return self.px, self.py, self.pz

        # Step 4: ZUPT candidate + hysteresis state machine
        zupt_candidate = _is_stationary(self.history, ga, gb, gg)
        if zupt_candidate:
            self.stop_count += 1
            self.move_count = 0
        else:
            self.move_count += 1
            self.stop_count = 0

        if self.stationary:
            if self.move_count >= MOVE_CONFIRM_FRAMES:
                self.stationary = False
        else:
            if self.stop_count >= STOP_CONFIRM_FRAMES:
                self.stationary = True

        if self.stationary:
            self.vx = self.vy = self.vz = 0.0
            # Also clear EMA so residual doesn't push velocity negative next frame
            self.ax_f = self.ay_f = self.az_f = 0.0
        else:
            # Step 5: Integrate velocity with anti-rebound clamp
            new_vx = self.vx + self.ax_f * dt
            new_vy = self.vy + self.ay_f * dt
            new_vz = self.vz + self.az_f * dt

            # Anti-rebound clamp: when a velocity axis would cross zero in one step,
            # clamp it to zero immediately to prevent opposite-direction push-through.
            if self.vx * new_vx < 0:
                new_vx = 0.0
                self.ax_f = 0.0
            if self.vy * new_vy < 0:
                new_vy = 0.0
                self.ay_f = 0.0
            if self.vz * new_vz < 0:
                new_vz = 0.0
                self.az_f = 0.0

            self.vx, self.vy, self.vz = new_vx, new_vy, new_vz

            # Step 6: Velocity decay — dt-based so result is same at any sample rate
            # decay = VELOCITY_DECAY_PER_SEC^dt  (e.g. 0.1^(1/30) ≈ 0.926 at 30 Hz)
            decay = VELOCITY_DECAY_PER_SEC ** dt
            self.vx *= decay
            self.vy *= decay
            self.vz *= decay

            # Deadband near rest to prevent tiny residual drift and rebound rebuild.
            if abs(self.vx) < V_EPS and abs(self.ax_f) < A_EPS:
                self.vx = 0.0
                self.ax_f = 0.0
            if abs(self.vy) < V_EPS and abs(self.ay_f) < A_EPS:
                self.vy = 0.0
                self.ay_f = 0.0
            if abs(self.vz) < V_EPS and abs(self.az_f) < A_EPS:
                self.vz = 0.0
                self.az_f = 0.0

        # Step 7: Integrate position
        self.px += self.vx * dt
        self.py += self.vy * dt
        self.pz += self.vz * dt

        return self.px, self.py, self.pz


# ── Math helpers ──────────────────────────────────────────────────────────────

def _linear_accel_world(ax_raw, ay_raw, az_raw, alpha_deg, beta_deg, gamma_deg):
    """
    Remove gravity and transform accelerometer data into the fixed world frame.

    World frame convention (W3C DeviceOrientation):
      X = East,  Y = North,  Z = up

    R = Rz(α)·Rx(β)·Ry(γ) transforms DEVICE → WORLD frame.
    (R^T would be world→device; we need R itself.)

    Sensor sign convention (measured on device):
      Flat face-up at rest: az ≈ -9.81 (gravity vector convention)
      Physical upward motion → az decreases (device Z linear component inverted)

    Derivation:
      gravity_device = R^T · [0, 0, -GRAVITY]  (gravity points DOWN = -Z in world)
      linear_device  = raw - gravity_device
      linear_world   = R · linear_device = R·raw + [0, 0, GRAVITY]
      Device correction: negate wz because device az decreases when moving up

    Verification:
      Flat at rest   (β=0):   raw=[0,0,-g]   → wz = -(-g + g)     = 0  ✓
      Flat moving up (β=0):   raw=[0,0,-g-a] → wz = -((-g-a) + g) = a > 0  ✓
      Upright rest   (β=90°): raw=[0,-g, 0]  → wz = -(sb·(-g) + g) = 0  ✓
    """
    a = math.radians(alpha_deg)
    b = math.radians(beta_deg)
    g = math.radians(gamma_deg)

    sa, ca = math.sin(a), math.cos(a)
    sb, cb = math.sin(b), math.cos(b)
    sg, cg = math.sin(g), math.cos(g)

    # Full rotation matrix R = Rz(a)·Rx(b)·Ry(g), device → world
    # Row 0:
    r00 = ca * cg - sa * sb * sg
    r01 = -sa * cb
    r02 = ca * sg + sa * sb * cg
    # Row 1:
    r10 = sa * cg + ca * sb * sg
    r11 = ca * cb
    r12 = sa * sg - ca * sb * cg
    # Row 2:
    r20 = -cb * sg
    r21 = sb
    r22 = cb * cg

    # R · raw_device
    wx = r00 * ax_raw + r01 * ay_raw + r02 * az_raw
    wy = r10 * ax_raw + r11 * ay_raw + r12 * az_raw
    wz = r20 * ax_raw + r21 * ay_raw + r22 * az_raw

    # Gravity cancellation: az at rest = -g, so add +g to zero it out
    wz += GRAVITY
    # Device Z axis is inverted for linear motion: moving up → az decreases.
    # Negate wz so that world +Z correctly represents upward direction.
    wz = -wz

    return wx, wy, wz


def _is_stationary(history, ga, gb, gg):
    """
    Return True when the device appears stationary.

    Conditions (all must pass):
      1. Mean linear-accel magnitude is low  → rules out constant linear acceleration
                                               (elevator, car at steady speed)
      2. Variance of linear-accel magnitude is low  → rules out vibration / movement
      3. Gyro magnitude is low  → rules out rotation
    """
    mags = [math.sqrt(ax * ax + ay * ay + az * az) for ax, ay, az in history]
    mean = sum(mags) / len(mags)

    # Condition 1: constant non-zero acceleration → not stationary
    if mean > ZUPT_ACCEL_MAG_THRESH:
        return False

    variance = sum((m - mean) ** 2 for m in mags) / len(mags)
    gyro_mag = math.sqrt(ga * ga + gb * gb + gg * gg)

    return variance < ZUPT_ACCEL_VAR_THRESH and gyro_mag < ZUPT_GYRO_THRESH


# ── Output table helpers ──────────────────────────────────────────────────────

_HEADERS = ['slot', 'x', 'y', 'z', 'vx', 'vy', 'vz', 'speed', 'stationary']


def _ensure_headers(table):
    """Guarantee row 0 contains the expected column headers."""
    if table.numRows == 0:
        table.setSize(1, len(_HEADERS))
    if table.numCols < len(_HEADERS):
        table.setSize(max(table.numRows, 1), len(_HEADERS))
    try:
        if all(str(table[0, i]) == _HEADERS[i] for i in range(len(_HEADERS))):
            return  # already correct
    except Exception:
        pass
    for i, h in enumerate(_HEADERS):
        table[0, i] = h


def _get_output_table():
    """Get or auto-create 'position_table' Table DAT inside the same container."""
    global _output_table
    if _output_table is not None:
        try:
            _ = _output_table.numRows  # validate still alive
            return _output_table
        except Exception:
            _output_table = None

    try:
        p = parent()  # type: ignore[name-defined]  # TD built-in
        if p is not None:
            t = p.op('position_table')
            if t is not None:
                _ensure_headers(t)
                _output_table = t
                return t
            # Auto-create Table DAT
            t = p.create(tableDAT, 'position_table')  # type: ignore[name-defined]  # TD built-in
            _ensure_headers(t)
            print('[W2TD Position] Created position_table DAT.')
            _output_table = t
            return t
    except Exception as e:
        print(f'[W2TD Position] Could not get/create position_table: {e}')

    return op('position_table')  # last-resort fallback


def _write_output(table, slot, est):
    """Write or update one slot row in position_table."""
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
        speed = math.sqrt(est.vx * est.vx + est.vy * est.vy + est.vz * est.vz)
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
        print(f'[W2TD Position] Write error slot {slot}: {e}')


def _remove_slot_row(table, slot):
    """Remove a disconnected slot's row from position_table."""
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
    """Parse one sensor_table row into a dict, or return None on error."""
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
    """
    Reset position and velocity for one slot.
    Call from TD Python: op('your_container/dat_execute').module.reset_slot(1)
    """
    e = _estimators.get(int(slot_number))
    if e:
        e.reset()
        print(f'[W2TD Position] Slot {slot_number} reset.')
    else:
        print(f'[W2TD Position] Slot {slot_number} not active.')


def reset_all():
    """
    Reset all active slot estimators.
    Call from TD Python: op('your_container/dat_execute').module.reset_all()
    """
    for e in _estimators.values():
        e.reset()
    print(f'[W2TD Position] All {len(_estimators)} slot(s) reset.')


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

        # Build column-name → index map from header row
        headers = {str(dat[0, c]): c for c in range(dat.numCols)}

        required = ['slot', 'connected', 'ax', 'ay', 'az', 'oa', 'ob', 'og', 'ga', 'gb', 'gg']
        if any(k not in headers for k in required):
            return  # sensor_table not yet initialised

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
        print(f'[W2TD Position] onTableChange error: {e}')


def onRowChange(dat, rows):
    pass

def onColChange(dat, cols):
    pass

def onCellChange(dat, cells, prev):
    pass

def onSizeChange(dat):
    pass
