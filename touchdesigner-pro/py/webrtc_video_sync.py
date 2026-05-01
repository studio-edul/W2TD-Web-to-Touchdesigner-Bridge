"""
W2TD Video TX Sync
==================
DAT Execute — webrtc_video_container 안에 배치.
webrtc_table 또는 w2td_config 변경 시 호출되어 비디오 TX 노드를 생성/삭제하고
WebRTC 재협상(addTrack + createOffer)을 처리한다.

TD 설정 방법:
  1. webrtc_video_container 안에 DAT Execute DAT 추가
  2. Parameters > DATs:
       ../webrtc_audio_container/webrtc_table
       ../../w2td_config
     (두 DAT 모두 등록 — 클라이언트 연결 중 videoout 변경 시에도 즉시 반응)
  3. Parameters > Table Change: On
  4. 이 파일을 Callbacks DAT로 지정

생성되는 노드 구조 (webrtc_video_container 내부):
  select_video_slot{N}  →  flip_top_{N}  →  video_stream_out_{N}

  select_video_slot{N}: video_slot{N}를 참조하는 selectTOP
  flip_top_{N}:         flipTOP (필요 시 방향 보정)
  video_stream_out_{N}: WebRTC Video Stream Out TOP (TD→모바일 송신)

video_slot{N} 위치: W2TD_Pro와 같은 계층 (project1/video_slot{N})
  → select 노드에서 ../../video_slot{N} 로 참조
"""

W2TD_BASE = 'W2TD_Pro'
BLOCK_HEIGHT = 300   # cam_render_sync.py와 동일해야 함! 두 파일 항상 같은 값 유지
CAM_ROW_H   = 100   # webrtc TX 행이 cam 행에서 얼마나 아래에 위치할지


# ── 노드 탐색 헬퍼 ────────────────────────────────────────────────────────────

def _this_container():
	"""이 DAT의 부모 컨테이너(webrtc_video_container)를 반환."""
	try:
		return parent(1)
	except NameError:
		return op('webrtc_video_container')


def _w2td_base():
	"""W2TD_Pro COMP를 반환."""
	try:
		p = parent(1)
		if p and p.name in ('W2TD_Pro', 'W2TD'):
			return p
		p2 = parent(2)
		if p2 and p2.name in ('W2TD_Pro', 'W2TD'):
			return p2
	except NameError:
		pass
	for proj in ('project1', 'project'):
		w = op(f'{proj}/{W2TD_BASE}')
		if w:
			return w
	return op(W2TD_BASE)


def _get_webrtc():
	"""webrtc_audio_container/webrtc_dat 반환."""
	base = _w2td_base()
	if base:
		ac = base.op('webrtc_audio_container')
		if ac:
			w = ac.op('webrtc_dat')
			if w:
				return w
	return op('webrtc_dat')


def _get_webrtc_table():
	"""webrtc_table 반환. webrtc_video_container → webrtc_audio_container 순으로 탐색."""
	# 1. webrtc_video_container 안에 바로 있는 경우 (사용자가 직접 배치한 경우)
	container = _this_container()
	if container:
		t = container.op('webrtc_table')
		if t:
			return t
	# 2. 기존 위치: webrtc_audio_container
	base = _w2td_base()
	if base:
		ac = base.op('webrtc_audio_container')
		if ac:
			t = ac.op('webrtc_table')
			if t:
				return t
	return op('webrtc_table')


def _read_video_tx_enabled():
	"""w2td_config의 Video 키 값으로 video TX 활성화 여부를 반환."""
	base = _w2td_base()
	cfg_dat = None
	if base:
		cfg_dat = base.op('w2td_config')
	if cfg_dat is None:
		cfg_dat = op('w2td_config')
	if cfg_dat is None:
		return True  # 기본값: 활성화
	for r in range(1, cfg_dat.numRows):
		try:
			key = str(cfg_dat[r, 0]).strip().lower()
			val = str(cfg_dat[r, 1]).strip().lower()
			if key in ('video', 'videoout'):
				try:
					return bool(int(float(val)))
				except (ValueError, TypeError):
					# 'td', 'js', 'color' 등 문자열 → 'none'/'0'/'false' 아니면 활성화
					return val not in ('none', '0', 'false', 'off', '')
		except Exception:
			pass
	return True


# ── webrtc_table 읽기 ─────────────────────────────────────────────────────────

def _read_rows():
	"""webrtc_table에서 연결된/연결 중인 슬롯 목록 반환. [(slot, conn_id), ...]"""
	t = _get_webrtc_table()
	if t is None or t.numRows < 2:
		return []
	seen = {}
	for r in range(1, t.numRows):
		try:
			conn_id = str(t[r, 'conn_id']).strip()
			if not conn_id or '-' not in conn_id or len(conn_id) < 10:
				continue
			state = str(t[r, 'state']).strip().lower()
			if state not in ('connected', 'connecting'):
				continue
			slot = int(t[r, 'slot'])
			if slot < 1:
				continue
			seen[slot] = (slot, conn_id)
		except (ValueError, TypeError):
			pass
	return sorted(seen.values())


# ── Video Stream Out TOP 파라미터 설정 ────────────────────────────────────────

def _set_video_out_params(top, conn_id):
	"""Video Stream Out TOP에 WebRTC 파라미터 설정."""
	webrtc = _get_webrtc()
	if webrtc is None:
		return
	# Protocol/Mode → WebRTC
	for par_name in ('protocol', 'Protocol', 'mode', 'Mode'):
		if hasattr(top.par, par_name):
			try:
				setattr(top.par, par_name, 'webrtc')
				break
			except Exception:
				try:
					setattr(top.par, par_name, 'WebRTC')
					break
				except Exception:
					pass
	# WebRTC DAT
	for par_name in ('webrtc', 'Webrtc'):
		if hasattr(top.par, par_name):
			try:
				setattr(top.par, par_name, webrtc)
				break
			except Exception:
				pass
	# WebRTC Connection (conn_id)
	for par_name in ('webrtcconnection', 'Webrtcconnection', 'connection', 'Connection'):
		if hasattr(top.par, par_name):
			try:
				setattr(top.par, par_name, conn_id)
				break
			except Exception as e:
				print(f'[W2TD Video Sync] Set {par_name} failed: {e}')
	# Active = 1
	for par_name in ('active', 'Active'):
		if hasattr(top.par, par_name):
			try:
				setattr(top.par, par_name, 1)
			except Exception:
				pass


# ── Video Track 자동 선택 ──────────────────────────────────────────────────────

def _auto_select_video_track(vout, track_name, attempt=1, max_attempts=15):
	"""Video Stream Out TOP의 webrtctrack 파라미터를 자동 선택. 메뉴가 채워질 때까지 재시도."""
	if vout is None:
		return
	for par_name in ('webrtctrack', 'Webrtctrack', 'track', 'Track'):
		if hasattr(vout.par, par_name):
			try:
				p = getattr(vout.par, par_name)
				menu_names = p.menuNames if hasattr(p, 'menuNames') else []
				if menu_names:
					chosen = track_name if track_name in menu_names else menu_names[0]
					setattr(vout.par, par_name, chosen)
					print(f'[W2TD Video Sync] Auto-selected video track "{chosen}" on {vout.name} (attempt {attempt})')
					return
			except Exception:
				pass
	# 메뉴가 아직 비어 있으면 재시도
	if attempt < max_attempts:
		_vout = vout
		_tn = track_name
		_att = attempt
		def _retry():
			_auto_select_video_track(_vout, _tn, _att + 1, max_attempts)
		run(_retry, delayFrames=5, fromOP=_vout)
	else:
		print(f'[W2TD Video Sync] Warning: could not auto-select video track on {vout.name} after {max_attempts} attempts')


# ── 메인 sync ─────────────────────────────────────────────────────────────────

def sync():
	"""webrtc_video_container 안의 비디오 TX 노드를 webrtc_table에 맞게 동기화."""
	if not _read_video_tx_enabled():
		print('[W2TD Video Sync] Video TX disabled in config — skipping')
		return

	container = _this_container()
	if container is None:
		print('[W2TD Video Sync] Error: webrtc_video_container not found')
		return

	rows = _read_rows()
	active_slots = {slot for slot, _ in rows}
	slot_to_conn = {slot: conn_id for slot, conn_id in rows}

	# 기존 TX 노드 스캔
	existing_selects = {}
	existing_flips = {}
	existing_outs = {}
	for child in container.children:
		n = child.name
		if n.startswith('select_video_slot') and n[17:].isdigit():
			existing_selects[int(n[17:])] = child
		elif n.startswith('flip_top_') and n[9:].isdigit():
			existing_flips[int(n[9:])] = child
		elif n.startswith('video_stream_out_') and n[17:].isdigit():
			existing_outs[int(n[17:])] = child

	# 비활성 슬롯 노드 삭제
	stale = (set(existing_selects) | set(existing_flips) | set(existing_outs)) - active_slots
	for slot in stale:
		for node in (existing_selects.get(slot), existing_flips.get(slot), existing_outs.get(slot)):
			if node:
				try:
					node.destroy()
					print(f'[W2TD Video Sync] Destroyed nodes for slot {slot}')
				except Exception as e:
					print(f'[W2TD Video Sync] Error destroying node slot {slot}: {e}')

	# 활성 슬롯 노드 생성/갱신
	newly_created = []
	for idx, slot in enumerate(sorted(slot_to_conn.keys())):
		conn_id = slot_to_conn[slot]

		# 1. select_video_slot{N} → ../../video_slot{N} 참조
		#    경로: webrtc_video_container(./), W2TD_Pro(../), project1(../../)
		vsel = existing_selects.get(slot) or container.op(f'select_video_slot{slot}')
		is_new_sel = vsel is None
		if is_new_sel:
			try:
				vsel = container.create('selectTOP', f'select_video_slot{slot}')
				print(f'[W2TD Video Sync] Created select_video_slot{slot}')
			except Exception as e:
				print(f'[W2TD Video Sync] Error creating select_video_slot{slot}: {e}')
				continue
		if vsel:
			for par_name in ('top', 'Top', 'input', 'Input'):
				if hasattr(vsel.par, par_name):
					try:
						setattr(vsel.par, par_name, f'../../video_slot{slot}')
						break
					except Exception:
						pass
			try:
				vsel.nodeX = 0
				vsel.nodeY = -idx * BLOCK_HEIGHT - CAM_ROW_H
				print(f'[W2TD Video Sync] select_video_slot{slot} nodeY={vsel.nodeY}')
			except Exception as e:
				print(f'[W2TD Video Sync] select_video_slot{slot} nodeY error: {e}')

		# 2. flip_top_{N}
		vflip = existing_flips.get(slot) or container.op(f'flip_top_{slot}')
		is_new_flip = vflip is None
		if is_new_flip:
			try:
				vflip = container.create('flipTOP', f'flip_top_{slot}')
				print(f'[W2TD Video Sync] Created flip_top_{slot}')
			except Exception as e:
				print(f'[W2TD Video Sync] Error creating flip_top_{slot}: {e}')
				vflip = None
		if vflip:
			if is_new_flip and vsel:
				try:
					vflip.setInputs([vsel])
				except Exception:
					try:
						vflip.inputConnectors[0].connect(vsel)
					except Exception:
						pass
			try:
				vflip.nodeX = 150
				vflip.nodeY = -idx * BLOCK_HEIGHT - CAM_ROW_H
				print(f'[W2TD Video Sync] flip_top_{slot} nodeY={vflip.nodeY}')
			except Exception as e:
				print(f'[W2TD Video Sync] flip_top_{slot} nodeY error: {e}')

		# 3. video_stream_out_{N}
		vout = existing_outs.get(slot) or container.op(f'video_stream_out_{slot}')
		is_new_out = vout is None
		if is_new_out:
			try:
				vout = container.create('videostreamoutTOP', f'video_stream_out_{slot}')
				print(f'[W2TD Video Sync] Created video_stream_out_{slot}')
			except Exception as e:
				print(f'[W2TD Video Sync] Error creating video_stream_out_{slot}: {e}')
				vout = None
		if vout:
			if is_new_out:
				upstream = vflip if vflip else vsel
				if upstream:
					try:
						vout.setInputs([upstream])
					except Exception:
						try:
							vout.inputConnectors[0].connect(upstream)
						except Exception:
							pass
			try:
				vout.nodeX = 300
				vout.nodeY = -idx * BLOCK_HEIGHT - CAM_ROW_H
				print(f'[W2TD Video Sync] video_stream_out_{slot} nodeY={vout.nodeY}')
			except Exception as e:
				print(f'[W2TD Video Sync] video_stream_out_{slot} nodeY error: {e}')
			_set_video_out_params(vout, conn_id)

		if (is_new_sel or is_new_out) and slot not in newly_created:
			newly_created.append(slot)

	# 신규 슬롯에 대해 WebRTC 재협상 트리거
	# delayFrames=5: webrtc_table_sync.py의 addTrack(audio) at frame=3 이후 실행됨
	if newly_created:
		webrtc = _get_webrtc()
		if webrtc:
			_slots_to_offer = list(newly_created)
			_conn_map = dict(slot_to_conn)
			_wrtc = webrtc

			_container = container

			def _trigger_video_offers():
				for s in _slots_to_offer:
					cid = _conn_map.get(s)
					if not cid:
						continue
					try:
						track_name = f'video_out_{s}'
						_wrtc.addTrack(cid, track_name, 'video')
						print(f'[W2TD Video Sync] addTrack("{track_name}", video) slot {s}')
						_wrtc.createOffer(cid)
						print(f'[W2TD Video Sync] createOffer slot {s}')
					except Exception as ex:
						print(f'[W2TD Video Sync] addTrack/createOffer error slot {s}: {ex}')
						continue
					# createOffer 후 reanswer가 완료되면 track 메뉴가 채워짐 → 자동 선택 시작
					vout = _container.op(f'video_stream_out_{s}')
					if vout:
						_auto_select_video_track(vout, track_name)

			run(_trigger_video_offers, delayFrames=5, fromOP=_wrtc)

	if rows:
		print(f'[W2TD Video Sync] {len(rows)} slot(s) synced, {len(newly_created)} new')
	else:
		print('[W2TD Video Sync] No connections — all video TX nodes removed')


def onTableChange(dat, prevDAT, info):
	"""webrtc_table 또는 w2td_config 변경 시 호출.
	DATs 파라미터에 두 테이블을 모두 등록하면 videoout 변경만으로도 즉시 반응한다."""
	sync()
