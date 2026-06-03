# DAT Execute DAT - watches w2td_config Table DAT
# Setup in TD:
#   1. Create a DAT Execute DAT
#   2. Set "DATs" parameter to: w2td_config
#   3. Enable "Table Change" checkbox
#   4. Paste this script as its content (or point it to this file)
#
# Automatically broadcasts config changes to all connected clients.
# Uses debouncing to prevent excessive broadcasts during rapid edits.
# Broadcast logic is self-contained (no web_server_dat.module access) to avoid module compilation errors.

import json

W2TD_BASE = 'W2TD_Pro'


def _w2td_base():
	try:
		p = parent(1)
		if p:
			return p
	except NameError:
		pass
	for p in ('project1', 'project'):
		w = op(f'{p}/{W2TD_BASE}')
		if w:
			return w
	root = op('/')
	if root and root.children:
		w = root.children[0].op(W2TD_BASE)
		if w:
			return w
	return op(W2TD_BASE) or op('W2TD')


def _op(path_suffix, fallback_name=None):
	base = _w2td_base()
	if base:
		o = base.op(path_suffix)
		if o is not None:
			return o
	return op(fallback_name or path_suffix.split('/')[-1])

# Debouncing: wait 300ms after last change before broadcasting
_debounce_timer = None
DEBOUNCE_DELAY = 0.3  # seconds


def _read_config():
	"""Read settings from w2td_config Table DAT (name | value)."""
	cfg = _op('w2td_config')
	if cfg is None:
		return {}
	out = {}
	for r in range(1, cfg.numRows):
		try:
			out[str(cfg[r, 0])] = str(cfg[r, 1])
		except Exception:
			pass
	return out


def _cfg_val(cfg, *keys, default=0):
	"""Try keys in order; normalize to int."""
	for k in keys:
		if k in cfg:
			try:
				return int(float(cfg[k]))
			except (ValueError, TypeError):
				return default
	return default


def _build_config_msg(cfg):
	"""Build config JSON dict matching w2td_config key names."""
	out = {
		'type': 'config',
		'sample_rate': _cfg_val(cfg, 'Samplerate', default=30),
		'wake_lock': _cfg_val(cfg, 'Wakelock', default=1),
		'haptic': _cfg_val(cfg, 'Haptic', default=1),
		'sensor_motion': _cfg_val(cfg, 'Motion', default=1),
		'sensor_orientation': _cfg_val(cfg, 'Orientation', default=1),
		'sensor_geolocation': _cfg_val(cfg, 'Geolocation', default=1),
		'sensor_touch': _cfg_val(cfg, 'Touch', default=1),
		'dev_mode': _cfg_val(cfg, 'Devmode', default=1),
		'sensor_rear_camera': _cfg_val(cfg, 'Rearcamera', default=0),
		'sensor_front_camera': _cfg_val(cfg, 'Frontcamera', default=0),
		'sensor_microphone': _cfg_val(cfg, 'Microphone', default=1),
		'audio_echo_cancellation': _cfg_val(cfg, 'Echocancellation', default=0),
		'audio_noise_suppression': _cfg_val(cfg, 'Noisesuppression', default=0),
		'audio_auto_gain': _cfg_val(cfg, 'Audiogain', default=0),
		'show_dots': _cfg_val(cfg, 'Showdots', 'Showtouchdots', default=1),
		'backgroundcolor': _cfg_val(cfg, 'Backgroundcolor', default=1),
		'flashlight': _cfg_val(cfg, 'Flashlight', default=1),
		'hapticfeedback': _cfg_val(cfg, 'Hapticfeedback', 'Haptic', default=1),
		'audio_tx': _cfg_val(cfg, 'Audio', default=1),
		'video_tx': _cfg_val(cfg, 'Video', default=1),
		# videoout: 'none' | 'td' | 'js' | 'color' — string value, not int
		'videoout': cfg.get('Videoout', 'none').strip().lower() or 'none',
		# canvas_topbar: show/hide top bar during JS sketch (0=hide, 1=show)
		'canvas_topbar': _cfg_val(cfg, 'Canvastopbar', default=1),
	}
	ice_srv = cfg.get('Iceservers', '').strip()
	if ice_srv:
		out['ice_servers'] = ice_srv
	if cfg.get('Icetransportpolicy', '').strip() == 'relay':
		out['ice_transport_policy'] = 'relay'
	out['cam_resolution'] = cfg.get('Resolution', 'non-commercial').strip().lower() or 'non-commercial'
	return out


def _do_broadcast():
	"""Send config to all registered clients (same approach as callbacks.py _broadcast_msg)."""
	web = _op('web_server_dat')
	if web is None:
		return
	cfg = _read_config()
	msg = json.dumps(_build_config_msg(cfg))
	slots = op('/').fetch('w2td_client_slots', {})
	sent = 0
	for addr in list(slots.keys()):
		try:
			web.webSocketSendText(addr, msg)
			sent += 1
		except Exception:
			pass
	# print(f'[W2TD] Config broadcast -> {sent} clients')
	# # Update web_render_top resolution + transform_top rotation inside webrtc_video_container
	_dim_map = {'non-commercial': 1280, 'fhd': 1920}
	try:
		res_str = ''
		screenmode_str = 'portrait'
		for _k, _v in cfg.items():
			if _k.lower() == 'resolution':
				res_str = _v.strip().lower()
			elif _k.lower() == 'screenmode':
				screenmode_str = _v.strip().lower()
		sq = _dim_map.get(res_str, 1280)
		rotate_deg = -90 if screenmode_str == 'landscape' else 0
		base = _w2td_base()
		container = base.op('webrtc_video_container') if base else None
		if container:
			updated = 0
			for i in range(1, 32):
				top = container.op(f'web_render_top_{i}')
				if top is None:
					break
				try:
					top.par.outputresolution = 'custom'
				except Exception:
					pass
				try:
					top.par.resolutionw = sq
					top.par.resolutionh = sq
					updated += 1
				except Exception:
					pass
				t_top = container.op(f'transform_top_{i}')
				if t_top:
					try:
						t_top.par.rotate = rotate_deg
					except Exception as e:
						print(f'[W2TD] Error setting transform_top_{i} rotate: {e}')
				c_top = container.op(f'crop_top_{i}')
				if c_top:
					crop_px = sq * 7 // 32
					try:
						c_top.par.cropleftunit   = 0
						c_top.par.croprightunit  = 0
						c_top.par.croptopunit    = 0
						c_top.par.cropbottomunit = 0
					except Exception as e:
						print(f'[W2TD] Error setting crop_top_{i} units: {e}')
					try:
						if screenmode_str == 'landscape':
							c_top.par.cropleft   = 0
							c_top.par.cropright  = sq
							c_top.par.croptop    = sq - crop_px
							c_top.par.cropbottom = crop_px
						else:
							c_top.par.cropleft   = crop_px
							c_top.par.cropright  = sq - crop_px
							c_top.par.croptop    = sq
							c_top.par.cropbottom = 0
					except Exception as e:
						print(f'[W2TD] Error setting crop_top_{i} values: {e}')
			if updated:
				# print(f'[W2TD] web_render_top resolution -> {sq}x{sq}, transform rotate -> {rotate_deg} ({updated} TOPs)')
	except Exception:
		pass
	# If videoout=js, send canvas_code directly (no module access — avoids compilation errors)
	try:
		cfg2 = _read_config()
		_vo = next(
			(cfg2[k].strip().lower() for k in ('Videoout', 'videoout', 'Video', 'display_mode')
			 if k in cfg2 and cfg2[k].strip()),
			'none'
		)
		if _vo == 'js':
			jsfile = next(
				(cfg2[k].strip() for k in ('Jsfile', 'jsfile') if k in cfg2 and cfg2[k].strip()),
				''
			)
			if jsfile:
				with open(jsfile, 'r', encoding='utf-8') as _f:
					_code = _f.read()
				_code_msg = json.dumps({'type': 'canvas_code', 'code': _code})
				_slots2 = op('/').fetch('w2td_client_slots', {})
				for _addr in list(_slots2.keys()):
					try:
						web.webSocketSendText(_addr, _code_msg)
					except Exception:
						pass
				# print(f'[W2TD Config Watch] canvas_code sent ({len(_code)} chars)')
	except Exception as e:
		print(f'[W2TD Config Watch] canvas_code send failed: {e}')

	# Trigger webrtc_table_sync to update TX nodes when Audio/Video flags change
	try:
		sync_dat = (_op('webrtc_table_sync')
		            or _op('webrtc_audio_container/webrtc_table_sync')
		            or _op('webrtc_auto_sync'))
		if sync_dat and hasattr(sync_dat, 'module') and hasattr(sync_dat.module, 'sync'):
			sync_dat.module.sync()
	except Exception as e:
		# print(f'[W2TD Config Watch] sync trigger failed: {e}')


def _debounced_broadcast():
	"""Debounced broadcast - schedules _do_broadcast (no web.module access)."""
	global _debounce_timer

	if _debounce_timer is not None:
		try:
			_debounce_timer.kill()
		except Exception:
			pass
		_debounce_timer = None

	delay_frames = max(1, int(DEBOUNCE_DELAY * 60))
	watch = _op('config_watch')
	_debounce_timer = run(
		"op('config_watch').module._do_broadcast()",
		delayFrames=delay_frames,
		fromOP=watch or op('config_watch')
	)


def onTableChange(dat):
	"""Called when w2td_config table changes - debounced broadcast."""
	try:
		_debounced_broadcast()
	except Exception as e:
		print(f'[W2TD Config Watch] Table change error: {e}')


# Required stubs
def onRowChange(dat, rows):
	pass

def onColChange(dat, cols):
	pass

def onCellChange(dat, cells, prev):
	pass

def onSizeChange(dat):
	pass
