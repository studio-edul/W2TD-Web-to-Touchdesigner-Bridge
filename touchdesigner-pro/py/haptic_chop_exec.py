# Execute CHOP - controls mobile haptic when w2td_haptic channel value changes
# Setup in TD:
#   1. Create a CHOP Execute DAT
#   2. CHOPs parameter: w2td_haptic
#   3. Value Change parameter: On
#   4. Paste this script
#   5. Channel names: slot1, slot2, ... (targets specific slot) or 'all' (targets all connected devices)

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
	"""Send haptic state when w2td_haptic channel value changes.
	Channel name 'slot1', 'slot2', etc. targets a specific slot.
	Channel name 'all' targets all connected devices.
	"""
	web = _op('web_server_dat')
	cb = _op('callbacks')
	if not web or not cb:
		return
	try:
		mod = cb.module
	except:
		return

	chan_name = channel.name
	state = 1 if val > 0.5 else 0
	if val == prev:
		return

	# 'all' channel: broadcast to all connected devices
	if chan_name == 'all':
		if hasattr(mod, 'send_haptic_state_to_all'):
			mod.send_haptic_state_to_all(web, state=state)
		return

	# 'slot<N>' channel: target specific slot
	if not chan_name.startswith('slot'):
		return
	try:
		slot = int(chan_name[4:].strip())
	except ValueError:
		return
	if hasattr(mod, 'send_haptic_state'):
		mod.send_haptic_state(web, slot=slot, state=state)

def onOffToOn(channel, sampleIndex, val, prev):
	return

def whileOn(channel, sampleIndex, val, prev):
	return

def onOnToOff(channel, sampleIndex, val, prev):
	return

def whileOff(channel, sampleIndex, val, prev):
	return
