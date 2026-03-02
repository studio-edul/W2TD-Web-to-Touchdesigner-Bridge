# DAT Execute DAT — watches w2td_config Table DAT
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

W2TD_BASE = 'W2TD'


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
	return op(W2TD_BASE)


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


def _cfg_str(cfg, *keys, default=''):
	"""Try keys in order; return string."""
	for k in keys:
		if k in cfg and cfg[k] is not None:
			return str(cfg[k]).strip()
	return default


def _build_config_msg(cfg):
	"""Build config JSON dict — keys from w2td_config (Samplerate, Wakelock, Motion, Geolocation, ...)."""
	out = {
		'type': 'config',
		'sample_rate': _cfg_val(cfg, 'Samplerate', 'samplerate', 'sample_rate', default=30),
		'wake_lock': _cfg_val(cfg, 'Wakelock', 'wakelock', 'wake_lock', default=1),
		'haptic': _cfg_val(cfg, 'Haptic', 'haptic', default=1),
		'sensor_motion': _cfg_val(cfg, 'Motion', 'motion', 'sensor_motion', default=1),
		'sensor_orientation': _cfg_val(cfg, 'Orientation', 'orientation', 'sensor_orientation', default=1),
		'sensor_geolocation': _cfg_val(cfg, 'Geolocation', 'geolocation', 'sensor_geolocation', default=1),
		'sensor_touch': _cfg_val(cfg, 'Touch', 'touch', 'sensor_touch', default=1),
		'dev_mode': _cfg_val(cfg, 'Devmode', 'devmode', 'dev_mode', default=1),
		'sensor_rear_camera': _cfg_val(cfg, 'Rearcamera', 'rearcamera', 'sensor_rear_camera', default=0),
		'sensor_front_camera': _cfg_val(cfg, 'Frontcamera', 'frontcamera', 'sensor_front_camera', default=0),
		'sensor_microphone': _cfg_val(cfg, 'Microphone', 'microphone', 'sensor_microphone', default=1),
		'audio_echo_cancellation': _cfg_val(cfg, 'Echocancellation', 'echocancellation', 'audio_echo_cancellation', default=0),
		'audio_noise_suppression': _cfg_val(cfg, 'Noisesuppression', 'noisesuppression', 'audio_noise_suppression', default=0),
		'audio_auto_gain': _cfg_val(cfg, 'Audiogain', 'audiogain', 'audio_auto_gain', default=0),
		'camera_resolution': _cfg_str(cfg, 'Resolution', 'resolution', 'camera_resolution', default='Non-Commercial'),
		'camera_screenmode': _cfg_str(cfg, 'Screenmode', 'screenmode', 'camera_screenmode', default='Portrait'),
	}
	ice_srv = (cfg.get('ice_servers') or cfg.get('Ice_servers') or '').strip()
	if ice_srv:
		out['ice_servers'] = ice_srv
	if (cfg.get('ice_transport_policy') or cfg.get('Ice_transport_policy') or '').strip() == 'relay':
		out['ice_transport_policy'] = 'relay'
	return out


def _get_cam_resolution_dims(cfg=None):
	"""w2td_config Resolution/Screenmode → (w, h). Synced with webrtc.js and callbacks."""
	if cfg is None:
		cfg = _read_config()
	res = _cfg_str(cfg, 'Resolution', 'resolution', default='Non-Commercial')
	mode = (_cfg_str(cfg, 'Screenmode', 'screenmode', default='Portrait') or '').strip().lower()
	presets = {
		'Non-Commercial': {'portrait': (540, 960), 'landscape': (960, 540)},
		'FHD': {'portrait': (1080, 1920), 'landscape': (1920, 1080)},
		'4K': {'portrait': (2160, 3840), 'landscape': (3840, 2160)},
	}
	p = presets.get(res, presets['Non-Commercial'])
	w, h = (p['portrait'] if mode == 'portrait' else p['landscape'])
	return (int(w), int(h))


def _update_cam_top_resolutions(cfg):
	"""Update existing web_render_top resolutions based on config."""
	tw, th = _get_cam_resolution_dims(cfg)
	for slot in range(1, 21):
		path = op('/').fetch(f'w2td_web_render_slot_{slot}', None)
		if path:
			top = op(path)
			if top:
				try:
					top.par.outputresolution = 'custom'
					top.par.resolutionw = tw
					top.par.resolutionh = th
				except Exception:
					pass


def _do_broadcast():
	"""Send config to actually connected clients only (w2td_client_slots may include disconnected addresses)."""
	web = _op('web_server_dat')
	if web is None:
		return
	cfg = _read_config()
	_update_cam_top_resolutions(cfg)
	msg = json.dumps(_build_config_msg(cfg))
	slots = op('/').fetch('w2td_client_slots', {})
	active = set()
	try:
		active = set(getattr(web, 'webSocketConnections', []) or [])
	except Exception:
		pass
	valid = [a for a in slots.keys() if str(a) in active]
	for addr in valid:
		try:
			web.webSocketSendText(addr, msg)
		except Exception:
			pass
	if valid or slots:
		print(f'[W2TD] Config broadcast -> {len(valid)} clients' + (f' ({len(slots) - len(valid)} stale)' if len(slots) > len(valid) else ''))


def _debounced_broadcast():
	"""Debounced broadcast — schedules _do_broadcast (no web.module access)."""
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
	"""Called when w2td_config table changes — debounced broadcast."""
	try:
		_debounced_broadcast()
	except Exception as e:
		print(f'[W2TD Config Watch] Error Table change: {e}')


# Required stubs
def onRowChange(dat, rows):
	pass

def onColChange(dat, cols):
	pass

def onCellChange(dat, cells, prev):
	pass

def onSizeChange(dat):
	pass
