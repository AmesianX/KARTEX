#!/usr/bin/env python3
"""ARTEX 중국어 → 한국어 번역 도구 (프론트엔드 TSX + 백엔드 Go).

  python3 i18nko.py extract     TSX 중국어를 추출해 strings.json 생성
  python3 i18nko.py go-extract  Go 중국어를 추출해 strings.go.json 생성
  python3 i18nko.py merge       parts/part*.json → dict.ko.json, parts/go-*.json → dict.go.ko.json
  python3 i18nko.py check       쓰기 없이 치환/미번역 집계 (missing*.json 생성)
  python3 i18nko.py apply       두 사전을 소스에 실제 적용

JSX 텍스트 노드와 문자열 리터럴을 **한 번의 스캔**으로 처리한다. 두 패스로
나누면 JSX 텍스트 안의 "..." 가 리터럴로 먼저 치환되어 그 노드가 사전 키와
어긋난다. 추출과 적용이 같은 정규식을 공유하므로 키는 항상 정확히 일치한다.

Go 쪽은 아래 GO_FILES 에 **명시한 파일만** 다룬다(glob 금지 — 이유는 그쪽 주석).
"""
import re, json, os, sys, glob, collections

# 리포 루트 = 이 스크립트(i18n-ko/)의 부모. 작업 경로에 묶이지 않게 한다.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CJK = re.compile(r'[一-鿿]')
CODE_SKIPPED = collections.Counter()
SKIP = ('src/lib/mock/',)          # 데모 전용 가짜 데이터(MOCK=1 에서만 실행)

# `>([^<>]*)<` 는 TS 제네릭도 JSX 로 오인한다
# (`useState<Foo>(null) … KeyboardEvent<HTMLTextAreaElement>` 사이가 통째로 잡힌다).
# 코드 토큰이 섞인 조각은 자동 치환에서 제외하고 따로 보고한다 — 코드를 깨뜨리는
# 쪽이 중국어가 남는 쪽보다 훨씬 나쁘다. 제외분은 manual.json 으로 빠진다.
CODEISH = re.compile(r'[;{}]|//|=>|\bconst \b|\bfunction \b|\breturn\b|React\.')

COMBINED = re.compile(
    r'>([^<>]*)<'                  # 1: JSX 텍스트 블록 (여러 줄 + {expr} 포함)
    r'|"((?:[^"\\\n]|\\.)*)"'      # 2: "..."
    r"|'((?:[^'\\\n]|\\.)*)'"      # 3: '...'
    r'|`((?:[^`\\]|\\.)*)`'        # 4: `...`
    , re.S)


def split_jsx(block):
    """JSX 텍스트 블록을 [(is_text, s), ...] 로 쪼갠다. {expr} 는 원형 보존.

    `复测漏洞 #{findingId}` 처럼 중괄호가 섞인 노드, 그리고 여러 줄에 걸친
    노드까지 다루기 위함이다. 중괄호는 깊이를 세어 중첩도 처리한다.
    """
    out, buf, i, n = [], [], 0, len(block)
    while i < n:
        if block[i] == '{':
            if buf:
                out.append((True, ''.join(buf)))
                buf = []
            depth, j = 0, i
            while j < n:
                if block[j] == '{':
                    depth += 1
                elif block[j] == '}':
                    depth -= 1
                    if depth == 0:
                        j += 1
                        break
                j += 1
            out.append((False, block[i:j]))
            i = j
        else:
            buf.append(block[i])
            i += 1
    if buf:
        out.append((True, ''.join(buf)))
    return out


def targets():
    out = []
    for f in glob.glob(os.path.join(ROOT, 'web/src/**/*.ts'), recursive=True) + \
             glob.glob(os.path.join(ROOT, 'web/src/**/*.tsx'), recursive=True):
        rel = os.path.relpath(f, os.path.join(ROOT, 'web'))
        if any(rel.startswith(s) for s in SKIP):
            continue
        out.append(f)
    return sorted(out)


def walk(src, on_text):
    """COMBINED 로 src 를 스캔한다. on_text(s) 가 문자열을 반환하면 치환."""
    def sub(m):
        jsx = m.group(1)
        if jsx is not None:
            if not CJK.search(jsx):
                return m.group(0)
            parts = []
            for is_text, chunk in split_jsx(jsx):
                if not is_text or not CJK.search(chunk):
                    parts.append(chunk)
                    continue
                s = chunk.strip()
                if CODEISH.search(s):
                    CODE_SKIPPED[s] += 1
                    parts.append(chunk)
                    continue
                new = on_text(s)
                parts.append(chunk.replace(s, new) if new is not None else chunk)
            return '>' + ''.join(parts) + '<'
        s = next(g for g in m.groups()[1:] if g is not None)
        if not CJK.search(s):
            return m.group(0)
        new = on_text(s)
        if new is None:
            return m.group(0)
        q = m.group(0)[0]
        return q + new + q
    return COMBINED.sub(sub, src)


def cmd_extract():
    count, where = collections.Counter(), collections.defaultdict(set)
    for f in targets():
        rel = os.path.relpath(f, ROOT)

        def seen(s):
            count[s] += 1
            where[s].add(rel)
            return None
        walk(open(f, encoding='utf-8').read(), seen)
    items = sorted(count.items(), key=lambda kv: (-kv[1], len(kv[0])))
    json.dump([{'zh': k, 'n': n, 'files': sorted(where[k])[:3]} for k, n in items],
              open(os.path.join(ROOT, 'i18n-ko/strings.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'고유 문자열 {len(items)}개 / 총 글자수 {sum(len(k) for k, _ in items)}')


def cmd_merge():
    d = {}
    for f in sorted(glob.glob(os.path.join(ROOT, 'i18n-ko/parts/part*.json'))):
        d.update(json.load(open(f, encoding='utf-8')))
    d = {k: v for k, v in d.items() if v}
    json.dump(d, open(os.path.join(ROOT, 'i18n-ko/dict.ko.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, sort_keys=True)
    print(f'병합 {len(d)}개 → dict.ko.json')


def cmd_apply(write):
    d = json.load(open(os.path.join(ROOT, 'i18n-ko/dict.ko.json'), encoding='utf-8'))
    hits, missing = collections.Counter(), collections.Counter()
    changed = 0
    for f in targets():
        src = open(f, encoding='utf-8').read()

        def tr(s):
            if s in d:
                hits[s] += 1
                return d[s]
            missing[s] += 1
            return None
        new = walk(src, tr)
        if new != src:
            changed += 1
            if write:
                open(f, 'w', encoding='utf-8').write(new)
    tag = '' if write else '[검사] '
    print(f'{tag}사전 {len(d)}개 / 파일 {changed}개 / 치환 {sum(hits.values())}건')
    print(f'{tag}미번역 고유 {len(missing)}개 (출현 {sum(missing.values())}건)')
    json.dump([{'zh': k, 'n': n} for k, n in missing.most_common()],
              open(os.path.join(ROOT, 'i18n-ko/missing.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'{tag}코드 섞여 자동 제외 {len(CODE_SKIPPED)}개 → manual.json (수동 처리)')
    json.dump([{'zh': k, 'n': n} for k, n in CODE_SKIPPED.most_common()],
              open(os.path.join(ROOT, 'i18n-ko/manual.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


# ── Go (백엔드) ──────────────────────────────────────────────────────────
#
# glob 을 쓰지 않고 파일을 하나씩 적는다. Go 전체를 긁으면 db/db.go 의 시드
# 데이터까지 잡히는데, 거기엔 agent 프롬프트 본문이 들어있다. 프롬프트는 도구
# 사용 규약이 촘촘히 박힌 글이라 번역하면 동작이 흔들린다(출력 언어는 프롬프트
# 끝에 지시를 덧붙이는 agent_lang.py 가 따로 담당). 그래서 "화면/산출물에
# 보이는 문자열이 있는 파일"만 명시적으로 추가한다.
# Go 전체를 대상으로 한다. 치환은 사전에 **있는 키만** 일어나므로(opt-in),
# 대상을 넓혀도 번역하지 않은 문자열은 그대로 남고 missing.go.json 에 쌓인다.
# 그게 곧 할 일 목록이다. 테스트 파일은 제외 — 중국어가 있어도 화면에 안 나온다.
GO_SKIP = ('web/', 'i18n-ko/', 'server/webui/')


def go_files():
    out = []
    for f in glob.glob(os.path.join(ROOT, '**/*.go'), recursive=True):
        rel = os.path.relpath(f, ROOT)
        if rel.endswith('_test.go') or any(rel.startswith(s) for s in GO_SKIP):
            continue
        out.append(f)
    return sorted(out)

# Go 쪽 한자 탐지는 TSX 보다 넓게 본다. CJK 한자(U+4E00-9FFF)만 보면 `、`(U+3001)
# 같은 CJK 구두점과 전각 기호가 그대로 남는다 — report.go 의 자산 목록 구분자가
# 실제로 그렇게 살아남아 화면에 보였다. 전각/반각 폭 형태(U+FF00-FFEF)까지 포함한다.
# TSX 쪽 CJK 는 건드리지 않는다(치환 3,445건이 걸려 있어 흔들 이유가 없다).
CJK_GO = re.compile(r'[一-鿿　-〿＀-￯]')

# fmt 서식 지정자. 번역이 이걸 빠뜨리거나 순서를 바꾸면 런타임에 깨지므로
# 적용 전에 키와 값에서 같은 순서로 나오는지 확인한다(verbs_ok).
VERB = re.compile(r'%[-+#\x20 0-9.*\[\]]*[a-zA-Z%]')

# 중국어 일부는 UI 문구가 아니라 **프롬프트와 Go 파서 사이의 계약**이다. 프롬프트가
# 모델에게 "이 말머리로 답하라"고 지시하고 Go 가 그 출력을 접두사/정규식으로 파싱한다.
# 한쪽만 번역하면 조용히 깨진다. 두 종류로 나눠 다룬다.
#
# 주의: 단어 단위로 보호하면 안 된다. `漏洞` 를 통째로 보호하면 평범한 산문인
# `漏洞明细`(→ 취약점 상세) 까지 번역을 거부하게 된다. 계약은 **패턴**이다.

# (1) 문장 안에 그대로 살아남아야 하는 리터럴. Go 가 이 토큰을 찾거나 쓴다.
#   intercept/intercept.go:481 · db/intercept.go:251 · task_archives_restore.go:680
#       HasPrefix(..., "[模型]")
#   server/chat_mentions.go:20 · web/src/lib/chat-mentions.ts:55
#       @[漏洞#123] 멘션 문법 — 백엔드와 프론트 정규식이 쌍이라 둘을 같이 바꿔야 한다
#   intercept/prompt.go:196,200 — LLM 심판 판정문의 세 토막 구분자.
#       parseVerdict 는 comment 가 `实际操作：` 로 시작하고 `；成功后的后果：` 와
#       `；命中规则：` 를 포함하며 세 토막이 모두 비지 않아야 통과시킨다. 하나라도
#       어긋나면 빈 Verdict{} 를 돌려주고, 그러면 판정이 버려져 llm_judge_fail_action
#       기본값(allow)으로 떨어진다 — 즉 **조용히 전부 통과**시킨다.
PROTECTED_LITERAL = (
    '[模型]',
    # prompt.go 안에서 「；」 가 붙은 형태와 안 붙은 형태가 섞여 쓰인다.
    # 짧은 쪽을 등록하면 양쪽 다 걸린다.
    '实际操作：', '成功后的后果：', '命中规则：',
    '@[漏洞', '@[资产', '@[企业', '@[接口', '@[IP',
    '@[应用', '@[域名', '@[子域名', '@[服务',
)

# (2) 아예 번역하면 안 되는 문자열. Go 가 이 리터럴 자체를 매처로 쓴다.
#   intercept/prompt.go:193    HasPrefix(reason, "实际操作：")
#   server/server.go:3823,3827 HasPrefix(m, "意图") / HasPrefix(m, "提示")
#       — 매칭 대상은 **사용자가 채팅에 입력한 메시지**이고, 코드가 쓰는 리터럴은
#         이 두 토큰 자체다.
#
# 접두사 비교가 아니라 **정확 일치**여야 한다. 접두사로 막으면 `提示内容`(힌트 내용,
# add_hint 의 파라미터 설명)이나 `意图 id（= work 句柄）` 처럼 그 단어로 시작하기만
# 하는 평범한 UI 문자열까지 번역을 거부하게 된다 — 실제로 그렇게 6건이 억울하게
# 중국어로 남아 있었다. 그런 문자열 안에 계약 토큰이 들어있는 경우는
# PROTECTED_LITERAL 이 따로 지킨다.
DNT_PREFIX = ()

# (3) 통째로 번역 금지. 우리 쪽 문구가 아니라 **외부가 보내온 문자열에 대한 매처**다.
#   agent/provider.go:306-310  LLM 공급자의 오류 본문을 strings.Contains 로 검사해
#       "잔액/한도 소진"을 판정한다. 중국계 공급자(DeepSeek·Zhipu·Moonshot 등)가
#       과금 오류를 중국어로 돌려주므로, 번역하면 감지가 깨지고 LLM 폴백 체인이
#       다음 설정으로 전환하지 못한다. 화면에 표시되는 문자열이 아니다.
DNT_EXACT = (
    # agent/provider.go:306-310 — 공급자 과금 오류 본문 매처
    '余额不足', '额度不足', '额度已用尽', '欠费',
    # 위 (2) 의 매처 리터럴 자체
    '实际操作：', '意图', '提示',
    # db/company_scope.go:160 — ICP 마커 / ContainsAny 입력 구두점 집합
    '备案', '.．。',
    # server/chat_mentions.go:20 — 멘션 종류 토큰 (web 쪽 정규식과 쌍)
    '漏洞', '资产', '企业', '接口', '应用', '域名', '子域名', '服务',
)


def protected_missing(k, v):
    """키에 있던 보호 리터럴이 값에서 사라졌는지. 빠진 토큰 목록."""
    return [t for t in PROTECTED_LITERAL if t in k and t not in v]


def dnt_violation(k):
    """이 키가 파서 계약이면 True — 번역 자체를 거부한다."""
    return any(k.startswith(t) for t in DNT_PREFIX) or k in DNT_EXACT


def verbs(s):
    return [m.group(0) for m in VERB.finditer(s) if m.group(0) != '%%']


def verbs_ok(k, v):
    return verbs(k) == verbs(v)


# Go 템플릿 변수. 프롬프트는 text/template 로 렌더되므로 `{{.Goal}}` 류가 그대로
# 남아야 한다. 하나라도 빠지면 그 자리에 값이 안 들어가고 조용히 빈 프롬프트가 된다.
TMPLVAR = re.compile(r'\{\{[^}]*\}\}')


def tmplvars(s):
    return TMPLVAR.findall(s)


def tmplvars_ok(k, v):
    return sorted(tmplvars(k)) == sorted(tmplvars(v))


def go_literals(src):
    """Go 소스에서 **문자열 리터럴 내용물**의 (start, end) 스팬만 돌려준다.

    주석의 한자는 화면에 안 나오고 업스트림 diff 만 키우므로 건드리지 않는다.
    정규식만으로는 `// 설명："abc"` 의 따옴표와 진짜 리터럴을 구분할 수 없어
    상태 기계로 훑는다. rune 리터럴도 반드시 건너뛴다 — `'"'` 가 유효한 Go
    코드라서, 안 건너뛰면 그 따옴표가 문자열 시작으로 오인된다.
    """
    spans, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            j = src.find('\n', i)
            i = n if j < 0 else j + 1
        elif c == '/' and i + 1 < n and src[i + 1] == '*':
            j = src.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c == "'":
            j = i + 1
            while j < n:
                if src[j] == '\\':
                    j += 2
                    continue
                if src[j] == "'":
                    j += 1
                    break
                j += 1
            i = j
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"' and src[j] != '\n':
                j += 2 if src[j] == '\\' else 1
            spans.append((i + 1, j, '"'))
            i = j + 1
        elif c == '`':
            j = src.find('`', i + 1)
            if j < 0:
                break
            spans.append((i + 1, j, '`'))
            i = j + 1
        else:
            i += 1
    return spans


def bare_quotes(s):
    r"""이스케이프되지 않은 " 의 개수. \\ 를 먼저 지워 \\" 를 오판하지 않게 한다."""
    return s.replace('\\\\', '').replace('\\"', '').count('"')


def go_walk(src, on_text, errs=None):
    """go_literals 스팬을 돌며 on_text(s) 가 문자열을 반환하면 치환.

    구분자별 적법성을 **치환 지점에서** 검사한다. 사전 단계에서는 못 한다 — 같은
    문자열이 "..." 리터럴과 백틱 raw 리터럴 양쪽에 나올 수 있고, 맨따옴표와 실제
    개행은 전자에서만 불법이다. 실제로 이것 때문에 agent/tools.go 가 깨졌다:
    원문의 전각 “…” 를 ASCII "…" 로 번역해 리터럴이 중간에 끊겼다.
    """
    out, prev = [], 0
    for a, b, q in go_literals(src):
        s = src[a:b]
        if not CJK_GO.search(s):
            continue
        new = on_text(s)
        if new is None:
            continue
        if q == '"':
            why = None
            if bare_quotes(new) > bare_quotes(s):
                why = '이스케이프 안 된 " — 「」 나 \\" 를 쓸 것'
            elif '\n' in new or '\r' in new:
                why = '실제 개행 — "..." 리터럴에는 들어갈 수 없다'
            if why:
                if errs is not None:
                    errs.append((why, s, new))
                continue
        out.append(src[prev:a])
        out.append(new)
        prev = b
    out.append(src[prev:])
    return ''.join(out)


def go_targets():
    return go_files()


def cmd_go_extract():
    count, where = collections.Counter(), collections.defaultdict(set)
    for f in go_targets():
        src = open(f, encoding='utf-8').read()
        rel = os.path.relpath(f, ROOT)
        for a, b, _q in go_literals(src):
            s = src[a:b]
            if CJK_GO.search(s):
                count[s] += 1
                where[s].add(rel)
    items = sorted(count.items(), key=lambda kv: (-kv[1], len(kv[0])))
    json.dump([{'zh': k, 'n': n, 'files': sorted(where[k])} for k, n in items],
              open(os.path.join(ROOT, 'i18n-ko/strings.go.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'[go] 고유 문자열 {len(items)}개 → strings.go.json')


def cmd_go_merge():
    d = {}
    for f in sorted(glob.glob(os.path.join(ROOT, 'i18n-ko/parts/go-*.json'))):
        d.update(json.load(open(f, encoding='utf-8')))
    d = {k: v for k, v in d.items() if v}
    json.dump(d, open(os.path.join(ROOT, 'i18n-ko/dict.go.ko.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, sort_keys=True)
    print(f'[go] 병합 {len(d)}개 → dict.go.ko.json')


def cmd_go_apply(write):
    p = os.path.join(ROOT, 'i18n-ko/dict.go.ko.json')
    if not os.path.exists(p):
        print('[go] dict.go.ko.json 없음 — merge 먼저')
        return 0
    d = json.load(open(p, encoding='utf-8'))

    # 아래 검사 중 하나라도 걸리면 **아무것도 쓰지 않는다**. 깨진 Fprintf 나
    # 끊어진 파서 계약은 중국어가 남는 것보다 훨씬 나쁘다.
    errs = []
    for k, v in d.items():
        if dnt_violation(k):
            errs.append(('파서 계약(번역 금지)', k, v, ''))
        if not verbs_ok(k, v):
            errs.append(('서식 지정자', k, v, f'{verbs(k)} → {verbs(v)}'))
        if not tmplvars_ok(k, v):
            errs.append(('템플릿 변수', k, v, f'{tmplvars(k)} → {tmplvars(v)}'))
        miss = protected_missing(k, v)
        if miss:
            errs.append(('보호 리터럴 누락', k, v, ', '.join(miss)))
    if errs:
        print(f'[go] 중단: 검사 실패 {len(errs)}건 — 아무것도 쓰지 않았다')
        for why, k, v, detail in errs[:12]:
            print(f'  [{why}] {detail}')
            print(f'    키   {k[:70]!r}')
            print(f'    번역 {v[:70]!r}')
        return 1

    hits, missing, changed = collections.Counter(), collections.Counter(), 0
    pending = []
    for f in go_targets():
        src = open(f, encoding='utf-8').read()

        def tr(s):
            if s in d:
                hits[s] += 1
                return d[s]
            missing[s] += 1
            return None
        lit = []
        new = go_walk(src, tr, lit)
        if lit:
            for why, k, v in lit:
                errs.append((f'리터럴 파손({os.path.relpath(f, ROOT)}): {why}', k, v, ''))
            continue
        pending.append((f, new, src))
    if errs:
        print(f'[go] 중단: 리터럴 파손 {len(errs)}건 — 아무것도 쓰지 않았다')
        for why, k, v, _ in errs[:12]:
            print(f'  [{why}]')
            print(f'    키   {k[:80]!r}')
            print(f'    번역 {v[:80]!r}')
        return 1
    for f, new, src in pending:
        if new != src:
            changed += 1
            if write:
                open(f, 'w', encoding='utf-8').write(new)
    tag = '' if write else '[검사] '
    print(f'{tag}[go] 사전 {len(d)}개 / 파일 {changed}개 / 치환 {sum(hits.values())}건')
    print(f'{tag}[go] 미번역 고유 {len(missing)}개 (출현 {sum(missing.values())}건)')
    json.dump([{'zh': k, 'n': n} for k, n in missing.most_common()],
              open(os.path.join(ROOT, 'i18n-ko/missing.go.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    return 0


def cmd_merge_all():
    cmd_merge()
    cmd_go_merge()


def cmd_apply_all(write):
    cmd_apply(write)
    return cmd_go_apply(write)


if __name__ == '__main__':
    c = sys.argv[1] if len(sys.argv) > 1 else 'check'
    rc = {'extract': cmd_extract, 'go-extract': cmd_go_extract,
          'merge': cmd_merge_all,
          'check': lambda: cmd_apply_all(False),
          'apply': lambda: cmd_apply_all(True)}[c]()
    sys.exit(rc or 0)
