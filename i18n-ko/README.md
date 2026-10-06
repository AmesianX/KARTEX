# i18n-ko — ARTEX 한국어화

[ARTEX](https://github.com/Autumn-27/ARTEX) 의 UI(중국어)와 agent 산출물을 한국어로 바꾼다.
업스트림은 i18n 프레임워크가 없고 문자열이 TSX 에 직접 박혀 있어, **사전 + 적용 스크립트**
방식을 쓴다. `git pull` 로 업스트림을 당겨온 뒤 `apply` 를 다시 돌리면 재적용된다.

## 구성

| 파일 | 역할 |
| --- | --- |
| `i18nko.py` | 추출 / 병합 / 검사 / 적용 |
| `parts/part*.json` | 번역 사전 조각 (`{중국어: 한국어}`) |
| `dict.ko.json` | `parts/` 를 병합한 적용용 사전 |
| `manual_fix.py` | 자동 치환에서 제외된 UI 텍스트를 줄 단위로 교체 |
| `agent_lang.py` | agent 프롬프트에 한국어 출력 지시 주입 |
| `strings.json` / `missing.json` / `manual.json` | 추출·검사 리포트 (산출물) |

## 사용법

```bash
cd i18n-ko

python3 i18nko.py extract   # 소스에서 중국어 추출 → strings.json
python3 i18nko.py merge     # parts/*.json → dict.ko.json
python3 i18nko.py check     # 쓰기 없이 치환/미번역 집계
python3 i18nko.py apply     # 소스에 실제 적용

python3 manual_fix.py       # 코드와 섞인 UI 텍스트 보정 (apply 이후)
```

agent 산출물(발견 요약, 리포트, 대화)을 한국어로:

```bash
ARTEX_PASSWORD=<관리자 비밀번호> python3 agent_lang.py --dry   # 미리보기
ARTEX_PASSWORD=<관리자 비밀번호> python3 agent_lang.py         # 적용
```

`ARTEX_TOKEN` / `ARTEX_TOKEN_FILE` / `ARTEX_URL` 로도 지정할 수 있다.
프롬프트는 버전이 남으므로 UI 「Agent 관리」의 「기본값 복원」으로 되돌릴 수 있다.

## 적용 후 재빌드

```bash
cd web && npm ci && npm run build:static && cd ..
cp -r web/out server/webui/dist
CGO_ENABLED=0 go build -tags embedui -o artex ./cmd/artex
```

> Next.js 16 은 Node 20+ 가 필요하다.

## 설계 메모

- **추출과 적용이 같은 정규식을 공유한다.** 키가 어긋나지 않는 유일한 방법이다.
- **JSX 텍스트와 문자열 리터럴을 한 번의 스캔으로 처리한다.** 두 패스로 나누면
  JSX 텍스트 안의 `"..."` 가 리터럴로 먼저 치환되어 그 노드가 사전 키와 어긋난다.
- **JSX 블록은 중괄호 깊이로 쪼갠다.** `复测漏洞 #{findingId}` 처럼 `{expr}` 가 섞인
  노드와 여러 줄에 걸친 노드를 놓치지 않기 위함이다.
- **코드 토큰이 섞인 조각은 자동 치환에서 뺀다** (`CODEISH`). `>([^<>]*)<` 는 TS 제네릭
  (`useState<Foo>(null) … KeyboardEvent<HTMLTextAreaElement>` 사이)도 JSX 로 오인한다.
  제외분은 `manual.json` 으로 빠지고 `manual_fix.py` 가 줄 단위로 처리한다.
- **번역하지 않는 것**: `web/src/lib/mock/` (데모 전용 가짜 데이터, `NEXT_PUBLIC_MOCK=1`
  에서만 실행), 코드 주석(화면에 안 나오고 업스트림 diff 만 키운다), ICP 등록번호 같은
  고유명사, agent 프롬프트 본문(도구 사용 규약이 박혀 있어 건드리면 동작이 흔들린다).
