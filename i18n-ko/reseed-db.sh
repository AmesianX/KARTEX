#!/usr/bin/env bash
# DB 를 비우고 한국어 시드로 다시 심는다. **데이터가 전부 사라진다.**
#
# 시드(인터셉트 규칙, Agent 이름·설명·프롬프트, MCP, skill 가시성)는 각 INSERT 가
# ON CONFLICT DO NOTHING 이라, 소스를 한국어로 고쳐도 **이미 들어간 행은 바뀌지 않는다.**
# 그래서 운영 데이터가 없는 초기 단계에서는 이렇게 비우는 게 가장 깨끗하다.
#
# 운영 중이라면 이 스크립트를 쓰지 말고 행을 UPDATE 하는 쪽을 택해야 한다.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"

[ -f .pgpw ] || { echo "[x] .pgpw 가 없다 — DB 비밀번호를 찾을 수 없다" >&2; exit 1; }

cat <<'WARN'
┌──────────────────────────────────────────────────────────┐
│  경고: artex 데이터베이스를 삭제하고 다시 만든다.        │
│  작업·자산·발견·트래픽 인덱스·관리자 비밀번호가         │
│  모두 사라진다. 되돌릴 수 없다.                          │
└──────────────────────────────────────────────────────────┘
WARN
read -rp '계속하려면 reseed 라고 입력: ' a
[ "$a" = reseed ] || { echo '취소'; exit 1; }

echo '[*] artex 정지'
pkill -f 'start.sh -addr' 2>/dev/null || true
pkill -f '\./artex -addr' 2>/dev/null || true
sleep 2

echo '[*] 데이터베이스 재생성'
# WITH (FORCE) 로 남은 연결을 끊는다(PG 13+). pkill 직후에도 artex 의 커넥션 풀이
# 잠깐 살아있어서, 없으면 "database is being accessed by other users" 로 실패한다.
sg docker -c "docker exec artex-pg psql -U artex -d postgres -c 'DROP DATABASE IF EXISTS artex WITH (FORCE)'"
sg docker -c "docker exec artex-pg psql -U artex -d postgres -c 'CREATE DATABASE artex'"

# jwt.key 는 남겨도 되지만, 비밀번호가 사라지므로 토큰도 무의미하다. 같이 치운다.
rm -f data/jwt.key jwt.key 2>/dev/null || true

echo '[*] 재기동 (스키마 + 한국어 시드 생성)'
# start.sh 는 env 파일을 읽지 않는다. 여기서 export 해야 LLM 설정이 자식에게 간다 —
# 빠뜨리면 기동 로그에 "no LLM provider configured" 가 뜨고 엔진이 멈춰 있는다.
if [ -f kartex.env ]; then
	set -a; . ./kartex.env; set +a
fi
nohup ./start.sh -addr :8787 -proxy :8788 > artex.log 2>&1 &

for i in $(seq 1 60); do
	if curl -sf -o /dev/null http://127.0.0.1:8787/api/health; then break; fi
	sleep 1
done

echo '[*] 시드 확인'
sg docker -c "docker exec artex-pg psql -U artex -d artex -c \"SELECT name FROM intercept_rules ORDER BY id LIMIT 5\""
sg docker -c "docker exec artex-pg psql -U artex -d artex -c \"SELECT key, name FROM agents ORDER BY id\""

echo
echo "[+] 완료 — http://$(hostname -I 2>/dev/null | awk '{print $1}'):8787/setup 에서 관리자 비밀번호를 다시 설정하세요"
