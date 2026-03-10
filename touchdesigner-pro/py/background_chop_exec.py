# Execute CHOP - sends mobile background color when w2td_background CHOP changes
# Setup in TD:
#   1. Create a CHOP Execute DAT
#   2. CHOPs parameter: w2td_background
#   3. Value Change parameter: On
#   4. Paste this script
#   5. Input CHOP should have 3 channels: r, g, b (0-1 range)

_prev_color = None

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

def onValueChange(channel, sampleIndex, val, prev):
	"""Send background color to all clients when r, g, or b channel changes."""
	global _prev_color
	chop = channel.owner
	try:
		r = max(0, min(255, int(round(chop['r'].eval() * 255))))
		g = max(0, min(255, int(round(chop['g'].eval() * 255))))
		b = max(0, min(255, int(round(chop['b'].eval() * 255))))
	except:
		return
	hex_color = f'#{r:02x}{g:02x}{b:02x}'
	if hex_color == _prev_color:
		return
	_prev_color = hex_color
	web = _op('web_server_dat')
	cb = _op('callbacks')
	if not web or not cb:
		return
	try:
		mod = cb.module
	except:
		return
	if not hasattr(mod, 'send_bg_color_to_all'):
		return
	mod.send_bg_color_to_all(web, hex_color, 0)

def onOffToOn(channel, sampleIndex, val, prev):
	return

def whileOn(channel, sampleIndex, val, prev):
	return

def onOnToOff(channel, sampleIndex, val, prev):
	return

def whileOff(channel, sampleIndex, val, prev):
	return
