# DAT Execute DAT — watches wob_config Table DAT
# Setup in TD:
#   1. Create a DAT Execute DAT
#   2. Set "DATs" parameter to: wob_config
#   3. Enable "Table Change" checkbox
#   4. Paste this script as its content (or point it to this file)
#
# Automatically broadcasts config changes to all connected clients.
# Uses debouncing to prevent excessive broadcasts during rapid edits.
# Broadcast logic is self-contained (no web_server_dat.module access) to avoid module compilation errors.

import json

W2TD_BASE = 'W2TD'


def _wob_base():
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
	base = _wob_base()
	if base:
		o = base.op(path_suffix)
		if o is not None:
			return o
	return op(fallback_name or path_suffix.split('/')[-1])

# Debouncing: wait 300ms after last change before broadcasting
_debounce_timer = None
DEBOUNCE_DELAY = 0.3  # seconds


def _read_config():
	"""Read settings from wob_config Table DAT (key | value)."""
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


def _build_config_msg(cfg):
	"""Build config JSON dict — matches callbacks._config_msg format."""
	out = {
		'type': 'config',
		'sample_rate': int(cfg.get('sample_rate', 30)),
		'wake_lock': int(cfg.get('wake_lock', 1)),
		'haptic': int(cfg.get('haptic', 1)),
		'sensor_motion': int(cfg.get('sensor_motion', 1)),
		'sensor_orientation': int(cfg.get('sensor_orientation', 1)),
		'sensor_geolocation': int(cfg.get('sensor_geolocation', 0)),
		'sensor_touch': int(cfg.get('sensor_touch', 1)),
		'dev_mode': int(cfg.get('dev_mode', 1)),
		'sensor_rear_camera':  int(cfg.get('sensor_rear_camera', 0)),
		'sensor_front_camera': int(cfg.get('sensor_front_camera', 0)),
		'sensor_microphone':   int(cfg.get('sensor_microphone', 1)),
		'audio_echo_cancellation': int(cfg.get('audio_echo_cancellation', 0)),
		'audio_noise_suppression': int(cfg.get('audio_noise_suppression', 0)),
		'audio_auto_gain': int(cfg.get('audio_auto_gain', 0)),
	}
	ice_srv = cfg.get('ice_servers', '').strip()
	if ice_srv:
		out['ice_servers'] = ice_srv
	if cfg.get('ice_transport_policy', '').strip() == 'relay':
		out['ice_transport_policy'] = 'relay'
	return out


def _do_broadcast():
	"""Send config to all connected clients. Uses web operator methods only (no web.module)."""
	web = _op('web_server_dat')
	if web is None:
		return
	cfg = _read_config()
	msg = json.dumps(_build_config_msg(cfg))
	slots = op('/').fetch('w2td_client_slots', {})
	for addr in list(slots.keys()):
		try:
			web.webSocketSendText(addr, msg)
		except Exception:
			pass
	print(f'[W2TD] Config broadcast -> {len(slots)} clients')


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
	"""Called when wob_config table changes — debounced broadcast."""
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
