"""
W2TD Stay-tion | line_chop.py
==============================
Script CHOP — 속도 실시간 적분, 슬라이딩 윈도우 출력

동작:
  - 첫 모바일 접속 시 프레임 카운트 시작
  - cook() 매 프레임마다 각 채널에 샘플 1개 append
  - speed * dt 만 누적 (speed_scale 미적용 — GLSL에서 uSpeedScale로 처리)
  - 접속 끊기면 채널 유지 + NO_DATA(-1) append (GLSL 스킵)
  - 재접속 시 새 채널 추가, 이전 프레임 구간은 NO_DATA
  - 채널명: index_0, index_1, ... (접속 순)
  - 출력: 최근 Windowminutes 분 분량의 샘플만 출력
  - 초과 데이터: CSV 파일로 아카이브 후 버퍼에서 제거
  - 끊긴 슬롯: 윈도우 내 잔존 데이터까지 포함하여 CSV 저장

커스텀 파라미터:
  Reset          Toggle   1로 하면 다음 cook()에서 전체 초기화 후 0으로 복귀
  Archivepath    Folder   CSV 저장 경로
  Maxspeed       Float    0 = 제한없음 / > 0 = 속도 클램프 상한
  Maxy           Float    Y축 최대값 기준
  Adaptivescale  Toggle   1 = maxY 적응형 / 0 = maxY 고정 (초과값은 GLSL에서 클립)
  Fps            Int      (미사용 — OUTPUT_FPS 30 고정)
  Windowminutes  Int      출력 윈도우 분 단위, 기본값 30
"""

import time as _time
import os as _os
import datetime as _dt
import numpy as _np

NO_DATA       = -1.0
EASE_DURATION = 2.0   # maxY 복귀 easing 시간(초)
OUTPUT_FPS    = 30    # 출력 고정 해상도 — Fps 파라미터와 무관

_last_cook_t = None
_ch_count    = 0
_frame_count = 0

_channels    = {}  # { key: {'buf': list, 'times': list, 'cur_y': float, 'active': bool, 'warmup': bool} }
_key_order   = []
_slot_to_key = {}  # { slot: key }

_dyn_max_y  = None
_ease_start = None
_ease_from  = None

_paused_since  = None   # 마지막 클라이언트가 끊긴 monotonic 시각 (None = 활성 중)
_pause_accum   = 0.0    # 누적 pause 시간(초)
_session_start = None   # 첫 채널 생성 시 effective_now (윈도우 좌측 기준점)


def _window_seconds(scriptOp):
    """Windowminutes → 윈도우 초. Fps 무관."""
    try:
        win_min = float(scriptOp.par.Windowminutes)
    except Exception:
        win_min = 30.0
    return max(win_min * 60.0, 10.0)


def _num_out_samples(scriptOp):
    """출력 샘플 수 = Windowminutes × 60 × OUTPUT_FPS(30 고정). Fps 파라미터 무관."""
    return max(int(_window_seconds(scriptOp) * OUTPUT_FPS), 60)


def _archive(key, buf, folder):
    """버퍼를 CSV 파일에 append 저장."""
    if not buf:
        return
    try:
        if not folder:
            folder = project.folder
        _os.makedirs(folder, exist_ok=True)
        date_str = _dt.datetime.now().strftime('%Y%m%d')
        filename = f'{date_str}_{key}.csv'
        path     = _os.path.join(folder, filename)
        with open(path, 'a') as f:
            for v in buf:
                f.write(f'{v}\n')
    except Exception as e:
        print(f'[line_chop] archive error: {e}')


def _do_reset(scriptOp):
    """전역 상태 전체 초기화. cook() 안에서만 호출."""
    global _last_cook_t, _ch_count, _frame_count
    global _channels, _key_order, _slot_to_key
    global _dyn_max_y, _ease_start, _ease_from
    global _paused_since, _pause_accum, _session_start

    _last_cook_t   = None
    _ch_count      = 0
    _frame_count   = 0
    _channels      = {}
    _key_order     = []
    _slot_to_key   = {}
    _dyn_max_y     = None
    _ease_start    = None
    _ease_from     = None
    _paused_since  = None
    _pause_accum   = 0.0
    _session_start = None

    # Reset 파라미터를 0으로 복귀 (Toggle 방식)
    try:
        scriptOp.par.Reset = 0
    except Exception:
        pass

    scriptOp.clear()
    scriptOp.numSamples = 1
    scriptOp.appendChan('_highlight')[0] = 0.0
    out_max      = scriptOp.appendChan('_maxY')
    try:
        out_max[0] = float(scriptOp.par.Maxy) or 100.0
    except Exception:
        out_max[0] = 100.0
    print('[line_chop] Reset — all graph data cleared')


def cook(scriptOp):
    global _last_cook_t, _ch_count, _frame_count
    global _channels, _key_order, _slot_to_key
    global _dyn_max_y, _ease_start, _ease_from
    global _paused_since, _pause_accum, _session_start

    scriptOp.rate = OUTPUT_FPS

    # ── Reset 체크 (Toggle par: 1 → 리셋 → 0으로 복귀) ─────────
    try:
        if int(scriptOp.par.Reset) == 1:
            _do_reset(scriptOp)
            return
    except Exception:
        pass

    now          = _time.monotonic()
    dt           = (now - _last_cook_t) if _last_cook_t is not None else 0.0
    _last_cook_t = now

    # ── sensor_table에서 실제 연결된 슬롯 수집 ──────────────────
    connected_slots = set()
    st = op('sensor_table')
    if st is not None and st.numRows >= 2:
        st_h = {str(st[0, c]): c for c in range(st.numCols)}
        if 'slot' in st_h and 'connected' in st_h:
            for row in range(1, st.numRows):
                try:
                    if int(st[row, st_h['connected']]) != 1:
                        continue
                    if 'visibility' in st_h and int(st[row, st_h['visibility']]) == 0:
                        continue
                    sensor_axes = ('az', 'ga', 'gb', 'gg')
                    if not any(col in st_h and abs(float(st[row, st_h[col]])) > 0.1 for col in sensor_axes):
                        continue
                    connected_slots.add(int(st[row, st_h['slot']]))
                except Exception:
                    continue
    any_connected = bool(connected_slots)

    # ── Pause / Resume ───────────────────────────────────────────
    if any_connected:
        if _paused_since is not None:
            _pause_accum += now - _paused_since
            _paused_since = None
    elif _paused_since is None:
        _paused_since = now

    effective_now = (_paused_since - _pause_accum) if _paused_since is not None \
                    else (now - _pause_accum)

    # ── position_table_merged 읽기 ───────────────────────────────
    active_slots = {}
    pt = op('position_table_merged')
    if pt is not None and pt.numRows >= 2:
        headers = {str(pt[0, c]): c for c in range(pt.numCols)}
        if 'slot' in headers and 'speed' in headers:
            for row in range(1, pt.numRows):
                try:
                    slot = int(pt[row, headers['slot']])
                    if slot not in connected_slots:
                        continue
                    speed = float(pt[row, headers['speed']])
                    active_slots[slot] = speed
                except Exception:
                    continue

    # ── 백그라운드 슬롯 수집 ────────────────────────────────────
    hidden_slots = set()
    if st is not None and st.numRows >= 2:
        st_hv = {str(st[0, c]): c for c in range(st.numCols)}
        if 'slot' in st_hv and 'visibility' in st_hv:
            for row in range(1, st.numRows):
                try:
                    if int(st[row, st_hv['visibility']]) == 0:
                        hidden_slots.add(int(st[row, st_hv['slot']]))
                except Exception:
                    continue

    # ── 파라미터 읽기 ────────────────────────────────────────────
    try:
        base_max_y = float(scriptOp.par.Maxy)
        if base_max_y <= 0:
            base_max_y = 100.0
    except Exception:
        base_max_y = 100.0

    try:
        max_speed = float(scriptOp.par.Maxspeed)  # 0 = 제한없음
    except Exception:
        max_speed = 0.0

    try:
        adaptive_scale = int(scriptOp.par.Adaptivescale)  # 1 = 적응형, 0 = 고정
    except Exception:
        adaptive_scale = 1

    try:
        archive_folder = str(scriptOp.par.Archivepath).strip()
    except Exception:
        archive_folder = ''

    if _dyn_max_y is None:
        _dyn_max_y = base_max_y

    # ── 대기 중 (센서 연결 없고 채널도 없음) ────────────────────
    # connected_slots 기준 — position_table_merged가 잠시 비어도 채널 유지
    if not connected_slots and not _channels:
        scriptOp.clear()
        scriptOp.numSamples = 1
        scriptOp.appendChan('_highlight')[0] = 0.0
        out_max    = scriptOp.appendChan('_maxY')
        out_max[0] = _dyn_max_y
        return

    # ── 새 채널 생성 (connected_slots 기준) ──────────────────────
    # active_slots(position_table_merged)가 리셋 직후 잠시 비어도
    # 센서 데이터(connected_slots)가 있으면 채널을 즉시 생성
    for slot in connected_slots:
        if slot not in _slot_to_key:
            key = f'index_{_ch_count}'
            _ch_count += 1
            _channels[key] = {
                'buf':    [],
                'times':  [],
                'cur_y':  0.0,
                'active': True,
                'warmup': True,   # 첫 1프레임은 출력 제외 — GLSL 텍스처 크기 변화로 인한 깜빡임 방지
            }
            _key_order.append(key)
            _slot_to_key[slot] = key
            if _session_start is None:
                _session_start = effective_now

    # ── cur_y 업데이트 (Maxspeed 클램프 적용) ───────────────────
    for slot, speed in active_slots.items():
        if slot not in _slot_to_key:
            continue  # 아직 채널 없는 슬롯 (race condition 방어)
        ch = _channels[_slot_to_key[slot]]
        # warmup 프레임(재연결 첫 1프레임)은 cur_y 적산 스킵
        # — position_table_merged의 speed가 이전-현재 위치 차분 기반이라
        #   재연결 직후 첫 speed 값이 비정상적으로 크게 튀는 경우를 차단
        if ch.get('warmup'):
            continue
        if max_speed > 0.0:
            speed = min(speed, max_speed)
        ch['cur_y'] += speed * dt

    # ── 끊긴 슬롯: 윈도우 내 버퍼 전체 저장 후 inactive 마킹 ───
    for slot in list(_slot_to_key.keys()):
        if slot not in active_slots and slot not in connected_slots and slot not in hidden_slots:
            key = _slot_to_key[slot]
            ch  = _channels[key]
            valid = [v for v in ch['buf'] if v > -0.5]
            if valid:
                _archive(key, ch['buf'], archive_folder)
                print(f'[line_chop] slot {slot} disconnected — saved {len(valid)} samples → {key}.csv')
            ch['active'] = False
            del _slot_to_key[slot]

    # ── 연결 중일 때만 샘플 append ──────────────────────────────
    if any_connected:
        active_visible_keys = {key for slot, key in _slot_to_key.items() if slot not in hidden_slots}
        for key, ch in _channels.items():
            if key in active_visible_keys:
                val = ch['cur_y']   # 0도 유효값 — 리셋 직후 cur_y=0부터 즉시 그리기 시작
            else:
                val = NO_DATA
            ch['buf'].append(val)
            ch['times'].append(effective_now)
        _frame_count += 1

    # ── 시간 기반 트리밍 (윈도우 초과분 아카이브 후 제거) ────────
    win_sec  = _window_seconds(scriptOp)
    t_cutoff = effective_now - win_sec
    for key, ch in _channels.items():
        cut = 0
        while cut < len(ch['times']) and ch['times'][cut] < t_cutoff:
            cut += 1
        if cut > 0:
            _archive(key, ch['buf'][:cut], archive_folder)
            ch['buf']   = ch['buf'][cut:]
            ch['times'] = ch['times'][cut:]

    # ── 윈도우 전체가 NO_DATA인 비활성 채널 제거 ────────────────
    for key in list(_key_order):
        ch = _channels.get(key)
        if ch is None or ch['active']:
            continue
        if all(v < -0.5 for v in ch['buf']):
            del _channels[key]
            _key_order.remove(key)

    if not _key_order:
        _session_start = None

    # ── dynamic maxY 계산 ────────────────────────────────────────
    peak = max((ch['cur_y'] for ch in _channels.values()), default=0.0)

    if adaptive_scale:
        # 적응형: peak에 맞게 scale up, 이후 easing으로 복귀
        if peak > base_max_y:
            _dyn_max_y  = max(peak, _dyn_max_y)
            _ease_start = None
            _ease_from  = None
        elif _dyn_max_y > base_max_y:
            if _ease_start is None:
                _ease_start = now
                _ease_from  = _dyn_max_y
            t      = min((now - _ease_start) / EASE_DURATION, 1.0)
            t_ease = t * t * (3.0 - 2.0 * t)
            _dyn_max_y = _ease_from * (1.0 - t_ease) + base_max_y * t_ease
            if t >= 1.0:
                _dyn_max_y  = base_max_y
                _ease_start = None
        else:
            _dyn_max_y = base_max_y
    else:
        # 고정: 항상 base_max_y. 초과값은 GLSL에서 자연 클립
        _dyn_max_y  = base_max_y
        _ease_start = None
        _ease_from  = None

    # ── 시간 기반 리샘플링 출력 ──────────────────────────────────
    num_out = _num_out_samples(scriptOp)
    if _session_start is not None and effective_now - _session_start < win_sec:
        t_start = _session_start
    else:
        t_start = effective_now - win_sec

    scriptOp.clear()
    scriptOp.numSamples = max(num_out, 1)

    for key in _key_order:
        if key not in _channels:
            continue
        ch = _channels[key]

        # warmup: 첫 1프레임은 all-NO_DATA로 출력 (GLSL 텍스처 크기 안정화)
        if ch.get('warmup'):
            ch['warmup'] = False
            out_ch = scriptOp.appendChan(key)
            out_ch.vals = [NO_DATA] * num_out
            continue

        buf_np   = _np.array(ch['buf'],   dtype=_np.float32)
        times_np = _np.array(ch['times'], dtype=_np.float64)
        valid    = buf_np > -0.5

        output = _np.full(num_out, NO_DATA, dtype=_np.float32)

        if valid.any():
            fracs    = (times_np[valid] - t_start) / win_sec
            in_range = (fracs >= 0.0) & (fracs < 1.0)
            if in_range.any():
                idxs = _np.clip(
                    (fracs[in_range] * num_out).astype(_np.int32), 0, num_out - 1
                )
                output[idxs] = buf_np[valid][in_range]
                last_valid_idx = int(idxs.max())

                # forward-fill: 첫 유효값 이전은 NO_DATA 유지
                sub  = output[:last_valid_idx + 1]
                mask = sub > -0.5
                fi   = _np.where(mask, _np.arange(last_valid_idx + 1), 0)
                _np.maximum.accumulate(fi, out=fi)
                output[:last_valid_idx + 1] = sub[fi]

        out_ch = scriptOp.appendChan(key)
        out_ch.vals = output        # numpy 직접 대입 — .tolist() 없음

    # ── highlight 비트마스크 ─────────────────────────────────────
    highlight_mask = 0
    if st is not None and st.numRows >= 2:
        st_h2 = {str(st[0, c]): c for c in range(st.numCols)}
        if 'slot' in st_h2 and 'touch_count' in st_h2:
            for row in range(1, st.numRows):
                try:
                    slot = int(st[row, st_h2['slot']])
                    tc   = int(st[row, st_h2['touch_count']])
                    if tc >= 1 and slot in _slot_to_key:
                        key = _slot_to_key[slot]
                        if key in _key_order:
                            idx = _key_order.index(key)
                            highlight_mask |= (1 << idx)
                except Exception:
                    continue

    out_hl      = scriptOp.appendChan('_highlight')
    out_hl.vals = [float(highlight_mask)] * max(num_out, 1)

    out_max      = scriptOp.appendChan('_maxY')
    out_max.vals = [_dyn_max_y] * max(num_out, 1)


def onPulse(scriptOp, channel):
    """Reset이 Pulse 타입으로 설정된 경우를 위한 fallback."""
    if channel.name == 'Reset':
        try:
            scriptOp.par.Reset = 1  # cook()에서 Toggle처럼 감지
        except Exception:
            _do_reset(scriptOp)

def onSetupParameters(scriptOp):
	"""Auto-generated by Component Editor"""
	# manual changes to anything other than parJSON will be	# destroyed by Comp Editor unless doc string above is	# changed

	TDJSON = op.TDModules.mod.TDJSON
	parJSON = """
	{
		"Custom": {
			"Archivepath": {
				"name": "Archivepath",
				"tupletName": "Archivepath",
				"label": "Archive Path",
				"page": "Custom",
				"sequence": null,
				"style": "Folder",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": "",
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": ""
			},
			"Reset": {
				"name": "Reset",
				"tupletName": "Reset",
				"label": "Reset",
				"page": "Custom",
				"sequence": null,
				"style": "Toggle",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": false,
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": ""
			},
			"Maxspeed": {
				"name": "Maxspeed",
				"tupletName": "Maxspeed",
				"label": "Max Speed",
				"page": "Custom",
				"sequence": null,
				"style": "Float",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": 0.0,
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": "",
				"min": 0.0,
				"max": 1.0,
				"normMin": 0.0,
				"normMax": 1.0,
				"clampMin": false,
				"clampMax": false
			},
			"Maxy": {
				"name": "Maxy",
				"tupletName": "Maxy",
				"label": "Max Y",
				"page": "Custom",
				"sequence": null,
				"style": "Float",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": 0.0,
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": "",
				"min": 0.0,
				"max": 1.0,
				"normMin": 0.0,
				"normMax": 1.0,
				"clampMin": false,
				"clampMax": false
			},
			"Adaptivescale": {
				"name": "Adaptivescale",
				"tupletName": "Adaptivescale",
				"label": "Adaptive Scale",
				"page": "Custom",
				"sequence": null,
				"style": "Toggle",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": true,
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": ""
			},
			"Fps": {
				"name": "Fps",
				"tupletName": "Fps",
				"label": "FPS",
				"page": "Custom",
				"sequence": null,
				"style": "Int",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": 30,
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": "",
				"min": 0.0,
				"max": 1.0,
				"normMin": 0.0,
				"normMax": 60.0,
				"clampMin": false,
				"clampMax": false
			},
			"Windowminutes": {
				"name": "Windowminutes",
				"tupletName": "Windowminutes",
				"label": "Window Minutes",
				"page": "Custom",
				"sequence": null,
				"style": "Int",
				"size": 1,
				"defaultMode": "CONSTANT",
				"default": 30,
				"defaultExpr": "",
				"defaultBindExpr": "",
				"enable": true,
				"startSection": false,
				"readOnly": false,
				"enableExpr": null,
				"help": "",
				"min": 0.0,
				"max": 1.0,
				"normMin": 0.0,
				"normMax": 60000.0,
				"clampMin": false,
				"clampMax": false
			}
		}
	}
	"""
	parData = TDJSON.textToJSON(parJSON)
	TDJSON.addParametersFromJSONOp(scriptOp, parData, destroyOthers=True)