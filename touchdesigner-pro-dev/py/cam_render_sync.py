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
"""
NODE_OFFSET_Y = 100
# Square side per Resolution config: Non-Commercial(960), FHD(1920)
_CAM_TOP_DIM_MAP = {'non-commercial': 960, 'fhd': 1920}


def _find_config():
	"""Find w2td_config Table DAT using video container's W2TD parent + fallbacks."""
	# Primary: navigate via webrtc_video_container -> W2TD parent (most reliable)
	try:
		vid = _w2td_video()
		if vid and vid.parent():
			cfg = vid.parent().op('w2td_config')
			if cfg:
				return cfg
	except Exception:
		pass
	# Secondary: walk up from me (up to 4 levels)
	try:
		p = me.parent()
		for _ in range(4):
			if p is None:
				break
			cfg = p.op('w2td_config')
			if cfg:
				return cfg
			p = p.parent()
	except (NameError, AttributeError):
		pass
	# Absolute path fallbacks
	for path in ('project1/W2TD/w2td_config', 'project/W2TD/w2td_config',
	             'project1/w2td_config', 'project/w2td_config'):
		cfg = op(path)
		if cfg:
			return cfg
	return op('w2td_config')


def _read_config_values():
	"""Return (res_key, dim, screenmode) from w2td_config using robust lookup."""
	res_key = 'non-commercial'
	screenmode = 'portrait'
	try:
		cfg = _find_config()
		if cfg and cfg.numRows >= 2:
			for r in range(1, cfg.numRows):
				try:
					k = str(cfg[r, 0]).strip().lower()
					v = str(cfg[r, 1]).strip()
					if k == 'resolution':
						res_key = v.lower()
					elif k == 'screenmode':
						screenmode = v.lower()
				except Exception:
					pass
	except Exception:
		pass
	dim = _CAM_TOP_DIM_MAP.get(res_key, 960)
	return res_key, dim, screenmode


def _w2td_video():
	"""Find webrtc_video_container. Uses me.parent() if DAT Execute is inside it."""
	try:
		p = me.parent()
		if p and p.op('topnet'):
			return p
		# If DAT Execute is inside W2TD, look for sibling webrtc_video_container
		if p and p.parent():
			c = p.parent().op('webrtc_video_container')
			if c:
				return c
	except (NameError, AttributeError):
		pass
	# Fallback: same structure as webrtc_audio_container (under W2TD)
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
	"""Return the container used for creating TOPs (must support create())."""
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
	"""Return sorted list of connected slot numbers from sensor_table."""
	t = table_dat
	if t is None:
		# Fallback: look for sensor_table as sibling of DAT Execute's parent
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
	"""Return cam_receiver base URL (http://ip:port or https://ip:port)."""
	base = op('/').fetch('w2td_cam_base_url', None)
	if base:
		return base
	# Fallback: check w2td_config or build from web server info
	cfg = op('w2td_config')
	if cfg and hasattr(cfg, 'numRows') and cfg.numRows >= 2:
		for col in ('base_url', 'cam_base_url', 'url'):
			if col in [str(cfg[0, c]) for c in range(cfg.numCols)]:
				idx = [str(cfg[0, c]) for c in range(cfg.numCols)].index(col)
				val = str(cfg[1, idx]).strip()
				if val:
					return val
	# Build from stored port + local IP
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
	"""Return web server port for cam_receiver."""
	return op('/').fetch('w2td_web_port', 9980)


def _get_tls_flag():
	"""Return True if &tls=1 should be appended to the cam_receiver URL."""
	return bool(op('/').fetch('w2td_cam_tls', False))


def _find_layout1(container):
	"""Find layout1 TOP in container or its parent."""
	layout1 = container.op('layout1') if container else None
	if not layout1:
		vid = _w2td_video()
		if vid:
			layout1 = vid.op('layout1')
		if not layout1 and vid and vid.parent():
			layout1 = vid.parent().op('layout1')
	return layout1


def sync(table_dat=None):
	"""Sync Web Render TOPs with sensor_table. Creates/destroys nodes and sets URLs."""
	container = _get_container()
	if container is None:
		shown = op('/').fetch('w2td_cam_render_container_err', False)
		if not shown:
			print('[Cam Render Sync] Error: webrtc_video_container not found - create W2TD/webrtc_video_container (Container COMP) and place DAT Execute inside it')
			op('/').store('w2td_cam_render_container_err', True)
		return

	op('/').store('w2td_cam_render_container_err', False)
	res_key, sq, screenmode = _read_config_values()
	rotate_deg = -90 if screenmode == 'landscape' else 0
	slots = _read_connected_slots(table_dat)
	base_url = _get_cam_base_url()
	port = _get_cam_port()
	tls = _get_tls_flag()

	target_names = [f'web_render_top_{i}' for i in range(1, len(slots) + 1)]
	slot_list = slots

	# Collect existing web_render_top nodes
	existing = {}
	if container:
		for i in range(1, 32):
			name = f'web_render_top_{i}'
			top = container.op(name)
			if top:
				existing[name] = top

	# Destroy removed nodes (web_render_top + transform_top + crop_top)
	prev_slots = tuple(op('/').fetch('w2td_cam_render_last_slots', ()))
	for name in list(existing.keys()):
		if name not in target_names:
			idx_str = name.split('_')[-1]
			try:
				idx = int(idx_str) - 1
				if 0 <= idx < len(prev_slots):
					op('/').store(f'w2td_cam_receiver_addr_{prev_slots[idx]}', None)
			except (ValueError, TypeError):
				pass
			for companion in (f'transform_top_{idx_str}', f'crop_top_{idx_str}', f'touch_out_top_{idx_str}'):
				c = container.op(companion)
				if c:
					try:
						c.destroy()
					except Exception:
						pass
			try:
				existing[name].destroy()
				print(f'[Cam Render Sync] Destroyed {name}')
			except Exception as e:
				print(f'[Cam Render Sync] Error destroying {name}: {e}')

	# Create/update nodes: web_render_top -> transform_top -> crop_top -> layout1
	for i, name in enumerate(target_names):
		idx = i + 1

		# --- web_render_top ---
		top = existing.get(name) or container.op(name)
		if top is None:
			try:
				top = container.create('webrenderTOP', name)
				print(f'[Cam Render Sync] Created {name}')
			except Exception as e:
				print(f'[Cam Render Sync] Error creating {name}: {e}')
				continue
		slot = slot_list[i] if i < len(slot_list) else idx
		url = f'{base_url}/cam_receiver.html?port={port}&slot={slot}&res={res_key}'
		if tls:
			url += '&tls=1'
		try:
			# Only set URL when changed to avoid ERR_ABORTED
			if getattr(top.par, 'url', None) != url:
				top.par.url = url
			top.par.active = 1
			if hasattr(top.par, 'outputresolution'):
				try:
					top.par.outputresolution = 'custom'
				except Exception:
					pass
			if hasattr(top.par, 'resolutionw') and hasattr(top.par, 'resolutionh'):
				try:
					top.par.resolutionw = sq
					top.par.resolutionh = sq
				except Exception:
					pass
			top.nodeX = 0
			top.nodeY = -i * NODE_OFFSET_Y
		except Exception as e:
			print(f'[Cam Render Sync] Error setting {name} params: {e}')
		op('/').store(f'w2td_web_render_slot_{slot}', top.path)

		# --- transform_top ---
		t_name = f'transform_top_{idx}'
		t_top = container.op(t_name)
		if t_top is None:
			try:
				t_top = container.create('transformTOP', t_name)
				print(f'[Cam Render Sync] Created {t_name}')
			except Exception as e:
				print(f'[Cam Render Sync] Error creating {t_name}: {e}')
				t_top = None
		if t_top:
			try:
				t_top.par.rotate = rotate_deg
			except Exception as e:
				print(f'[Cam Render Sync] Error setting {t_name} rotate: {e}')
			try:
				t_top.nodeX = top.nodeX + 150
				t_top.nodeY = -i * NODE_OFFSET_Y
			except Exception:
				pass
			try:
				top.outputConnectors[0].connect(t_top.inputConnectors[0])
			except Exception as e:
				print(f'[Cam Render Sync] Error connecting {name} -> {t_name}: {e}')

		# --- crop_top ---
		c_name = f'crop_top_{idx}'
		c_top = container.op(c_name)
		if c_top is None:
			try:
				c_top = container.create('cropTOP', c_name)
				print(f'[Cam Render Sync] Created {c_name}')
			except Exception as e:
				print(f'[Cam Render Sync] Error creating {c_name}: {e}')
				c_top = None
		if c_top:
			try:
				c_top.nodeX = top.nodeX + 300
				c_top.nodeY = -i * NODE_OFFSET_Y
			except Exception:
				pass
			# Crop black bars in pixels (unit=0 -> pixel mode)
			crop_px = sq * 7 // 32
			try:
				c_top.par.cropleftunit   = 0
				c_top.par.croprightunit  = 0
				c_top.par.croptopunit    = 0
				c_top.par.cropbottomunit = 0
			except Exception as e:
				print(f'[Cam Render Sync] Error setting {c_name} crop units: {e}')
			try:
				if screenmode == 'landscape':
					# After -90 transform: black bars appear on top/bottom
					c_top.par.cropleft   = 0
					c_top.par.cropright  = sq
					c_top.par.croptop    = sq - crop_px
					c_top.par.cropbottom = crop_px
				else:
					# Portrait: black bars on left/right from 9:16 content in square
					c_top.par.cropleft   = crop_px
					c_top.par.cropright  = sq - crop_px
					c_top.par.croptop    = sq
					c_top.par.cropbottom = 0
			except Exception as e:
				print(f'[Cam Render Sync] Error setting {c_name} crop values: {e}')
			try:
				if t_top:
					t_top.outputConnectors[0].connect(c_top.inputConnectors[0])
			except Exception as e:
				print(f'[Cam Render Sync] Error connecting {t_name} -> {c_name}: {e}')

		# --- touch_out_top ---
		o_name = f'touch_out_top_{idx}'
		o_top = container.op(o_name)
		if o_top is None:
			try:
				o_top = container.create('touchoutTOP', o_name)
				print(f'[Cam Render Sync] Created {o_name}')
			except Exception as e:
				print(f'[Cam Render Sync] Error creating {o_name}: {e}')
				o_top = None
		if o_top:
			try:
				o_top.nodeX = top.nodeX + 450
				o_top.nodeY = -i * NODE_OFFSET_Y
			except Exception:
				pass
			try:
				o_top.par.port = 9000 + idx
			except Exception as e:
				print(f'[Cam Render Sync] Error setting {o_name} port: {e}')
			try:
				if c_top:
					c_top.outputConnectors[0].connect(o_top.inputConnectors[0])
			except Exception as e:
				print(f'[Cam Render Sync] Error connecting {c_name} -> {o_name}: {e}')

		# Connect crop_top -> layout1 (touch_out_top is a side output only, not in the layout chain)
		layout_src = c_top or t_top or top
		try:
			layout1 = _find_layout1(container)
			if layout1 and i < len(layout1.inputConnectors):
				layout_src.outputConnectors[0].connect(layout1.inputConnectors[i])
		except Exception:
			pass

	# Clean up slot mappings for disconnected slots
	for s in range(1, 21):
		if s not in slot_list:
			op('/').store(f'w2td_web_render_slot_{s}', None)
			op('/').store(f'w2td_cam_res_logged_{s}', False)

	if slots:
		prev = tuple(op('/').fetch('w2td_cam_render_last_slots', ()))
		if tuple(slots) != prev:
			print(f'[Cam Render Sync] {len(slots)} web render TOPs synced (slots {slots})')
			op('/').store('w2td_cam_render_last_slots', tuple(slots))
		# Set layout1 resolution based on cropped output size
		try:
			layout1 = _find_layout1(container)
			if layout1:
				n = len(slots)
				crop_side = sq * 7 // 32
				short = sq - 2 * crop_side  # = sq * 9 // 16
				if screenmode == 'landscape':
					w, h = sq * n, short   # 16:9 each slot
				else:
					w, h = short * n, sq   # 9:16 each slot
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
	"""Called by DAT Execute when sensor_table changes."""
	sync(table_dat=dat)


def onRowChange(dat, rows):
	pass

def onColChange(dat, cols):
	pass

def onCellChange(dat, cells, prev):
	pass

def onSizeChange(dat):
	pass
