"""
W2TD Pro | canvas_code_dat_exec.py
===================================
DAT Execute — W2TD_Pro COMP 내부 배치.
연결된 In DAT의 내용이 바뀔 때마다 canvas_code를 전체 모바일에 브로드캐스트.

설정 방법:
  1. W2TD_Pro 내부에 In DAT 추가 → 이름: canvas_code_in
  2. DAT Execute 추가 → Parameters > DATs: canvas_code_in
  3. Parameters > Callbacks DAT: 이 파일
  4. W2TD_Pro COMP 외부에서 Text DAT를 canvas_code_in에 연결

동작:
  - Text DAT 내용 변경 → onTableChange → send_canvas_code_to_all 호출
  - 빈 텍스트를 넣으면 모바일 스케치 중단 (clear)
  - 새로 접속하는 클라이언트에는 callbacks.py의 _replay_canvas_code가 자동 재전송
    (videoout='js'일 때만 재전송됨)
"""


def _send(dat):
    code = dat.text if dat is not None else ''
    ws = op('../web_server_dat')
    if ws is None:
        print('[W2TD Canvas DAT] web_server_dat not found')
        return
    try:
        ws.module.send_canvas_code_to_all(ws, code)
    except AttributeError:
        # callbacks.py 모듈이 아직 로드되지 않은 경우
        print('[W2TD Canvas DAT] callbacks module not ready — retry on next change')
    except Exception as e:
        print(f'[W2TD Canvas DAT] Error sending canvas code: {e}')


def onTableChange(dat, prevDAT, info):
    """In DAT 내용이 변경될 때마다 호출."""
    _send(dat)


def onFileChange(dat, prevDAT, info):
    """In DAT가 외부 파일을 참조하고 있을 때 파일이 변경되면 호출."""
    _send(dat)
