#!/usr/bin/env bash
# KARTEX 재시작.
#
#   ./RESTART_ALL.sh            종료 → env 적용 → 기동 → 헬스체크
#   ./RESTART_ALL.sh --build    위 + 한국어 적용·재빌드(i18n-ko/apply-ko.sh)
#   ./RESTART_ALL.sh --status   기동하지 않고 상태만 출력
#
# 데이터를 지우는 옵션은 **의도적으로 넣지 않았다.** DB 재시드는
# i18n-ko/reseed-db.sh 에만 있다. 재시작과 초기화가 한 스크립트에 섞여 있으면
# 플래그 하나 잘못 쳐서 운영 데이터가 날아간다.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ADDR_PORT=8787
PROXY_PORT=8788
ENV_FILE=kartex.env

info(){ printf '\033[36m[*]\033[0m %s\n' "$*"; }
ok(){   printf '\033[32m[+]\033[0m %s\n' "$*"; }
warn(){ printf '\033[33m[!]\033[0m %s\n' "$*"; }
die(){  printf '\033[31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# ── 상태 출력 ────────────────────────────────────────────
show_status(){
	echo '──────────────────────────────────────────'
	local pid; pid=$(lsof -ti:$ADDR_PORT 2>/dev/null | head -1)
	if [ -n "$pid" ]; then
		ok "artex    실행 중 (pid $pid, :$ADDR_PORT)"
	else
		printf '\033[31m[x]\033[0m %s\n' "artex    정지 (:$ADDR_PORT 비어있음)"
	fi
	if lsof -ti:$PROXY_PORT >/dev/null 2>&1; then
		ok "기록 프록시 :$PROXY_PORT"
	else
		warn "기록 프록시 :$PROXY_PORT 안 떠 있음"
	fi
	local h; h=$(curl -sf -m 5 "http://127.0.0.1:$ADDR_PORT/api/health" 2>/dev/null)
	[ -n "$h" ] && ok "health   $h"
	local a; a=$(curl -sf -m 5 "http://127.0.0.1:$ADDR_PORT/api/auth/status" 2>/dev/null)
	case "$a" in
		*'"initialized":false'*) warn "관리자 비밀번호 미설정 — /setup 에서 먼저 설정해야 한다" ;;
		*'"initialized":true'*)  ok  "관리자 비밀번호 설정됨" ;;
	esac
	# LLM 은 로그에만 찍힌다. 안 붙어 있으면 엔진이 조용히 멈춰 있으므로 꼭 본다.
	local llm; llm=$(grep -a '\[engine\].*LLM\|no LLM provider' artex.log 2>/dev/null | tail -1)
	if [ -n "$llm" ]; then
		case "$llm" in
			*'no LLM provider'*) printf '\033[31m[x]\033[0m %s\n' "LLM      미설정 — 엔진이 멈춰 있다 ($ENV_FILE 확인)" ;;
			*) ok "LLM      ${llm#*\[engine\] }" ;;
		esac
	fi
	echo '──────────────────────────────────────────'
	echo "  콘솔  http://$(hostname -I 2>/dev/null | awk '{print $1}'):$ADDR_PORT"
	echo "  로그  tail -f $(pwd)/artex.log"
}

[ "${1:-}" = --status ] && { show_status; exit 0; }

# ── 전제 조건 ────────────────────────────────────────────
[ -x ./artex ]      || die "./artex 가 없다 — ./RESTART_ALL.sh --build 로 먼저 빌드하라"
[ -f ./start.sh ]   || die './start.sh 가 없다'
[ -f ./config.json ]|| die './config.json 이 없다 (DB 접속 정보)'

# Postgres 컨테이너. --restart unless-stopped 라 보통 떠 있지만, 호스트를 재부팅하고
# docker 가 늦게 올라온 경우 등을 대비해 확인하고 필요하면 올린다.
if ! sg docker -c "docker ps --format '{{.Names}}'" 2>/dev/null | grep -qx artex-pg; then
	warn 'artex-pg 컨테이너가 안 떠 있다 — 기동 시도'
	sg docker -c 'docker start artex-pg' >/dev/null 2>&1 || die 'artex-pg 기동 실패'
	for _ in $(seq 1 30); do
		sg docker -c 'docker exec artex-pg pg_isready -U artex -d artex' >/dev/null 2>&1 && break
		sleep 1
	done
fi
sg docker -c 'docker exec artex-pg pg_isready -U artex -d artex' >/dev/null 2>&1 \
	|| die 'Postgres 가 응답하지 않는다'
ok 'Postgres 정상'

# ── 선택: 한국어 적용 + 재빌드 ──────────────────────────
if [ "${1:-}" = --build ]; then
	info '한국어 적용 + 빌드 (i18n-ko/apply-ko.sh)'
	./i18n-ko/apply-ko.sh || die '빌드/검증 실패 — 위 출력을 확인하라'
fi

# ── 종료 ────────────────────────────────────────────────
# start.sh 는 artex 가 0 이나 SIGTERM 이 아닌 이유로 죽으면 **다시 올린다**.
# 그래서 artex 를 직접 죽이면 래퍼가 크래시로 보고 재기동해 버린다. 래퍼에
# TERM 을 보내야 한다 — 래퍼가 그걸 artex 로 전달하고 정상 종료한다.
#
# 래퍼는 pkill -f 로 찾지 않는다. `-f` 는 **이 스크립트 자신의 명령줄**까지
# 매칭해서 스스로를 죽인 적이 있다. 포트를 듣는 pid 의 부모를 /proc 로 확인한다.
pid=$(lsof -ti:$ADDR_PORT 2>/dev/null | head -1)
if [ -n "$pid" ]; then
	target=$pid
	ppid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
	if [ -n "${ppid:-}" ] && [ "$ppid" -gt 1 ] 2>/dev/null; then
		if tr '\0' ' ' < "/proc/$ppid/cmdline" 2>/dev/null | grep -q 'start\.sh'; then
			target=$ppid
			info "start.sh 래퍼(pid $ppid)에 TERM — artex(pid $pid) 로 전달된다"
		fi
	fi
	[ "$target" = "$pid" ] && info "artex(pid $pid)에 TERM"
	kill -TERM "$target" 2>/dev/null || true
	for _ in $(seq 1 20); do
		lsof -ti:$ADDR_PORT >/dev/null 2>&1 || break
		sleep 1
	done
	if lsof -ti:$ADDR_PORT >/dev/null 2>&1; then
		warn '정상 종료 안 됨 — KILL'
		lsof -ti:$ADDR_PORT 2>/dev/null | xargs -r kill -9 2>/dev/null || true
		sleep 2
	fi
	ok '기존 프로세스 종료'
else
	info '실행 중인 artex 없음'
fi
# 프록시 포트가 남아 있으면(래퍼 없이 떴던 경우) 같이 정리한다.
lsof -ti:$PROXY_PORT 2>/dev/null | xargs -r kill -9 2>/dev/null || true

# ── 기동 ────────────────────────────────────────────────
# start.sh 는 env 파일을 읽지 않는다(앱도 안 읽는다). 여기서 export 해야 LLM 설정이
# 자식 프로세스까지 간다 — 빠뜨리면 로그에 "no LLM provider configured" 가 뜨고
# 엔진이 조용히 멈춰 있는다. 실제로 그렇게 한 번 당했다.
if [ -f "$ENV_FILE" ]; then
	set -a; . "./$ENV_FILE"; set +a
	ok "$ENV_FILE 적용"
else
	warn "$ENV_FILE 이 없다 — LLM 은 UI(시스템 → LLM)에서 설정해야 한다"
fi

info 'artex 기동'
nohup ./start.sh -addr ":$ADDR_PORT" -proxy ":$PROXY_PORT" > artex.log 2>&1 &
disown 2>/dev/null || true

printf '  응답 대기'
for _ in $(seq 1 60); do
	curl -sf -m 2 -o /dev/null "http://127.0.0.1:$ADDR_PORT/api/health" && { printf ' ✓\n'; break; }
	printf '.'
	sleep 1
done
echo

curl -sf -m 5 -o /dev/null "http://127.0.0.1:$ADDR_PORT/api/health" || {
	printf '\033[31m[x]\033[0m %s\n' '기동 실패 — 로그 마지막 20줄:'
	tail -20 artex.log
	exit 1
}

show_status
