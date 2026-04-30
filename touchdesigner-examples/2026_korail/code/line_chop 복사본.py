"""
W2TD Stay-tion | line_chop.py
==============================
Script CHOP — 절대 시간 축 기반 철도 다이어그램 데이터 생성.

── 동작 방식 ────────────────────────────────────────────────
  - 첫 모바일 접속 시 세션 시작 (시간 축 0)
  - 이후 cook()이 매 프레임 실행되며 시간이 계속 흐름
  - speed=0 → dy=0 → 수평선 / speed>0 → y 증가 → 기울기
  - 접속 끊겨도 채널은 삭제되지 않고 마지막 y 유지
  - 재접속 시 새 채널 추가 (기존 채널 보존)
  - 채널별 시작 전 구간은 NO_DATA(-1000) → GLSL에서 스킵

── 채널 레이아웃 ────────────────────────────────────────────
  - 채널명: s{slot}_c{n}  (n = 생성 순서)
  - 샘플 수: HISTORY_LEN (전체 세션을 이 해상도로 매핑)
  - CHOP to TOP → width=HISTORY_LEN, height=채널 수

── Parent COMP 파라미터 ────────────────────────────────────
  Speedscale      float  기울기 배율          기본값 2.0
  Sessionduration float  세션 총 시간(초)     기본값 28800 (8시간)
"""

import time as _time

HISTORY_LEN = 2000   # 시간 축 해상도 (샘플 수)
NO_DATA     = -1000.0  # 아직 기록 없음 — GLSL에서 렌더 스킵

_COLORS = [
    (0.40, 0.80, 1.00), (1.00, 0.40, 0.40), (0.40, 1.00, 0.40),
    (1.00, 1.00, 0.40), (1.00, 0.40, 1.00), (0.40, 1.00, 1.00),
    (1.00, 0.80, 0.40), (0.80, 0.40, 1.00), (0.40, 0.80, 0.40),
    (1.00, 0.60, 0.80), (0.60, 0.80, 1.00), (1.00, 0.60, 0.40),
    (0.60, 1.00, 0.80), (1.00, 0.80, 1.00), (0.80, 1.00, 0.40),
    (0.40, 0.60, 1.00), (1.00, 0.40, 0.60), (0.40, 1.00, 0.60),
    (0.80, 0.60, 0.40), (0.60, 0.40, 1.00),
]

# ── 세션 상태 (스크립트 리로드 전까지 유지) ──────────────────
_session_start  = None   # float: time.monotonic() at first connection
_last_cook_t    = None   # float: 직전 cook() 호출 시각
_ch_count       = 0      # 생성된 채널 총 수 (고유 이름용)

# _channels: { key: { 'buf': list[float], 'cur_y': float,
#                      'last_idx': int, 'active': bool, 'slot': int } }
_channels  = {}
_key_order = []          # 출력 순서 보장

# _slot_to_key: { slot: key }  현재 접속 중인 슬롯의 활성 채널
_slot_to_key = {}


_debug_count = 0   # 초반 N프레임만 디버그 출력


def _par(name, default):
    try:
        p = parent()
        if p and hasattr(p.par, name):
            return float(getattr(p.par, name))
    except Exception:
        pass
    return default


def _find_position_table(scriptOp):
    """
    position_table DAT를 찾는다.
    1) 부모 COMP 파라미터 Positiontable 경로 우선
    2) 같은 레벨(sibling) op('position_table')
    3) 부모 컨테이너 안의 op('position_table')
    """
    # 1) 커스텀 파라미터로 경로 지정된 경우
    try:
        p = parent()
        if p and hasattr(p.par, 'Positiontable'):
            path = str(p.par.Positiontable)
            if path:
                t = op(path)
                if t is not None:
                    return t
    except Exception:
        pass

    # 2) scriptOp 기준 sibling
    try:
        t = scriptOp.parent().op('position_table')
        if t is not None:
            return t
    except Exception:
        pass

    # 3) 한 단계 위 (컨테이너 밖)
    try:
        t = scriptOp.parent().parent().op('position_table')
        if t is not None:
            return t
    except Exception:
        pass

    return None


def _elapsed():
    if _session_start is None:
        return 0.0
    return _time.monotonic() - _session_start


def _t_to_idx(t, session_dur):
    """시간(초) → 버퍼 인덱스 (0 ~ HISTORY_LEN-1)"""
    if session_dur <= 0:
        return 0
    return min(int(t / session_dur * HISTORY_LEN), HISTORY_LEN - 1)


def cook(scriptOp):
    global _session_start, _last_cook_t, _ch_count

    now           = _time.monotonic()
    dt            = (now - _last_cook_t) if _last_cook_t is not None else 0.0
    _last_cook_t  = now

    speed_scale   = _par('Speedscale', 2.0)
    session_dur   = _par('Sessionduration', 28800.0)

    # ── position_table 읽기 ───────────────────────────────────
    active_slots = {}   # { slot: speed }
    pt = op('position_table')
    if pt is not None and pt.numRows >= 2:
        headers = {str(pt[0, c]): c for c in range(pt.numCols)}
        if 'slot' in headers and 'speed' in headers:
            for row in range(1, pt.numRows):
                try:
                    slot  = int(pt[row, headers['slot']])
                    speed = float(pt[row, headers['speed']])
                    active_slots[slot] = speed
                except Exception:
                    continue

    # ── 활성 슬롯 업데이트 ────────────────────────────────────
    for slot, speed in active_slots.items():

        # 첫 접속 → 세션 시작
        if _session_start is None:
            _session_start = now

        # 새 채널 생성 (첫 접속 or 재접속)
        if slot not in _slot_to_key:
            key = f's{slot}_c{_ch_count}'
            _ch_count += 1
            start_idx = _t_to_idx(_elapsed(), session_dur)
            _channels[key] = {
                'buf':      [NO_DATA] * HISTORY_LEN,
                'cur_y':    0.0,
                'last_idx': start_idx,
                'active':   True,
                'slot':     slot,
            }
            _key_order.append(key)
            _slot_to_key[slot] = key

        key = _slot_to_key[slot]
        ch  = _channels[key]

        # y 누적 (실제 dt 기반 → 프레임레이트 독립)
        ch['cur_y']  += speed * speed_scale * dt
        ch['active']  = True

        # 현재 시간 인덱스까지 버퍼 채우기
        idx = _t_to_idx(_elapsed(), session_dur)
        for i in range(ch['last_idx'], idx + 1):
            ch['buf'][i] = ch['cur_y']
        if idx > ch['last_idx']:
            ch['last_idx'] = idx

    # ── 끊긴 슬롯 처리 (채널 유지, 마지막 y 보존) ───────────
    for slot in list(_slot_to_key.keys()):
        if slot not in active_slots:
            key = _slot_to_key[slot]
            _channels[key]['active'] = False
            del _slot_to_key[slot]

    # 비활성 채널도 시간 흐름에 따라 마지막 y로 채움 (수평 연장)
    if _session_start is not None:
        idx = _t_to_idx(_elapsed(), session_dur)
        for key, ch in _channels.items():
            if not ch['active'] and idx > ch['last_idx']:
                last_y = ch['cur_y']
                for i in range(ch['last_idx'] + 1, idx + 1):
                    ch['buf'][i] = last_y
                ch['last_idx'] = idx

    # ── 채널 출력 ─────────────────────────────────────────────
    scriptOp.clear()
    scriptOp.numSamples = HISTORY_LEN

    for key in _key_order:
        if key not in _channels:
            continue
        ch_data = _channels[key]
        out_ch  = scriptOp.appendChan(key)
        buf     = ch_data['buf']
        for i in range(HISTORY_LEN):
            out_ch[i] = buf[i]
