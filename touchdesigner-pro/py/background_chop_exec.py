# Execute CHOP - sends mobile background color when background CHOP changes
#
# Supports two modes:
#
# Mode 1 — Broadcast (all clients):
#   CHOP name: w2td_background
#   Channels: r, g, b (0-1 range, single sample)
#   Effect: sends same color to ALL connected mobile clients
#
# Mode 2 — Per-slot (individual clients):
#   CHOP name: w2td_bg_color_bus
#   Channels: slot1_r, slot1_g, slot1_b, slot2_r, slot2_g, slot2_b, ... (0-1 range)
#   Channel name maps to slot: slot{N}_r/g/b → slot N
#   Effect: sends color only to the specific mobile slot
#
# Setup in TD:
#   1. Create a CHOP Execute DAT
#   2. CHOPs parameter: w2td_background w2td_bg_color_bus  (space-separated)
#   3. Value Change parameter: On
#   4. Paste this script

_prev_color = None          # for w2td_background broadcast dedup
_prev_slot_colors = {}      # for w2td_bg_color_bus per-slot dedup: {slot: hex_color}


def _w2td_base():
	try:
		p = parent(1)
		if p:
			return p
	except NameError:
		pass
	for p in ('project1', 'project'):
		w = op(f'{p}/W2TD_Pro')
		if w:
			return w
	root = op('/')
	if root and root.children:
		w = root.children[0].op('W2TD_Pro')
		if w:
			return w
	return op('W2TD_Pro')


def _op(path_suffix, fallback_name=None):
	base = _w2td_base()
	if base:
		o = base.op(path_suffix)
		if o is not None:
			return o
	return op(fallback_name or path_suffix.split('/')[-1])


def _get_callbacks_mod():
	web = _op('web_server_dat')
	cb = _op('callbacks')
	if not web or not cb:
		return None, None
	try:
		mod = cb.module
		return web, mod
	except Exception:
		return None, None


def onValueChange(channel, sampleIndex, val, prev):
	chop = channel.owner
	chop_name = chop.name

	if chop_name in ('w2td_background', 'w2td_color'):
		# Both w2td_background and w2td_color (alias) broadcast to all clients
		_handle_broadcast(chop)

	elif chop_name == 'w2td_bg_color_bus':
		_handle_per_slot(chop, channel.name)


def _handle_broadcast(chop):
	"""Send same color to all clients (w2td_background CHOP)."""
	global _prev_color
	try:
		r = max(0, min(255, int(round(chop['r'].eval() * 255))))
		g = max(0, min(255, int(round(chop['g'].eval() * 255))))
		b = max(0, min(255, int(round(chop['b'].eval() * 255))))
	except Exception:
		return
	hex_color = f'#{r:02x}{g:02x}{b:02x}'
	if hex_color == _prev_color:
		return
	_prev_color = hex_color
	web, mod = _get_callbacks_mod()
	if mod is None:
		return
	if not hasattr(mod, 'send_bg_color_to_all'):
		return
	mod.send_bg_color_to_all(web, hex_color, 0)


def _handle_per_slot(chop, chan_name):
	"""Send color to individual slot (w2td_bg_color_bus CHOP, slot{N}_r/g/b channel names)."""
	global _prev_slot_colors
	import re
	m = re.match(r'^slot(\d+)_(r|g|b)$', chan_name)
	if not m:
		return
	slot = int(m.group(1))
	try:
		r = max(0, min(255, int(round(chop[f'slot{slot}_r'].eval() * 255))))
		g = max(0, min(255, int(round(chop[f'slot{slot}_g'].eval() * 255))))
		b = max(0, min(255, int(round(chop[f'slot{slot}_b'].eval() * 255))))
	except Exception:
		return
	hex_color = f'#{r:02x}{g:02x}{b:02x}'
	if _prev_slot_colors.get(slot) == hex_color:
		return
	_prev_slot_colors[slot] = hex_color
	web, mod = _get_callbacks_mod()
	if mod is None:
		return
	if not hasattr(mod, 'send_bg_color_to_client'):
		return
	mod.send_bg_color_to_client(web, slot, hex_color, 0)


def onOffToOn(channel, sampleIndex, val, prev):
	return


def whileOn(channel, sampleIndex, val, prev):
	return


def onOnToOff(channel, sampleIndex, val, prev):
	return


def whileOff(channel, sampleIndex, val, prev):
	return
