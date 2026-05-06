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
  - 초과 데이터: .npy 파일로 아카이브 후 버퍼에서 제거

Parent COMP 파라미터:
  Speepdscale    float  (미사용 — GLSL uSpeedScale로 처리)
  Windowminutes  int    출력 윈도우 분 단위  기본값 30
"""

import time as _time
import os as _os
import datetime as _dt

NO_DATA       = -1.0
EASE_DURATION = 2.0   # maxY 복귀 easing 시간(초)
OUTPUT_FPS    = 30    # 출력 고정 해상도 — Fps 파라미터와 무관

_last_cook_t = None
_ch_count    = 0
_frame_count = 0

_channels    = {}  # { key: {'buf': list, 'times': list, 'cur_y': float, 'active': bool} }
_key_order   = []
_slot_to_key = {}  # { slot: key }

_dyn_max_y  = None
_ease_start = None
_ease_from  = None


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


def _archive(key, excess_buf, folder):
    """초과 버퍼를 CSV 파일에 append 저장."""
    if not excess_buf:
        return
    try:
        if not folder:
            folder = project.folder
        _os.makedirs(folder, exist_ok=True)
        date_str    = _dt.datetime.now().strftime('%Y%m%d')
        filename    = f'{date_str}_{key}.csv'
        path        = _os.path.join(folder, filename)
        with open(path, 'a') as f:
            for v in excess_buf:
                f.write(f'{v}\n')
    except Exception as e:
        print(f'[line_chop] archive error: {e}')


def cook(scriptOp):
    global _last_cook_t, _ch_count, _frame_count
    global _dyn_max_y, _ease_start, _ease_from

    scriptOp.rate = OUTPUT_FPS  # lock X-axis scale regardless of TD timeline FPS

    now          = _time.monotonic()
    dt           = (now - _last_cook_t) if _last_cook_t is not None else 0.0
    _last_cook_t = now

    # ── sensor_table에서 실제 연결된 슬롯 수집 ──────────────
    # az != 0 체크: 센서 비활성 시 az=0, 활성 시 중력가속도(~9.8)가 들어옴
    connected_slots = set()
    st = op('sensor_table')
    if st is not None and st.numRows >= 2:
        st_h = {str(st[0, c]): c for c in range(st.numCols)}
        if 'slot' in st_h and 'connected' in st_h:
            for row in range(1, st.numRows):
                try:
                    if int(st[row, st_h['connected']]) != 1:
                        continue
                    sensor_axes = ('az', 'ga', 'gb', 'gg')
                    if not any(col in st_h and abs(float(st[row, st_h[col]])) > 0.1 for col in sensor_axes):
                        continue  # 센서 미활성 — az/ga/gb/gg 전부 0이면 선 그리기 시작 안 함
                    connected_slots.add(int(st[row, st_h['slot']]))
                except Exception:
                    continue

    # ── position_table_merged 읽기 ───────────────────────────────────
    active_slots = {}
    pt = op('position_table_merged')
    if pt is not None and pt.numRows >= 2:
        headers = {str(pt[0, c]): c for c in range(pt.numCols)}
        if 'slot' in headers and 'speed' in headers:
            for row in range(1, pt.numRows):
                try:
                    slot  = int(pt[row, headers['slot']])
                    if slot not in connected_slots:
                        continue
                    speed = float(pt[row, headers['speed']])
                    active_slots[slot] = speed
                except Exception:
                    continue

    # ── 백그라운드(visibility:hidden) 슬롯 수집 — sensor_table.visibility 기준 ──
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

    # ── base maxY 파라미터 ────────────────────────────────────
    try:
        base_max_y = float(scriptOp.par.Maxy)
        if base_max_y <= 0:
            base_max_y = 100.0
    except Exception:
        base_max_y = 100.0

    if _dyn_max_y is None:
        _dyn_max_y = base_max_y

    # 아직 아무도 접속 안 했으면 대기
    if not active_slots and not _channels:
        scriptOp.clear()
        scriptOp.numSamples = 1
        scriptOp.appendChan('_highlight')[0] = 0.0
        out_max    = scriptOp.appendChan('_maxY')
        out_max[0] = _dyn_max_y
        return

    # ── 새 채널 생성 ─────────────────────────────────────────
    for slot in active_slots:
        if slot not in _slot_to_key:
            key = f'index_{_ch_count}'
            _ch_count += 1
            _channels[key] = {
                'buf':        [],   # cur_y 값
                'times':      [],   # monotonic 타임스탬프
                'cur_y':      0.0,
                'active':     True,
                'created_at': now,
            }
            _key_order.append(key)
            _slot_to_key[slot] = key

    # ── 아카이브 저장 경로 ────────────────────────────────────
    try:
        archive_folder = str(scriptOp.par.Archivepath).strip()
    except Exception:
        archive_folder = ''

    # ── cur_y 업데이트 (speed_scale 미적용 — 원본 데이터 보존) ──
    for slot, speed in active_slots.items():
        ch = _channels[_slot_to_key[slot]]
        ch['cur_y'] += speed * dt

    # ── 끊긴 슬롯: inactive 마킹 (백그라운드 슬롯은 유지) ───
    for slot in list(_slot_to_key.keys()):
        if slot not in active_slots and slot not in connected_slots and slot not in hidden_slots:
            _channels[_slot_to_key[slot]]['active'] = False
            del _slot_to_key[slot]

    # ── 모든 채널에 매 프레임 1샘플 append (타임스탬프 포함) ─
    # 연결 중 + 화면 보임: cur_y 기록
    # 끊김 또는 화면 숨김(hidden): NO_DATA → GLSL 스킵, 선 중단
    # 재연결/복귀 시 fill-forward가 끊긴 구간을 소급해서 채움
    active_visible_keys = {key for slot, key in _slot_to_key.items() if slot not in hidden_slots}
    for key, ch in _channels.items():
        if key in active_visible_keys:
            val = ch['cur_y'] if ch['cur_y'] > 0.0 else NO_DATA
        else:
            val = NO_DATA
        ch['buf'].append(val)
        ch['times'].append(now)

    _frame_count += 1

    # ── 시간 기반 트리밍 (윈도우 초과분 아카이브 후 제거) ────
    win_sec  = _window_seconds(scriptOp)
    t_cutoff = now - win_sec
    for key, ch in _channels.items():
        cut = 0
        while cut < len(ch['times']) and ch['times'][cut] < t_cutoff:
            cut += 1
        if cut > 0:
            _archive(key, ch['buf'][:cut], archive_folder)
            ch['buf']   = ch['buf'][cut:]
            ch['times'] = ch['times'][cut:]

    # ── 윈도우 전체가 NO_DATA인 비활성 채널 제거 ─────────────
    for key in list(_key_order):
        ch = _channels.get(key)
        if ch is None or ch['active']:
            continue
        if all(v < -0.5 for v in ch['buf']):
            del _channels[key]
            _key_order.remove(key)

    # ── dynamic maxY 계산 ────────────────────────────────────
    peak = max((ch['cur_y'] for ch in _channels.values()), default=0.0)

    if peak > base_max_y:
        # 최대값 초과 → 즉시 snap up, easing 취소
        _dyn_max_y  = max(peak, _dyn_max_y)
        _ease_start = None
        _ease_from  = None
    elif _dyn_max_y > base_max_y:
        # 초과값 없음 → base_max_y 로 easing 복귀
        if _ease_start is None:
            _ease_start = now
            _ease_from  = _dyn_max_y
        t          = min((now - _ease_start) / EASE_DURATION, 1.0)
        # ease in/out (smoothstep): t^2 * (3 - 2t)
        t_ease     = t * t * (3.0 - 2.0 * t)
        _dyn_max_y = _ease_from * (1.0 - t_ease) + base_max_y * t_ease
        if t >= 1.0:
            _dyn_max_y  = base_max_y
            _ease_start = None
    else:
        _dyn_max_y = base_max_y

    # ── 시간 기반 리샘플링 출력 (numSamples 고정 — Fps 무관) ─
    num_out  = _num_out_samples(scriptOp)
    t_start  = now - win_sec
    scriptOp.clear()
    scriptOp.numSamples = max(num_out, 1)

    for key in _key_order:
        if key not in _channels:
            continue
        ch     = _channels[key]
        output = [NO_DATA] * num_out
        # 채널이 윈도우보다 짧으면 왼쪽부터 시작 (오른쪽 끝에서 시작하지 않음)
        ch_created  = ch.get('created_at', t_start)
        ch_t_start  = ch_created if (now - ch_created) < win_sec else t_start
        # 실제 샘플을 시간 기반으로 출력 인덱스에 매핑
        last_valid_idx = -1
        for t, v in zip(ch['times'], ch['buf']):
            if v < -0.5:
                continue
            frac = (t - ch_t_start) / win_sec
            idx  = int(frac * num_out)
            if 0 <= idx < num_out:
                output[idx] = v
                last_valid_idx = max(last_valid_idx, idx)
        # 마지막 유효 샘플까지만 갭 채움
        # 끊김/숨김 이후 구간은 채우지 않음 → 선 중단
        # 재연결 시 새 유효 샘플이 생기면 그 사이가 소급 채워짐
        if last_valid_idx >= 0:
            last_v = NO_DATA
            for i in range(last_valid_idx + 1):
                if output[i] > -0.5:
                    last_v = output[i]
                elif last_v > -0.5:
                    output[i] = last_v
        out_ch = scriptOp.appendChan(key)
        out_ch.vals = output

    # ── highlight 비트마스크 계산 (sensor_table touch_count) ─
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

    # ── _highlight 채널 출력 (GLSL이 마지막-1 row에서 읽음) ─
    out_hl      = scriptOp.appendChan('_highlight')
    out_hl.vals = [float(highlight_mask)] * max(num_out, 1)

    # ── _maxY 채널 출력 (GLSL이 마지막 row에서 읽음) ─────────
    out_max      = scriptOp.appendChan('_maxY')
    out_max.vals = [_dyn_max_y] * max(num_out, 1)

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