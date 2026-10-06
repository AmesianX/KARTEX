#!/usr/bin/env python3
"""내장/커스텀 Agent 의 프롬프트에 한국어 출력 지시를 넣는다.

UI 라벨(dict.ko.json)과 달리 agent 산출물의 언어는 프롬프트가 정한다. 프롬프트
본문을 번역하지는 않는다 — 도구 사용 규약이 촘촘히 박혀 있어 건드리면 동작이
흔들린다. 대신 끝에 출력 언어 블록을 덧붙이고, 기존 중국어 언어 지시만 바꿔
충돌을 없앤다. MARKER 로 멱등하며, UI 의 「기본값 복원」으로 되돌릴 수 있다.

  python3 agent_lang.py            적용
  python3 agent_lang.py --dry      무엇이 바뀌는지만 출력
"""
import json, os, sys, urllib.request

BASE = os.environ.get('ARTEX_URL', 'http://127.0.0.1:8787')

# 토큰: ARTEX_TOKEN, 또는 ARTEX_TOKEN_FILE 이 가리키는 파일.
# 없으면 ARTEX_PASSWORD 로 로그인해서 받는다 (username 은 ARTEX 고정).
def _token():
    if os.environ.get('ARTEX_TOKEN'):
        return os.environ['ARTEX_TOKEN'].strip()
    f = os.environ.get('ARTEX_TOKEN_FILE')
    if f:
        return open(f).read().strip()
    pw = os.environ.get('ARTEX_PASSWORD')
    if not pw:
        sys.exit('ARTEX_TOKEN, ARTEX_TOKEN_FILE 또는 ARTEX_PASSWORD 중 하나가 필요합니다.')
    r = urllib.request.Request(
        BASE + '/api/auth/login',
        data=json.dumps({'username': 'ARTEX', 'password': pw}).encode(),
        method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read())['token']


TOKEN = _token()
AGENTS = ['goals', 'planner', 'mainagent', 'worker', 'auto', 'pentest', 'reporter', 'retester']

MARKER = '━━ 출력 언어 (ARTEX 한국어 설정) ━━'
BLOCK = f'''

{MARKER}
사용자에게 보이는 모든 산출물은 **한국어**로 작성한다. finding 의 summary / description,
상세 리포트, 대화 응답, 상태 메시지, 삭제·중단 사유가 모두 해당된다.
단 다음은 원문을 그대로 유지한다: 도구 이름과 파라미터, 명령어와 그 출력, 코드,
HTTP 요청/응답 원문, 로그, URL, 그리고 취약점 분류명 같은 기술 식별자(예: SQL Injection).'''

# 기존 중국어 언어 지시 → 한국어. 남겨 두면 지시가 서로 충돌한다.
REPLACE = {
    '使用简洁中文答复。': '간결한 한국어로 답변한다.',
    '- 全程**中文**。': '- 전 과정 **한국어**로 작성한다。',
}


def req(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={'Authorization': 'Bearer ' + TOKEN,
                                        'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read() or b'{}')


def main():
    dry = '--dry' in sys.argv
    for key in AGENTS:
        d = req('GET', f'/api/agents/{key}')
        prompt = d.get('prompt') or ''
        if not prompt:
            print(f'{key:10} 프롬프트 없음 — 건너뜀')
            continue
        if MARKER in prompt:
            print(f'{key:10} 이미 적용됨 — 건너뜀')
            continue
        new = prompt
        swapped = []
        for zh, ko in REPLACE.items():
            if zh in new:
                new = new.replace(zh, ko)
                swapped.append(zh)
        new += BLOCK
        tag = '[dry] ' if dry else ''
        if dry:
            print(f'{tag}{key:10} {len(prompt)} → {len(new)}자  치환={swapped}')
            continue
        res = req('PUT', f'/api/agents/{key}/prompt',
                  {'template': new, 'note': '한국어 출력 지시 추가 (i18n-ko)'})
        print(f'{key:10} v{res.get("version")} 저장  {len(prompt)} → {len(new)}자  치환={swapped}')


if __name__ == '__main__':
    main()
