"""
WOB Relative Position Estimator
================================
sensor_table Table Change DAT의 Script DAT으로 연결.
accelerationIncludingGravity + DeviceOrientation으로
기기의 상대 위치를 추정 (이중 적분 / 관성 항법 방식).

결과 출력:
    - op('mobile_position') Constant CHOP  → val0=x, val1=y, val2=z  (단위: m)
    - op('/').store('wob_pos_{slot}', {'x':..., 'y':..., 'z':...})

TD 사전 준비:
    1. Constant CHOP 생성 → 이름: mobile_position
    2. CHOP에서 채널을 3개로 추가 (기본 1개 → + 버튼으로 2개 더 추가)
    3. 채널 이름을 각각 x, y, z 로 설정 (Name 0/1/2 파라미터)

바이어스 보정:
    - reset_position() 호출 후 기기를 약 1초간 정지 상태로 유지
    - CAL_FRAMES 개 샘플로 세계 좌표계 가속도 평균(바이어스) 측정
    - 이후 모든 측정에서 바이어스 차감 → 드리프트 최소화

위치 초기화:
    op('/').fetch('wob_relative_position_estimators', {}).get(1).reset_position()
"""

import math
import time

import numpy as np

GRAVITY = 9.81
CAL_FRAMES = 30  # 보정용 정지 샘플 수 (~1초 @ 30Hz)

_update_count = 0
_estimators_cache = {}  # module-level cache — persists between calls, resets on script reload


# ── 수학 유틸 ──────────────────────────────────────────────────────────────────

def _gravity_in_device_frame(oa, ob, og):
    """
    W3C DeviceOrientation (alpha=oa, beta=ob, gamma=og, deg) 기반
    기기 좌표계에서의 중력 벡터 반환 (m/s²).
    """
    a = math.radians(float(oa or 0))
    b = math.radians(float(ob or 0))
    g = math.radians(float(og or 0))
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cg, sg = math.cos(g), math.sin(g)

    return np.array([
         GRAVITY * (ca * sg - sa * sb * cg),
        -GRAVITY * (sa * sg + ca * sb * cg),
        -GRAVITY * cb * cg,
    ])


def _rotation_device_to_world(oa, ob, og):
    """기기 좌표계 → 세계 좌표계 (X=East, Y=North, Z=Up) 변환 행렬."""
    a = math.radians(float(oa or 0))
    b = math.radians(float(ob or 0))
    g = math.radians(float(og or 0))
    ca, sa = math.cos(a), math.sin(a)
    cb, sb = math.cos(b), math.sin(b)
    cg, sg = math.cos(g), math.sin(g)

    return np.array([
        [ca*cg + sa*sb*sg,  -sa*cg + ca*sb*sg,  cb*sg],
        [sa*cb,              ca*cb,             -sb   ],
        [-ca*sg + sa*sb*cg,  sa*sg + ca*sb*cg,  cb*cg],
    ])


# ── 위치 추정 클래스 ───────────────────────────────────────────────────────────

class RelativePositionEstimator:
    def __init__(self, slot):
        self.slot = slot
        self.last_time       = None
        self.accel_threshold = 0.08  # ZUPT 임계값 (m/s²)
        self.damping_half_life = 0.5  # 정지 시 속도 반감기 (초)
        self.reset_position()

    def reset_position(self):
        """
        위치·속도·바이어스 보정을 0으로 초기화.
        호출 후 기기를 ~1초 정지 상태로 유지하면 바이어스 재보정.
        """
        self.position      = np.zeros(3)
        self.velocity      = np.zeros(3)
        self._cal_samples  = []   # 보정용 샘플 버퍼
        self._cal_done     = False
        self._bias         = np.zeros(3)  # 세계 좌표계 가속도 바이어스
        print(f'[WOB Pos] slot={self.slot} reset — hold device still for ~1s (bias calibration starting...)')

    def update(self, accel_x, accel_y, accel_z, oa=0, ob=0, og=0):
        """
        매 sensor_table 변경 시 호출.
        반환: (x, y, z) 세계 좌표계 상대 위치 (m)
        """
        now = time.time()
        if self.last_time is None:
            self.last_time = now
            return tuple(self.position)

        dt = now - self.last_time
        self.last_time = now

        if dt <= 0 or dt > 1.0:
            return tuple(self.position)

        # Step 1: 중력 제거 → 기기 좌표계 선형 가속도
        accel_raw = np.array([
            float(accel_x or 0),
            float(accel_y or 0),
            float(accel_z or 0),
        ])
        a_device = accel_raw - _gravity_in_device_frame(oa, ob, og)

        # Step 2: 기기 좌표계 → 세계 좌표계 변환
        R = _rotation_device_to_world(oa, ob, og)
        a_world = R @ a_device

        # Step 3: 바이어스 보정 (처음 CAL_FRAMES 동안 정지 상태 측정)
        if not self._cal_done:
            self._cal_samples.append(a_world.copy())
            if len(self._cal_samples) >= CAL_FRAMES:
                self._bias = np.mean(self._cal_samples, axis=0)
                self._cal_done = True
                print(f'[WOB Pos] slot={self.slot} bias calibrated: ({self._bias[0]:.4f}, {self._bias[1]:.4f}, {self._bias[2]:.4f}) m/s2')
            # 보정 중에는 적분 안 함
            return tuple(self.position)

        a_corrected = a_world - self._bias

        # Step 4: ZUPT — 보정된 가속도가 임계값 미만이면 정지로 간주
        if np.linalg.norm(a_corrected) < self.accel_threshold:
            a_corrected = np.zeros(3)
            decay = 0.5 ** (dt / self.damping_half_life)
            self.velocity *= decay

        # Step 5: 이중 적분 (세계 좌표계)
        self.velocity += a_corrected * dt
        self.position += self.velocity * dt

        return tuple(self.position)


# ── TD 연동 ───────────────────────────────────────────────────────────────────

def _write_to_chop(pos):
    """Write position to mobile_position Constant CHOP (slot 1 only)."""
    chop = op('mobile_position')
    if chop is None:
        print('[WOB Pos] ERROR: op("mobile_position") not found — create a Constant CHOP named mobile_position')
        return False
    # Try const0value / const1value / const2value (TD 2022+)
    try:
        chop.par.const0value = pos[0]
        chop.par.const1value = pos[1]
        chop.par.const2value = pos[2]
        return True
    except AttributeError:
        pass
    # Fallback: val0 / val1 / val2 (older TD builds)
    try:
        chop.par.val0 = pos[0]
        chop.par.val1 = pos[1]
        chop.par.val2 = pos[2]
        return True
    except AttributeError:
        pass
    # Diagnostic: list available parameters so the user knows what name to use
    try:
        par_names = [p.name for p in chop.pars()]
        print(f'[WOB Pos] ERROR: mobile_position CHOP missing const0value/val0. Available pars: {par_names[:15]}')
    except Exception:
        print('[WOB Pos] ERROR: mobile_position CHOP parameter access failed')
    return False


def onTableChange(dat):
    """sensor_table Table Change handler. Writes slot 1 position to mobile_position CHOP."""
    global _update_count
    _update_count += 1

    if dat is None or dat.numRows < 2:
        return

    if _update_count == 1:
        print(f'[WOB Pos] started — sensor_table rows={dat.numRows}')

    # Clean up estimators for disconnected slots
    active_slots = set()
    for r in range(1, dat.numRows):
        try:
            active_slots.add(int(dat[r, 'slot']))
        except (ValueError, TypeError, KeyError):
            pass

    for stale in list(_estimators_cache.keys()):
        if stale not in active_slots:
            print(f'[WOB Pos] slot={stale} disconnected — estimator removed')
            del _estimators_cache[stale]

    # Estimate position per slot
    for r in range(1, dat.numRows):
        try:
            slot = int(dat[r, 'slot'])
        except (ValueError, TypeError, KeyError):
            continue

        try:
            ax = float(dat[r, 'ax'] or 0)
            ay = float(dat[r, 'ay'] or 0)
            az = float(dat[r, 'az'] or 0)
            oa = float(dat[r, 'oa'] or 0)
            ob = float(dat[r, 'ob'] or 0)
            og = float(dat[r, 'og'] or 0)
        except (ValueError, TypeError, KeyError):
            ax = ay = az = oa = ob = og = 0.0

        if slot not in _estimators_cache:
            _estimators_cache[slot] = RelativePositionEstimator(slot)
            print(f'[WOB Pos] slot={slot} new estimator created')

        pos = _estimators_cache[slot].update(ax, ay, az, oa, ob, og)

        if slot == 1:
            _write_to_chop(pos)
