# DAT Execute DAT — watches wob_config Table DAT
# Setup in TD:
#   1. Create a DAT Execute DAT
#   2. Set "DATs" parameter to: wob_config
#   3. Enable "Table Change" checkbox
#   4. Paste this script as its content (or point it to this file)
#
# Automatically broadcasts config changes to all connected clients.
# Uses debouncing to prevent excessive broadcasts during rapid edits.

# Debouncing: wait 300ms after last change before broadcasting
_debounce_timer = None
DEBOUNCE_DELAY = 0.3  # seconds


def _broadcast():
	"""Call callbacks.py broadcast_config() to push config to all clients."""
	web = op('web_server_dat')
	if web is None:
		print('[WOB Config Watch] web_server_dat not found — update op name')
		return
	
	# Use callbacks.py's broadcast_config function for consistency
	try:
		# Import callbacks module and call broadcast_config
		callbacks_module = web.module
		if hasattr(callbacks_module, 'broadcast_config'):
			callbacks_module.broadcast_config(web)
		else:
			print('[WOB Config Watch] broadcast_config not found in callbacks.py')
	except Exception as e:
		print(f'[WOB Config Watch] Broadcast error: {e}')


def _debounced_broadcast():
	"""Debounced broadcast — waits for changes to settle."""
	global _debounce_timer

	# Cancel previous timer
	if _debounce_timer is not None:
		try:
			_debounce_timer.kill()
		except Exception:
			pass
		_debounce_timer = None

	# Schedule broadcast after delay using TD's global run() function
	try:
		delay_frames = max(1, int(DEBOUNCE_DELAY * 60))  # 60fps default
		_debounce_timer = run(
			'web = op("web_server_dat")\n'
			'if web and hasattr(web.module, "broadcast_config"):\n'
			'    web.module.broadcast_config(web)',
			delayFrames=delay_frames
		)
	except Exception:
		# Fallback: immediate broadcast if run() fails
		_broadcast()


def onTableChange(dat):
	"""Called when wob_config table changes — debounced broadcast."""
	try:
		_debounced_broadcast()
	except Exception as e:
		print(f'[WOB Config Watch] Table change error: {e}')


# Required stubs
def onRowChange(dat, rows):
	pass

def onColChange(dat, cols):
	pass

def onCellChange(dat, cells, prev):
	pass

def onSizeChange(dat):
	pass
