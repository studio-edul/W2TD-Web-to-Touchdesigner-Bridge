# Execute CHOP - controls mobile haptic when w2td_haptic channel value changes
# Setup in TD:
#   1. Create Execute CHOP
#   2. CHOPs parameter: w2td_haptic
#   3. Value Change: checked ✅
#   4. Connect this file to Script DAT
#
# Runs only when value changes (more efficient than Every Frame polling).

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


def _op_web():
	base = _w2td_base()
	if base:
		w = base.op('web_server_dat')
		if w:
			return w
	return op('web_server_dat')


def onValueChange(channel, sampleIndex, val, prev):
	"""Send haptic state to slot when w2td_haptic channel value changes."""
	web = _op_web()
	if web is None:
		return

	slot = _parse_slot(channel.name)
	if slot is None:
		return

	state = 1 if val != 0 else 0
	try:
		web.module.send_haptic_state(web, slot=slot, state=state)
	except Exception as e:
		print(f'[W2TD Haptic] Error onValueChange: {e}')


def _parse_slot(name):
	"""Parse slot number from channel name.
	Supported formats: 'slot1', 'ch1', '1'
	"""
	if name.startswith('slot'):
		try:
			return int(name[4:])
		except ValueError:
			return None

	if name.startswith('ch'):
		try:
			return int(name[2:])
		except ValueError:
			return None

	try:
		return int(name)
	except ValueError:
		return None


# Required stubs
def onOffToOn(channel, sampleIndex, val, prev):
	pass

def onOnToOff(channel, sampleIndex, val, prev):
	pass

def whileOn(channel, sampleIndex, val, prev):
	pass

def whileOff(channel, sampleIndex, val, prev):
	pass
