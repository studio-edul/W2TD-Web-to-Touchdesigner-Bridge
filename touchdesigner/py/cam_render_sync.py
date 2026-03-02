"""
sensor_table -> Web Render TOP sync
==================================
Creates web_render_top_1, web_render_top_2, ... based on connected slots.
Each TOP loads cam_receiver.html?slot=N for that slot.
Setup in TD:
  1. Create webrtc_video_container (Container COMP)
  2. Create DAT Execute DAT inside webrtc_video_container
  3. Set "DATs" to: ../sensor_table (상대경로 — sensor_table이 한 단계 위에 있을 때)
  4. Enable "Table Change"
  5. Paste this script
상대 경로: DAT Execute가 webrtc_video_container 안에 있으면 ../sensor_table
"""
NODE_OFFSET_Y = 100


def _w2td_video():
	"""webrtc_video_container. DAT Execute가 그 안에 있으면 me.parent() 사용."""
	try:
		p = me.parent()
		if p and p.op('topnet'):
			return p
		# DAT Execute가 W2TD 등에 있으면, 형제 webrtc_video_container 찾기
		if p and p.parent():
			c = p.parent().op('webrtc_video_container')
			if c:
				return c
	except (NameError, AttributeError):
		pass
	# fallback: webrtc_audio_container와 동일 구조 (W2TD 아래)
	for proj in ('project1', 'project'):
		for path in (f'{proj}/W2TD/webrtc_video_container', f'{proj}/webrtc_video_container'):
			c = op(path)
			if c:
				return c
	root = op('/')
	if root and root.children:
		for child in root.children:
			c = child.op('W2TD/webrtc_video_container') or child.op('webrtc_video_container')
			if c:
				return c
	return op('webrtc_video_container')


def _get_container():
	"""TopNet or similar for creating Web Render TOPs (must have create())."""
	c = _w2td_video()
	if c is None:
		return None
	topnet = c.op('topnet') if c else None
	if topnet and hasattr(topnet, 'create'):
		return topnet
	if hasattr(c, 'create'):
		return c
	for child in (c.children if c else []):
		if hasattr(child, 'create'):
			return child
	return c


def _read_connected_slots(table_dat=None):
	"""sensor_table에서 연결된 slot 목록. table_dat 있으면 사용 (onTableChange에서 전달, 경로 불필요)."""
	t = table_dat
	if t is None:
		# fallback: DAT Execute 부모의 형제에서 sensor_table
		try:
			p = me.parent()
			if p and p.parent():
				t = p.parent().op('sensor_table')
		except (NameError, AttributeError):
			pass
		if t is None:
			t = op('sensor_table')
	if t is None or t.numRows < 2:
		return []
	slots = []
	for r in range(1, t.numRows):
		try:
			connected = t[r, 'connected']
			if connected in (1, '1', True, 'True', 'true'):
				slot = int(t[r, 'slot'])
				if 1 <= slot:
					slots.append(slot)
		except (ValueError, TypeError):
			pass
	return sorted(slots)


def _get_cam_base_url():
	"""cam_receiver base URL (http://ip:port or https://ip:port)."""
	base = op('/').fetch('w2td_cam_base_url', None)
	if base:
		return base
	# fallback: w2td_config or build from web server
	cfg = op('w2td_config')
	if cfg and hasattr(cfg, 'numRows') and cfg.numRows >= 2:
		for col in ('base_url', 'cam_base_url', 'url'):
			if col in [str(cfg[0, c]) for c in range(cfg.numCols)]:
				idx = [str(cfg[0, c]) for c in range(cfg.numCols)].index(col)
				val = str(cfg[1, idx]).strip()
				if val:
					return val
	# build from common storage
	port = op('/').fetch('w2td_web_port', 9980)
	import socket
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(('8.8.8.8', 80))
		ip = s.getsockname()[0]
		s.close()
	except Exception:
		ip = '127.0.0.1'
	return f'http://{ip}:{port}'


def _get_cam_port():
	"""Web server port for cam_receiver."""
	return op('/').fetch('w2td_web_port', 9980)


def _get_tls_flag():
	"""Whether to add &tls=1 to URL."""
	return bool(op('/').fetch('w2td_cam_tls', False))


def sync(table_dat=None):
	"""sensor_table과 동기화: Web Render TOP 생성/삭제, URL 설정. table_dat 있으면 사용 (경로 불필요)."""
	container = _get_container()
	if container is None:
		shown = op('/').fetch('w2td_cam_render_container_err', False)
		if not shown:
			print('[Cam Render Sync] 에러 webrtc_video_container not found - create W2TD/webrtc_video_container (Container COMP) and place DAT Execute inside it')
			op('/').store('w2td_cam_render_container_err', True)
		return

	op('/').store('w2td_cam_render_container_err', False)  # 성공 시 리셋
	slots = _read_connected_slots(table_dat)
	base_url = _get_cam_base_url()
	port = _get_cam_port()
	tls = _get_tls_flag()

	target_names = [f'web_render_top_{i}' for i in range(1, len(slots) + 1)]
	slot_list = slots  # [1, 2, 3] for 3 connected

	# 기존 Web Render TOP 조회
	existing = {}
	if container:
		for i in range(1, 32):
			name = f'web_render_top_{i}'
			top = container.op(name)
			if top:
				existing[name] = top

	# 삭제 (web_render_top만). 제거될 TOP의 slot cam_receiver 클리어 → offer pending 유도
	prev_slots = tuple(op('/').fetch('w2td_cam_render_last_slots', ()))
	for name in list(existing.keys()):
		if name not in target_names:
			try:
				idx = int(name.split('_')[-1]) - 1
				if 0 <= idx < len(prev_slots):
					op('/').store(f'w2td_cam_receiver_addr_{prev_slots[idx]}', None)
			except (ValueError, TypeError):
				pass
			try:
				existing[name].destroy()
				print(f'[Cam Render Sync] Destroyed {name}')
			except Exception as e:
				print(f'[Cam Render Sync] 에러 Destroy {name} failed: {e}')

	# 생성 및 URL 설정
	for i, name in enumerate(target_names):
		top = existing.get(name) or container.op(name)
		if top is None:
			try:
				top = container.create('webrenderTOP', name)
				print(f'[Cam Render Sync] Created {name}')
			except Exception as e:
				print(f'[Cam Render Sync] 에러 Create {name} failed: {e}')
				continue
		slot = slot_list[i] if i < len(slot_list) else (i + 1)
		url = f'{base_url}/cam_receiver.html?port={port}&slot={slot}'
		if tls:
			url += '&tls=1'
		try:
			# URL 변경 시에만 설정 — 동일 URL 반복 설정 시 ERR_ABORTED 유발
			if getattr(top.par, 'url', None) != url:
				top.par.url = url
			top.par.active = 1
			top.nodeX = 0
			top.nodeY = -i * NODE_OFFSET_Y
		except Exception as e:
			print(f'[Cam Render Sync] 에러 Set {name} url failed: {e}')
		# cam_resolution 수신 시 해당 slot의 web_render_top 찾기용
		op('/').store(f'w2td_web_render_slot_{slot}', top.path)

		# web_render_top → layout1 직접 연결
		try:
			layout1 = (container.op('layout1') if container else None) or (_w2td_video().op('layout1') if _w2td_video() else None)
			if not layout1 and _w2td_video() and _w2td_video().parent():
				layout1 = _w2td_video().parent().op('layout1')
			if layout1 and i < len(layout1.inputConnectors):
				top.outputConnectors[0].connect(layout1.inputConnectors[i])
		except Exception:
			pass

	# 삭제된 slot 매핑 정리
	for s in range(1, 21):
		if s not in slot_list:
			op('/').store(f'w2td_web_render_slot_{s}', None)
			op('/').store(f'w2td_cam_res_logged_{s}', False)

	if slots:
		prev = tuple(op('/').fetch('w2td_cam_render_last_slots', ()))
		if tuple(slots) != prev:
			print(f'[Cam Render Sync] {len(slots)} web render TOPs synced (slots {slots})')
			op('/').store('w2td_cam_render_last_slots', tuple(slots))
		# layout1 해상도: 연결된 영상 수에 맞춰 수평 배치 (540x960 each → 540*n x 960)
		try:
			layout1 = (container.op('layout1') if container else None) or (_w2td_video().op('layout1') if _w2td_video() else None)
			if not layout1 and _w2td_video() and _w2td_video().parent():
				layout1 = _w2td_video().parent().op('layout1')
			if layout1:
				n = len(slots)
				w, h = 540 * n, 960
				if hasattr(layout1.par, 'outputresolution'):
					try:
						layout1.par.outputresolution = 'custom'
					except Exception:
						pass
				if hasattr(layout1.par, 'resolutionw') and hasattr(layout1.par, 'resolutionh'):
					try:
						layout1.par.resolutionw = w
						layout1.par.resolutionh = h
					except Exception:
						pass
				if hasattr(layout1.par, 'align'):
					try:
						layout1.par.align = 'horizlr'
					except Exception:
						pass
		except Exception:
			pass
	else:
		op('/').store('w2td_cam_render_last_slots', ())


def onTableChange(dat, prevDAT, info):
	"""DAT Execute DAT의 onTableChange에서 호출. dat=sensor_table (경로 무관)."""
	sync(table_dat=dat)


def onRowChange(dat, rows):
	pass

def onColChange(dat, cols):
	pass

def onCellChange(dat, cells, prev):
	pass

def onSizeChange(dat):
	pass
