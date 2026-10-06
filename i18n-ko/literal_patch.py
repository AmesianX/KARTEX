#!/usr/bin/env python3
"""사전(토큰 단위 치환)으로 다룰 수 없는 파일의 정확 문자열 교체.

i18nko.py 는 .ts/.tsx(JSX·문자열 리터럴)와 .go(문자열 리터럴)만 다룬다. 그 밖에
한국어로 바꿔야 하는 문자열이 몇 개 있는데 — 지금은 db/schema.sql 의 시드 값 —
그 파일에 맞는 렉서를 새로 쓰는 건 얻는 것(3건)에 비해 과하다. 대신 **파일 ·
원문 · 교체문**을 그대로 적어두고 적용한다.

손으로 고치지 않고 이 파일에 적는 이유는 재현성이다. 업스트림을 당기거나
`git checkout` 으로 트리를 되돌리면 손패치는 조용히 사라지지만, 이건 apply-ko.sh
가 매번 다시 적용한다. 그리고 원문이 **정확히 1회** 나오지 않으면 중단한다 —
업스트림이 그 문장을 고쳤다는 뜻이고, 그때는 사람이 보고 판단해야 한다.

  python3 literal_patch.py          적용 (이미 적용돼 있으면 건너뜀)
  python3 literal_patch.py --check  쓰기 없이 상태만 보고
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (파일, 원문, 교체문). 원문은 번역 전 업스트림 텍스트.
PATCHES = [
    # 작업 실행 중 자산이 자동 연결될 때 쓰는 사유. 트리거가 넣고 UI 에 보인다.
    ('db/schema.sql', "'任务执行期间自动关联'", "'작업 실행 중 자동 연결'"),
    # 과거 task_assets 를 task_asset_links 로 옮길 때의 사유.
    ('db/schema.sql', "'由历史任务资产关联迁移'", "'과거 작업 자산 연결에서 이전됨'"),
    # 재검증 세션이 삭제됐을 때 finding_retests.error 에 남는 문구.
    ('db/schema.sql', "'复测会话已删除'", "'재검증 세션이 삭제되었습니다'"),
]

# 번역하면 안 되는 것(참고용 주석): schema.sql:1076 의 `LIKE '[模型]%'` 는
# decision_source 를 판정하는 파서 계약이다. 여기 넣지 말 것.


def main():
    check = '--check' in sys.argv
    applied = skipped = 0
    errs = []
    by_file = {}
    for rel, old, new in PATCHES:
        by_file.setdefault(rel, []).append((old, new))

    for rel, items in by_file.items():
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            errs.append(f'{rel}: 파일이 없다')
            continue
        src = open(p, encoding='utf-8').read()
        out = src
        for old, new in items:
            if out.count(new) >= 1 and out.count(old) == 0:
                skipped += 1          # 이미 적용됨
                continue
            n = out.count(old)
            if n != 1:
                errs.append(f'{rel}: 원문이 {n}회 나온다(1회여야 한다) — {old[:40]}')
                continue
            out = out.replace(old, new)
            applied += 1
        if out != src and not check:
            open(p, 'w', encoding='utf-8').write(out)

    tag = '[검사] ' if check else ''
    print(f'{tag}[literal] 적용 {applied}건 / 이미 적용 {skipped}건 / 오류 {len(errs)}건')
    for e in errs:
        print(f'  {e}')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
