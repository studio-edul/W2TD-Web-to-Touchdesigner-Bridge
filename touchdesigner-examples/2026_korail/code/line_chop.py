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
EASE_DURATION = 2.0       # maxY 복귀 easing 시간(초)

_last_cook_t   = None
_ch_count      = 0
_frame_count   = 0                    # 누적 프레임 수
_session_start = _time.monotonic()    # TD 시작(모듈 로드) 시점

_channels    = {}         # { key: {'buf': list, 'cur_y': float, 'active': bool} }
_key_order   = []
_slot_to_key = {}         # { slot: key }

_dyn_max_y  = None        # 현재 유효 maxY
_ease_start = None        # easing 시작 시각
_ease_from  = None        # easing 시작 시점의 maxY 값


def _window_samples(scriptOp):
    """Windowminutes + Fps 파라미터 → 슬라이딩 윈도우 샘플 수."""
    try:
        win_min = float(scriptOp.par.Windowminutes)
    except Exception:
        win_min = 30.0
    try:
        fps = float(scriptOp.par.Fps)
        if fps <= 0:
            fps = 30.0
    except Exception:
        fps = 30.0
    return max(int(win_min * 60.0 * fps), 60)


def _archive(key, excess_buf, folder):
    """초과 버퍼를 CSV 파일에 append 저장."""
    if not excess_buf:
        return
    try:
        if not folder:
            folder = project.folder
        date_str    = _dt.datetime.now().strftime('%Y%m%d')
        proj_name   = project.name
        filename    = f'{proj_name}_{date_str}_{key}.csv'
        path        = _os.path.join(folder, filename)
        with open(path, 'a') as f:
            for v in excess_buf:
                f.write(f'{v}\n')
    except Exception as e:
        print(f'[line_chop] archive error: {e}')


def cook(scriptOp):
    global _last_cook_t, _ch_count, _frame_count
    global _dyn_max_y, _ease_start, _ease_from

    now          = _time.monotonic()
    dt           = (now - _last_cook_t) if _last_cook_t is not None else 0.0
    _last_cook_t = now

    # ── sensor_table에서 실제 연결된 슬롯 수집 ──────────────
    connected_slots = set()
    st = op('sensor_table')
    if st is not None and st.numRows >= 2:
        st_h = {str(st[0, c]): c for c in range(st.numCols)}
        if 'slot' in st_h and 'connected' in st_h:
            for row in range(1, st.numRows):
                try:
                    if int(st[row, st_h['connected']]) == 1:
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
                    if connected_slots and slot not in connected_slots:
                        continue
                    speed = float(pt[row, headers['speed']])
                    active_slots[slot] = speed
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
                'buf':    [NO_DATA] * _frame_count,
                'cur_y':  0.0,
                'active': True,
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

    # ── 끊긴 슬롯: inactive 마킹 ─────────────────────────────
    for slot in list(_slot_to_key.keys()):
        if slot not in active_slots:
            _channels[_slot_to_key[slot]]['active'] = False
            del _slot_to_key[slot]

    # ── 모든 채널에 매 프레임 1샘플 append ───────────────────
    for ch in _channels.values():
        ch['buf'].append(ch['cur_y'] if ch['active'] else NO_DATA)

    _frame_count += 1

    # ── 슬라이딩 윈도우 계산 ─────────────────────────────────
    win = _window_samples(scriptOp)

    # ── 초과 버퍼 아카이브 + 트리밍 ──────────────────────────
    for key, ch in _channels.items():
        buf = ch['buf']
        if len(buf) > win * 2:
            cutoff = len(buf) - win
            _archive(key, buf[:cutoff], archive_folder)
            ch['buf'] = buf[cutoff:]

    # ── 윈도우 전체가 NO_DATA인 비활성 채널 제거 ─────────────
    out_len = min(win, _frame_count)
    for key in list(_key_order):
        ch = _channels.get(key)
        if ch is None or ch['active']:
            continue
        window = ch['buf'][-out_len:] if len(ch['buf']) >= out_len else ch['buf']
        if all(v < -0.5 for v in window):
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

    # ── 채널 출력 (최근 win 샘플만) ─────────────────────────
    out_len = min(win, _frame_count)
    scriptOp.clear()
    scriptOp.numSamples = max(out_len, 1)

    for key in _key_order:
        if key not in _channels:
            continue
        buf    = _channels[key]['buf']
        window = buf[-out_len:] if len(buf) >= out_len else buf
        out_ch = scriptOp.appendChan(key)
        out_ch.vals = window

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
    out_hl.vals = [float(highlight_mask)] * max(out_len, 1)

    # ── _maxY 채널 출력 (GLSL이 마지막 row에서 읽음) ─────────
    out_max      = scriptOp.appendChan('_maxY')
    out_max.vals = [_dyn_max_y] * max(out_len, 1)

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