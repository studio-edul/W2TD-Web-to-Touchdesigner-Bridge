"""
WOB webrtc_table -> Audio Stream In CHOP sync
============================================
Called from DAT Execute DAT on webrtc_table change.
Nodes under WOB/webrtc_audio_container (relative path).
"""

WOB_BASE = 'WOB'
WOB_AUDIO = f'{WOB_BASE}/webrtc_audio_container'


def _wob_audio():
	"""Always return webrtc_audio_container (not WOB)."""
	try:
		p = parent(1)
		if p:
			if p.name == 'webrtc_audio_container':
				return p
			if p.name == 'WOB':
				c = p.op('webrtc_audio_container')
				if c:
					return c
	except NameError:
		pass
	for proj in ('project1', 'project'):
		c = op(f'{proj}/{WOB_AUDIO}')
		if c:
			return c
	root = op('/')
	if root and root.children:
		c = root.children[0].op(WOB_AUDIO)
		if c:
			return c
	return op(WOB_AUDIO)


def _get_container():
	"""ChopNetwork for creating Audio CHOPs (must have create()). Excludes outCHOP."""
	c = _wob_audio()
	if c is None:
		return None
	chopnet = c.op('chopnet')
	if chopnet and hasattr(chopnet, 'create'):
		return chopnet
	for child in c.children:
		if hasattr(child, 'create'):
			return child
	return c


def _get_merge():
	c = _wob_audio()
	if c:
		m = c.op('webrtc_audio_merge')
		if m:
			return m
	return op('webrtc_audio_merge')


def _get_rename():
	c = _wob_audio()
	if c:
		for name in ('rename1', 'rename1dldi'):
			r = c.op(name)
			if r:
				return r
	return op('rename1') or op('rename1dldi')


def _get_webrtc():
	c = _wob_audio()
	if c:
		w = c.op('webrtc_dat')
		if w:
			return w
	return op('webrtc_dat')


def _get_table():
	c = _wob_audio()
	if c:
		t = c.op('webrtc_table')
		if t:
			return t
	return op('webrtc_table')


def _read_rows():
	"""webrtc_table에서 (slot, conn_id) 목록. Row 0=헤더 제외, state=connected만, slot당 1개."""
	t = _get_table()
	if t is None or t.numRows < 2:
		return []
	print(f'[WOB WebRTC Sync] webrtc_table numRows={t.numRows}')
	seen = {}
	for r in range(1, t.numRows):
		try:
			conn_id = str(t[r, 'conn_id']).strip()
			if not conn_id or conn_id.lower() == 'conn_id':
				continue
			if '-' not in conn_id or len(conn_id) < 10:
				continue
			state = str(t[r, 'state']).strip().lower()
			if state != 'connected':
				continue
			slot = int(t[r, 'slot'])
			if slot < 1:
				continue
			seen[slot] = (slot, conn_id)
		except (ValueError, TypeError):
			pass
	rows = sorted(seen.values(), key=lambda x: x[0])
	return rows


def _set_audio_chop_params(chop, conn_id):
	"""Audio Stream In CHOP의 WebRTC Connection/Track 설정."""
	webrtc = _get_webrtc()
	if webrtc is None:
		return False
	# Source Type = WebRTC
	for par_name in ('srctype', 'Srctype', 'sourcetype'):
		if hasattr(chop.par, par_name):
			try:
				setattr(chop.par, par_name, 'webrtc')
				break
			except Exception:
				pass
	# WebRTC DAT
	for par_name in ('webrtc', 'Webrtc'):
		if hasattr(chop.par, par_name):
			try:
				setattr(chop.par, par_name, webrtc)
				break
			except Exception:
				pass
	# WebRTC Connection (conn_id)
	for par_name in ('webrtcconnection', 'Webrtcconnection', 'connection', 'Connection'):
		if hasattr(chop.par, par_name):
			try:
				setattr(chop.par, par_name, conn_id)
				break
			except Exception as e:
				print(f'[WOB WebRTC Sync] Set {par_name} failed: {e}')
	# WebRTC Track (mono: select first/only track)
	for par_name in ('webrtctrack', 'Webrtctrack', 'track', 'Track'):
		if hasattr(chop.par, par_name):
			try:
				p = getattr(chop.par, par_name)
				if hasattr(p, 'menuNames') and p.menuNames:
					setattr(chop.par, par_name, p.menuNames[0])
				else:
					setattr(chop.par, par_name, 0)
				break
			except Exception:
				pass
	# Play = 1
	for par_name in ('play', 'Play'):
		if hasattr(chop.par, par_name):
			try:
				setattr(chop.par, par_name, 1)
			except Exception:
				pass
	return False


def sync():
	"""webrtc_table과 동기화: Audio Stream In CHOP 생성/삭제, Merge 입력 갱신."""
	container = _get_container()
	merge_chop = _get_merge()
	if container is None:
		print('[WOB WebRTC Sync] webrtc_audio_container not found - create under WOB')
		return
	if merge_chop is None:
		print('[WOB WebRTC Sync] webrtc_audio_merge not found - create Merge CHOP under WOB/webrtc_audio_container')
		return

	rows = _read_rows()
	target_names = [f'webrtc_audio_{i}' for i in range(1, len(rows) + 1)]
	slot_conn = {r[0]: r[1] for r in rows}

	# 기존 Audio Stream In CHOP 조회 (container, chopnet, wob_audio 순으로 검색)
	existing = {}
	for chop in (container.ops('webrtc_audio_*') if hasattr(container, 'ops') else []):
		if chop.name.startswith('webrtc_audio_') and chop.name[14:].isdigit():
			existing[chop.name] = chop
	if not existing and hasattr(container, 'children'):
		for child in container.children:
			if child.name.startswith('webrtc_audio_') and child.name[14:].isdigit():
				existing[child.name] = child
	wob_audio = _wob_audio()
	if not existing and wob_audio:
		for chop in wob_audio.ops('chopnet/webrtc_audio_*'):
			if chop.name.startswith('webrtc_audio_') and chop.name[14:].isdigit():
				existing[chop.name] = chop
	if not existing and wob_audio:
		for i in range(1, 32):
			name = f'webrtc_audio_{i}'
			chop = wob_audio.op(f'chopnet/{name}') or wob_audio.op(name)
			if chop:
				existing[name] = chop

	# 삭제: target에 없고 webrtc_audio_N 형태면 삭제
	to_delete = [n for n in existing if n not in target_names]
	for name in to_delete:
		try:
			existing[name].destroy()
			print(f'[WOB WebRTC Sync] Destroyed {name}')
		except Exception as e:
			print(f'[WOB WebRTC Sync] Destroy {name} failed: {e}')

	# 생성: 노드 없을 때만 생성 (container.op으로 존재 확인), x 동일, y는 숫자 커질수록 아래로
	NODE_OFFSET_Y = 150
	for i, name in enumerate(target_names):
		chop = existing.get(name) or container.op(name)
		if chop is None:
			try:
				chop = container.create('audiostreaminCHOP', name)
				print(f'[WOB WebRTC Sync] Created {name}')
			except Exception as e:
				print(f'[WOB WebRTC Sync] Create {name} failed: {e}')
				continue
		try:
			chop.nodeX = 0
			chop.nodeY = i * NODE_OFFSET_Y
		except Exception:
			pass
		if i < len(rows):
			_, conn_id = rows[i]
			_set_audio_chop_params(chop, conn_id)

	# Merge CHOP 입력 연결 (setInputs 사용)
	chops_to_merge = []
	for name in target_names:
		chop = container.op(name)
		if chop:
			chops_to_merge.append(chop)
	try:
		merge_chop.setInputs(chops_to_merge)
	except Exception:
		for i, chop in enumerate(chops_to_merge):
			for par_name in (f'input{i}', f'chop{i}'):
				if hasattr(merge_chop.par, par_name):
					try:
						setattr(merge_chop.par, par_name, chop)
						break
					except Exception:
						pass

	# Rename CHOP: renameto 파라미터에 각 순서별 conn_id 설정
	rename_chop = _get_rename()
	if rename_chop:
		try:
			rename_chop.setInputs([merge_chop])
		except Exception:
			pass
		if rows:
			# renameto: 공백으로 구분된 conn_id 목록 (순서대로 채널 이름)
			renameto_val = ' '.join(conn_id for _, conn_id in rows)
			for par_name in ('renameto', 'Renameto', 'commonrenameto'):
				if hasattr(rename_chop.par, par_name):
					try:
						setattr(rename_chop.par, par_name, renameto_val)
						break
					except Exception:
						pass
			# renamefrom: 모든 채널 매칭
			for par_name in ('renamefrom', 'Renamefrom', 'commonrenamefrom'):
				if hasattr(rename_chop.par, par_name):
					try:
						setattr(rename_chop.par, par_name, '*')
						break
					except Exception:
						pass

	if rows:
		print(f'[WOB WebRTC Sync] {len(rows)} audio chops synced')
	else:
		print('[WOB WebRTC Sync] No connections - all audio chops removed')


def onTableChange(dat, prevDAT, info):
	"""DAT Execute DAT의 onTableChange에서 호출."""
	sync()
