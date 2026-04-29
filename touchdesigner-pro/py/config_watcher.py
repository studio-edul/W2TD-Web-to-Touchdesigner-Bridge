# config_watcher.py — DAT Execute script for w2td_config Table DAT
#
# Setup in TD:
#   1. Create a DAT Execute inside W2TD_Pro COMP
#   2. Set its "DAT" parameter to w2td_config
#   3. Paste this script (or reference this file)
#   4. Enable "Table Change"
#
# Effect: any row edit in w2td_config immediately pushes updated config
# to all connected clients. If Videoout=js, jsfile is also re-sent.

def onTableChange(dat, rows, cols, cells, prev):
	ws = op('../web_server_dat')
	if ws is None:
		print('[W2TD ConfigWatcher] web_server_dat not found')
		return
	try:
		ws.module.broadcast_config(ws)
	except AttributeError:
		pass  # callbacks module not ready yet (startup)
	except Exception as e:
		print(f'[W2TD ConfigWatcher] Error: {e}')
