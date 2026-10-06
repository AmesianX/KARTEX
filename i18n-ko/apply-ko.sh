#!/usr/bin/env bash
# 한국어화 적용 + 빌드 + 검증. 업스트림을 당긴 뒤에도 이 스크립트 하나만 돌리면 된다.
#
#   ./i18n-ko/apply-ko.sh            적용 → 빌드 → 검증
#   ./i18n-ko/apply-ko.sh --check    쓰기 없이 미번역만 집계
#
# 검증 게이트가 핵심이다. 사전 치환은 업스트림이 문자열을 고치면 **조용히** 매칭에
# 실패하고 중국어가 되살아난다. 그래서 마지막에 빌드 산출물에서 한자를 세고, 0이
# 아니면 비0으로 끝낸다 — 어느 층이 깨졌는지 추적할 필요 없이 한 번에 걸린다.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

# Go 가 PATH 에 없으면 흔한 설치 위치를 덧붙인다. 특정 환경을 가정하지 않는다.
command -v go >/dev/null 2>&1 || export PATH="$HOME/.local/go/bin:/usr/local/go/bin:$PATH"
command -v go >/dev/null 2>&1 || { echo "[x] go 를 찾을 수 없다 — PATH 를 확인하라" >&2; exit 1; }
# 한자 + 우리가 한국어 관례로 정규화한 중국식 부호(、【】（）)만 본다.
# 「」『』 는 한국어 조판에서도 쓰므로 제외한다 — 넣으면 번역된 한국어가 전부 걸린다.
CJK='[\x{4e00}-\x{9fff}\x{3001}\x{3010}\x{3011}\x{ff08}\x{ff09}]'

info(){ printf '\033[36m[*]\033[0m %s\n' "$*"; }
ok(){   printf '\033[32m[+]\033[0m %s\n' "$*"; }
die(){  printf '\033[31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

info '사전 병합'
python3 i18n-ko/i18nko.py merge

if [ "${1:-}" = --check ]; then
	python3 i18n-ko/i18nko.py check
	exit 0
fi

info '소스에 적용 (TSX + Go)'
# i18nko.py 자체가 서식 지정자·템플릿 변수·보호 리터럴·번역금지·리터럴 파손을
# 검사하고, 하나라도 걸리면 아무것도 쓰지 않고 비0 으로 끝난다.
python3 i18n-ko/i18nko.py apply
python3 i18n-ko/manual_fix.py
python3 i18n-ko/literal_patch.py

info 'Go 검증 (vet / build)'
# gofmt 는 게이트로 쓰지 않는다. 업스트림 자체가 gofmt 를 통과하지 않는 파일을
# 여러 개 들고 있어서(db/config.go, db/asset_intercept.go, *_test.go 등 — 구조체
# 주석 정렬), 그걸로 막으면 번역과 무관한 이유로 항상 실패한다. 참고로만 찍는다.
# 실제 게이트는 go vet 과 go build 다 — vet 은 Fprintf 의 서식과 인자를 직접 본다.
if [ -n "$(gofmt -l . 2>/dev/null | grep -v '^web/' || true)" ]; then
	printf '\033[33m[!]\033[0m gofmt 미적용 파일(업스트림 포함, 차단하지 않음): %s\n' \
		"$(gofmt -l . 2>/dev/null | grep -v '^web/' | tr '\n' ' ')"
fi
go vet ./... || die 'go vet 실패 — Fprintf 서식/인자 불일치일 가능성이 높다'
go build ./... >/dev/null || die 'go build 실패'

info '프론트엔드 정적 빌드'
( cd web && npm run build:static )
rm -rf server/webui/dist && mkdir -p server/webui && cp -r web/out server/webui/dist

info '단일 바이너리 빌드'
CGO_ENABLED=0 go build -tags embedui -trimpath -o artex ./cmd/artex

info '검증 게이트: 중국어가 남았는지'
fail=0

# Go 는 **우리 소스**를 본다. 빌드된 바이너리를 grep 하면 의존성(norma SDK 등)과
# 내장 프론트엔드의 mock 데이터까지 세서 쓸 수 없다 — 실제로 3,071종이 나왔고
# 그 대부분이 우리가 손댈 수 없는 것이었다.
#
# 판정 방법: 한자가 든 리터럴에서 **의도적으로 보존한 토큰**(파서 계약)을 걷어낸
# 뒤에도 한자가 남으면 그게 진짜 누락이다. 허용 목록 파일을 따로 두지 않아도
# PROTECTED_LITERAL / DNT_EXACT 하나만 관리하면 된다.
if ! python3 - <<'PY'
import sys, os
sys.path.insert(0, 'i18n-ko')
import re
from i18nko import go_literals, go_files, PROTECTED_LITERAL, DNT_EXACT
BAD = re.compile(r'[\u4e00-\u9fff\u3001\u3010\u3011\uff08\uff09]')
allowed = sorted(set(PROTECTED_LITERAL) | set(DNT_EXACT), key=len, reverse=True)
left = []
for f in go_files():
    src = open(f, encoding='utf-8').read()
    for a, b, _q in go_literals(src):
        s = src[a:b]
        if not BAD.search(s):
            continue
        t = s
        for tok in allowed:
            t = t.replace(tok, '')
        if BAD.search(t):
            left.append((os.path.relpath(f), src[:a].count('\n') + 1, s))
if left:
    print(f'  Go 소스: 미번역 {len(left)}건')
    for f, ln, s in left[:15]:
        print(f'    {f}:{ln}  {s[:70]!r}')
    sys.exit(1)
PY
then
	fail=1
fi

# 프론트엔드는 **소스**를 본다. 빌드 산출물에는 lib/mock/(NEXT_PUBLIC_MOCK=1 에서만
# 실행되는 데모 데이터)이 섞여 들어가고, 그건 업스트림 중국어의 절반 이상이면서
# 실배포에서 한 줄도 실행되지 않는다. i18nko.py 의 SKIP 과 같은 기준으로 센다.
if ! python3 - <<'PY'
import sys, os
sys.path.insert(0, 'i18n-ko')
import json
from i18nko import targets, walk
allow = set(k for k in json.load(open('i18n-ko/allow-untranslated.json', encoding='utf-8'))
            if not k.startswith('_'))
left = []
for f in targets():
    src = open(f, encoding='utf-8').read()
    hits = []
    walk(src, lambda s: (hits.append(s), None)[1])
    for s in hits:
        if s not in allow:
            left.append((os.path.relpath(f), s))
if left:
    print(f'  프론트엔드 소스: 미번역 {len(left)}건')
    for f, s in left[:15]:
        print(f'    {f}  {s[:70]!r}')
    sys.exit(1)
PY
then
	fail=1
fi

# agent 가 읽는 skill 지침. 두 줄은 의도적으로 중국어다 — 대상 사이트가 돌려주는
# 중국어 오류 문구를 매칭하는 정규식이라(preload.js 의 NEGATIVE_RE, reference.md 의
# grep 레시피) 번역하면 중국어 대상에서 탐지가 깨진다.
s=$(grep -rlP "$CJK" skills/ 2>/dev/null | wc -l)
if [ "$s" -gt 2 ]; then
	printf '\033[31m  skills: 한자 포함 파일 %s개 (허용 2개 초과)\033[0m\n' "$s"
	grep -rlP "$CJK" skills/ | sed 's/^/    /'
	fail=1
fi

[ "$fail" -eq 0 ] || die '검증 실패 — 위 위치의 중국어를 사전(parts/)에 추가한 뒤 다시 돌려라.'

ok '한국어화 적용 완료 · 산출물에 중국어 없음'
echo
echo '다음 단계:'
echo '  재기동       pkill -f "artex -addr" ; nohup ./start.sh -addr :8787 -proxy :8788 >artex.log 2>&1 &'
echo '  DB 새로 심기 i18n-ko/reseed-db.sh   (시드 행을 한국어로 다시 만든다 · 데이터 전부 삭제)'
