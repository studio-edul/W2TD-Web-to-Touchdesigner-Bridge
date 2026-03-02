"""
w2td_zombie_checker.py
Zombie slot auto-cleanup for W2TD.

Setup in TouchDesigner:
  1. Create an Execute DAT named 'w2td_zombie_checker'
  2. Paste this script content into it
  3. Enable 'Execute Frame': On (runs _maybe_check every frame, throttled to every 10s)

Optional w2td_config key:
  slot_timeout  |  30    (seconds before a silent slot is released; min 10)

Requires:
  - web_server_dat: Web Server DAT (to close stale WebSocket connections)
  - callbacks.py module accessible via op('web_server_dat').module
"""
import time

_last_check = [0.0]
CHECK_INTERVAL = 10.0  # internal check cadence (seconds)


def _get_timeout():
	"""Read slot_timeout from w2td_config (default 30s, minimum 10s)."""
	try:
		cfg_op = op('w2td_config')
		if cfg_op is None:
			for proj in ('project1', 'project'):
				w = op(f'{proj}/W2TD')
				if w:
					cfg_op = w.op('w2td_config')
					break
		if cfg_op is not None:
			for r in range(1, cfg_op.numRows):
				if str(cfg_op[r, 0]) == 'slot_timeout':
					return max(10, int(str(cfg_op[r, 1])))
	except Exception:
		pass
	return 30


def _check_zombies():
	"""Scan all active slots and release any that haven't sent data within timeout."""
	slots = op('/').fetch('w2td_client_slots', {})
	if not slots:
		return

	timeout = _get_timeout()
	now = time.time()
	ws_dat = op('web_server_dat')
	ws_module = ws_dat.module if ws_dat else None

	for addr, slot in list(slots.items()):
		last_seen = op('/').fetch(f'w2td_last_seen_{slot}', 0)
		if last_seen == 0:
			# Never received a message — skip (still in hello phase)
			continue
		elapsed = now - last_seen
		if elapsed > timeout:
			print(f'[W2TD Zombie] Slot {slot} ({addr}) silent for {int(elapsed)}s — releasing')
			if ws_module:
				try:
					ws_module._release_slot(addr, slot)
				except Exception as e:
					print(f'[W2TD Zombie] 에러 _release_slot error: {e}')
				try:
					ws_module._wt_remove_by_slot(slot)
				except Exception:
					pass
				try:
					ws_module._clear_pending_cam_for_slot(slot)
				except Exception:
					pass
			# Try to close the stale WebSocket connection
			if ws_dat:
				try:
					ws_dat.webSocketClose(addr)
				except Exception:
					pass


def onFrameStart(frame):
	"""Called every frame. Checks zombies every CHECK_INTERVAL seconds."""
	now = time.time()
	if now - _last_check[0] < CHECK_INTERVAL:
		return
	_last_check[0] = now
	try:
		_check_zombies()
	except Exception as e:
		print(f'[W2TD Zombie] 에러 Error: {e}')
