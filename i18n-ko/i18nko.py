#!/usr/bin/env python3
"""ARTEX 프론트엔드 중국어 → 한국어 번역 도구.

  python3 i18nko.py extract     중국어 문자열을 추출해 strings.json 생성
  python3 i18nko.py merge       parts/part*.json 을 dict.ko.json 으로 병합
  python3 i18nko.py check       쓰기 없이 치환/미번역 집계 (missing.json 생성)
  python3 i18nko.py apply       dict.ko.json 을 소스에 실제 적용

JSX 텍스트 노드와 문자열 리터럴을 **한 번의 스캔**으로 처리한다. 두 패스로
나누면 JSX 텍스트 안의 "..." 가 리터럴로 먼저 치환되어 그 노드가 사전 키와
어긋난다. 추출과 적용이 같은 정규식을 공유하므로 키는 항상 정확히 일치한다.
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


if __name__ == '__main__':
    c = sys.argv[1] if len(sys.argv) > 1 else 'check'
    {'extract': cmd_extract, 'merge': cmd_merge,
     'check': lambda: cmd_apply(False), 'apply': lambda: cmd_apply(True)}[c]()
