"""
sensor_table -> Web Render TOP sync
==================================
Creates web_render_top_1, web_render_top_2, ... based on connected slots.
Each TOP loads cam_receiver.html?slot=N for that slot.
Setup in TD:
  1. Create webrtc_video_container (Container COMP)
  2. Create DAT Execute DAT inside webrtc_video_container
  3. Set "DATs" to: ../sensor_table (relative path when sensor_table is one level up)
  4. Enable "Table Change"
  5. Paste this script
Relative path: ../sensor_table when DAT Execute is inside webrtc_video_container
"""
NODE_OFFSET_Y = 100


def _w2td_video():
	"""webrtc_video_container. Uses me.parent() when DAT Execute is inside it."""
	try:
		p = me.parent()
		if p and p.op('topnet'):
			return p
		# When DAT Execute is under W2TD etc., find sibling webrtc_video_container
		if p and p.parent():
			c = p.parent().op('webrtc_video_container')
			if c:
				return c
	except (NameError, AttributeError):
		pass
	# fallback: same structure as webrtc_audio_container (under W2TD)
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
	"""List connected slots from sensor_table. Uses table_dat if provided (passed from onTableChange, path not needed)."""
	t = table_dat
	if t is None:
		# fallback: sensor_table from DAT Execute parent's sibling
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


def _read_config():
	"""Read w2td_config Table DAT."""
	cfg_op = op('w2td_config') or op('project1/W2TD/w2td_config') or op('project/W2TD/w2td_config')
	if cfg_op is None or not hasattr(cfg_op, 'numRows') or cfg_op.numRows < 2:
		return {}
	out = {}
	for r in range(1, cfg_op.numRows):
		try:
			out[str(cfg_op[r, 0])] = str(cfg_op[r, 1])
		except Exception:
			pass
	return out


def _cfg_str(cfg, *keys, default=''):
	for k in keys:
		if k in cfg and cfg.get(k) is not None:
			return str(cfg[k]).strip()
	return default


def _get_cam_resolution_dims(cfg=None):
	"""Read Resolution, Screenmode from w2td_config and return (w, h). Synced with webrtc.js and callbacks.py."""
	if cfg is None:
		cfg = _read_config()
	res = _cfg_str(cfg, 'Resolution', 'resolution', default='Non-Commercial')
	mode = (_cfg_str(cfg, 'Screenmode', 'screenmode', default='Portrait') or '').strip().lower()
	# Synced with webrtc.js: portrait=tall(vertical), landscape=wide(horizontal) — natural mapping
	presets = {
		'Non-Commercial': {'portrait': (540, 960), 'landscape': (960, 540)},
		'FHD': {'portrait': (1080, 1920), 'landscape': (1920, 1080)},
		'4K': {'portrait': (2160, 3840), 'landscape': (3840, 2160)},
	}
	p = presets.get(res, presets['Non-Commercial'])
	# Swap: config Landscape → Portrait display (540x960), config Portrait → Landscape display (960x540)
	w, h = (p['portrait'] if mode == 'landscape' else p['landscape'])
	return (int(w), int(h))


def sync(table_dat=None):
	"""Sync with sensor_table: create/remove Web Render TOPs, set URLs. Uses table_dat if provided (path not needed)."""
	container = _get_container()
	if container is None:
		shown = op('/').fetch('w2td_cam_render_container_err', False)
		if not shown:
			print('[Cam Render Sync] Error webrtc_video_container not found - create W2TD/webrtc_video_container (Container COMP) and place DAT Execute inside it')
			op('/').store('w2td_cam_render_container_err', True)
		return

	op('/').store('w2td_cam_render_container_err', False)  # Reset on success
	slots = _read_connected_slots(table_dat)
	base_url = _get_cam_base_url()
	port = _get_cam_port()
	tls = _get_tls_flag()

	target_names = [f'web_render_top_{i}' for i in range(1, len(slots) + 1)]
	slot_list = slots  # [1, 2, 3] for 3 connected

	# Query existing Web Render TOPs
	existing = {}
	if container:
		for i in range(1, 32):
			name = f'web_render_top_{i}'
			top = container.op(name)
			if top:
				existing[name] = top

	# Remove (web_render_top only). Clear cam_receiver for removed slot → trigger offer pending
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
				print(f'[Cam Render Sync] Error Destroy {name} failed: {e}')

	# Create and set URL
	cfg = _read_config()
	for i, name in enumerate(target_names):
		top = existing.get(name) or container.op(name)
		if top is None:
			try:
				top = container.create('webrenderTOP', name)
				print(f'[Cam Render Sync] Created {name}')
			except Exception as e:
				print(f'[Cam Render Sync] Error Create {name} failed: {e}')
				continue
		slot = slot_list[i] if i < len(slot_list) else (i + 1)
		cw, ch = _get_cam_resolution_dims(cfg)
		mode = (_cfg_str(cfg, 'Screenmode', 'screenmode', default='Portrait') or 'Portrait').strip().lower()
		url = f'{base_url}/cam_receiver.html?port={port}&slot={slot}&mode={mode}'
		if tls:
			url += '&tls=1'
		try:
			# Set TOP resolution from config BEFORE page loads — viewport must match expected mode
			top.par.outputresolution = 'custom'
			top.par.resolutionw = cw
			top.par.resolutionh = ch
			# Set only when URL changes — repeated same URL can cause ERR_ABORTED
			if getattr(top.par, 'url', None) != url:
				top.par.url = url
			top.par.active = 1
			top.nodeX = 0
			top.nodeY = -i * NODE_OFFSET_Y
		except Exception as e:
			print(f'[Cam Render Sync] Error Set {name} url failed: {e}')
		# Lookup web_render_top for slot when cam_resolution is received
		op('/').store(f'w2td_web_render_slot_{slot}', top.path)

		# Direct connect web_render_top → layout1
		try:
			layout1 = (container.op('layout1') if container else None) or (_w2td_video().op('layout1') if _w2td_video() else None)
			if not layout1 and _w2td_video() and _w2td_video().parent():
				layout1 = _w2td_video().parent().op('layout1')
			if layout1 and i < len(layout1.inputConnectors):
				top.outputConnectors[0].connect(layout1.inputConnectors[i])
		except Exception:
			pass

	# Clear mapping for removed slots
	for s in range(1, 21):
		if s not in slot_list:
			op('/').store(f'w2td_web_render_slot_{s}', None)
			op('/').store(f'w2td_cam_res_logged_{s}', False)

	if slots:
		prev = tuple(op('/').fetch('w2td_cam_render_last_slots', ()))
		if tuple(slots) != prev:
			print(f'[Cam Render Sync] {len(slots)} web render TOPs synced (slots {slots})')
			op('/').store('w2td_cam_render_last_slots', tuple(slots))
		# layout1 resolution: horizontal layout based on w2td_config Resolution/Screenmode
		try:
			layout1 = (container.op('layout1') if container else None) or (_w2td_video().op('layout1') if _w2td_video() else None)
			if not layout1 and _w2td_video() and _w2td_video().parent():
				layout1 = _w2td_video().parent().op('layout1')
			if layout1:
				n = len(slots)
				cw, ch = _get_cam_resolution_dims()
				w, h = cw * n, ch
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
	"""Called from DAT Execute DAT's onTableChange. dat=sensor_table (path not needed)."""
	sync(table_dat=dat)


def onRowChange(dat, rows):
	pass

def onColChange(dat, cols):
	pass

def onCellChange(dat, cells, prev):
	pass

def onSizeChange(dat):
	pass
