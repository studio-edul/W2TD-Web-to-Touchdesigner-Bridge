"""
W2TD webrtc_table -> Audio Stream In CHOP sync
==============================================
Called from DAT Execute DAT on webrtc_table change.
Nodes under W2TD/webrtc_audio_container (relative path).
"""

W2TD_BASE = 'W2TD'
W2TD_AUDIO = f'{W2TD_BASE}/webrtc_audio_container'


# ── W2TD Logger ──────────────────────────────────────────────────
_LOG_MAX = 200

def _get_logger():
    try:
        p = me.parent()
        while p:
            if p.name in ('W2TD', 'W2TD_Pro'):
                return p.parent().op('logger')
            p = p.parent()
    except Exception:
        pass
    return None

def _log_error(msg):
    import datetime
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line)
    dat = _get_logger()
    if dat is None:
        return
    existing = dat.text.splitlines() if dat.text.strip() else []
    existing.insert(0, line)
    if len(existing) > _LOG_MAX:
        existing = existing[:_LOG_MAX]
    dat.text = '\n'.join(existing)
# ─────────────────────────────────────────────────────────────────

def _w2td_audio():
	"""Always return webrtc_audio_container."""
	try:
		p = parent(1)
		if p:
			if p.name == 'webrtc_audio_container':
				return p
			if p.name == 'W2TD':
				c = p.op('webrtc_audio_container')
				if c:
					return c
	except NameError:
		pass
	for proj in ('project1', 'project'):
		c = op(f'{proj}/{W2TD_AUDIO}')
		if c:
			return c
	root = op('/')
	if root and root.children:
		c = root.children[0].op(W2TD_AUDIO)
		if c:
			return c
	return op(W2TD_AUDIO)


def _get_container():
	"""ChopNetwork for creating Audio CHOPs (must have create()). Excludes outCHOP."""
	c = _w2td_audio()
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
	c = _w2td_audio()
	if c:
		m = c.op('webrtc_audio_merge')
		if m:
			return m
	return op('webrtc_audio_merge')


def _get_rename():
	c = _w2td_audio()
	if c:
		for name in ('rename1', 'rename1dldi'):
			r = c.op(name)
			if r:
				return r
	return op('rename1') or op('rename1dldi')


def _get_webrtc():
	c = _w2td_audio()
	if c:
		w = c.op('webrtc_dat')
		if w:
			return w
	return op('webrtc_dat')


def _get_table():
	c = _w2td_audio()
	if c:
		t = c.op('webrtc_table')
		if t:
			return t
	return op('webrtc_table')


def _sanitize_channel_name(s):
	"""Normalize channel names for CHOP usage - remove spaces and special chars."""
	if not s:
		return ''
	return ''.join(c if c.isalnum() or c in '_-' else '_' for c in str(s).strip())[:64] or 'ch'


def _read_rows():
	"""List (slot, conn_id, channel_name) from webrtc_table. Skip row 0 header, state=connected only, 1 per slot."""
	t = _get_table()
	if t is None or t.numRows < 2:
		return []
	# print(f'[W2TD WebRTC Sync] webrtc_table numRows={t.numRows}')
	seen = {}
	for r in range(1, t.numRows):
		try:
			conn_id = str(t[r, 'conn_id']).strip()
			if not conn_id or conn_id.lower() == 'conn_id':
				continue
			if '-' not in conn_id or len(conn_id) < 10:
				continue
			state = str(t[r, 'state']).strip().lower()
			# Include connecting (state update may be delayed, prevents chop from being removed)
			if state not in ('connected', 'connecting'):
				continue
			slot = int(t[r, 'slot'])
			if slot < 1:
				continue
			try:
				name = str(t[r, 'name']).strip()
			except Exception:
				name = ''
			channel_name = _sanitize_channel_name(name) or f'slot{slot}'
			seen[slot] = (slot, conn_id, channel_name)
		except (ValueError, TypeError):
			pass
	rows = sorted(seen.values(), key=lambda x: x[0])
	return rows


def _set_audio_chop_params(chop, conn_id):
	"""Set WebRTC Connection/Track for Audio Stream In CHOP."""
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
				_log_error(f'[W2TD WebRTC Sync] Error Set {par_name} failed: {e}')
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
	"""Sync with webrtc_table: create/remove Audio Stream In CHOPs, update Merge inputs."""
	container = _get_container()
	merge_chop = _get_merge()
	if container is None:
		_log_error('[W2TD WebRTC Sync] Error webrtc_audio_container not found - create under W2TD')
		return
	if merge_chop is None:
		_log_error('[W2TD WebRTC Sync] Error webrtc_audio_merge not found - create Merge CHOP under W2TD/webrtc_audio_container')
		return

	rows = _read_rows()
	target_names = [f'webrtc_audio_{i}' for i in range(1, len(rows) + 1)]
	slot_conn = {r[0]: r[1] for r in rows}

	# Query existing Audio Stream In CHOPs (search container, chopnet, w2td_audio)
	existing = {}
	for chop in (container.ops('webrtc_audio_*') if hasattr(container, 'ops') else []):
		if chop.name.startswith('webrtc_audio_') and chop.name[14:].isdigit():
			existing[chop.name] = chop
	if not existing and hasattr(container, 'children'):
		for child in container.children:
			if child.name.startswith('webrtc_audio_') and child.name[14:].isdigit():
				existing[child.name] = child
	w2td_audio = _w2td_audio()
	if not existing and w2td_audio:
		for chop in w2td_audio.ops('chopnet/webrtc_audio_*'):
			if chop.name.startswith('webrtc_audio_') and chop.name[14:].isdigit():
				existing[chop.name] = chop
	if not existing and w2td_audio:
		for i in range(1, 32):
			name = f'webrtc_audio_{i}'
			chop = w2td_audio.op(f'chopnet/{name}') or w2td_audio.op(name)
			if chop:
				existing[name] = chop

	# Remove: delete if not in target and name matches webrtc_audio_N
	to_delete = [n for n in existing if n not in target_names]
	for name in to_delete:
		try:
			existing[name].destroy()
			# print(f'[W2TD WebRTC Sync] Destroyed {name}')
		except Exception as e:
			_log_error(f'[W2TD WebRTC Sync] Error Destroy {name} failed: {e}')

	# Create: only when node doesn't exist (check via container.op), same x, y increases upward (-)
	NODE_OFFSET_Y = 100
	for i, name in enumerate(target_names):
		chop = existing.get(name) or container.op(name)
		if chop is None:
			try:
				chop = container.create('audiostreaminCHOP', name)
				# print(f'[W2TD WebRTC Sync] Created {name}')
			except Exception as e:
				_log_error(f'[W2TD WebRTC Sync] Error Create {name} failed: {e}')
				continue
		try:
			chop.nodeX = 0
			chop.nodeY = -i * NODE_OFFSET_Y
		except Exception:
			pass
		if i < len(rows):
			_, conn_id, _ = rows[i]
			_set_audio_chop_params(chop, conn_id)

	# Connect Merge CHOP inputs (using setInputs)
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

	# Rename CHOP: set renameto param to names (device names) per order
	rename_chop = _get_rename()
	if rename_chop:
		try:
			rename_chop.setInputs([merge_chop])
		except Exception:
			pass
		if rows:
			# renameto: space-separated channel names (using device name)
			renameto_val = ' '.join(channel_name for _, _, channel_name in rows)
			for par_name in ('renameto', 'Renameto', 'commonrenameto'):
				if hasattr(rename_chop.par, par_name):
					try:
						setattr(rename_chop.par, par_name, renameto_val)
						break
					except Exception:
						pass
			# renamefrom: match all channels
			for par_name in ('renamefrom', 'Renamefrom', 'commonrenamefrom'):
				if hasattr(rename_chop.par, par_name):
					try:
						setattr(rename_chop.par, par_name, '*')
						break
					except Exception:
						pass

	if rows:
		# print(f'[W2TD WebRTC Sync] {len(rows)} audio chops synced')
		pass
	else:
		# print('[W2TD WebRTC Sync] No connections - all audio chops removed')
		pass


def onTableChange(dat, prevDAT, info):
	"""Called from DAT Execute DAT's onTableChange."""
	sync()
