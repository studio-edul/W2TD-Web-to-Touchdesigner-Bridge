# Execute CHOP - controls mobile flashlight when w2td_flashlight channel value changes
# Setup in TD:
#   1. Create a CHOP Execute DAT
#   2. CHOPs parameter: w2td_flashlight
#   3. Value Change parameter: On
#   4. Paste this script

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
	"""Send flashlight state to slot when w2td_flashlight channel value changes.
	Assumes channel name is formatted as 'chan1', 'chan2', etc.
	"""
	web = _op('web_server_dat')
	cb = _op('callbacks')
	if not web or not cb:
		return
	try:
		mod = cb.module
	except:
		return
	if not hasattr(mod, 'send_flashlight_to_client'):
		return

	# Channel name must start with 'chan' followed by the slot number
	chan_name = channel.name
	if not chan_name.startswith('chan'):
		return

	slot = None
	try:
		slot = int(chan_name[4:].strip())
	except ValueError:
		pass

	if slot is not None:
		state = 1 if val > 0.5 else 0
		if val != prev:
			mod.send_flashlight_to_client(web, slot=slot, state=state)

def onOffToOn(channel, sampleIndex, val, prev):
	return

def whileOn(channel, sampleIndex, val, prev):
	return

def onOnToOff(channel, sampleIndex, val, prev):
	return

def whileOff(channel, sampleIndex, val, prev):
	return
