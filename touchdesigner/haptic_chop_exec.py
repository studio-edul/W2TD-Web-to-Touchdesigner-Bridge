# Execute CHOP — wob_haptic 채널 값 변경 시 모바일 진동 제어
# Setup in TD:
#   1. Execute CHOP 생성
#   2. CHOPs 파라미터: wob_haptic
#   3. Value Change: 체크 ✅
#   4. 이 파일을 Script DAT에 연결
#
# Every Frame 폴링 방식보다 효율적 — 값이 실제로 바뀔 때만 실행됨.

def onValueChange(channel, sampleIndex, val, prev):
    """wob_haptic 채널 값이 바뀌면 해당 슬롯에 진동 상태 전송."""
    web = op('web_server_dat')
    if web is None:
        return

    slot = _parse_slot(channel.name)
    if slot is None:
        return

    state = 1 if val != 0 else 0
    try:
        web.module.send_haptic_state(web, slot=slot, state=state)
    except Exception as e:
        print(f'[WOB Haptic] onValueChange error: {e}')


def _parse_slot(name):
    """채널 이름에서 슬롯 번호를 파싱.
    지원 형식: 'slot1', 'ch1', '1'
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
