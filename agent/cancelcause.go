package agent

import (
	"context"
	"errors"
	"fmt"
)

// AbortCause names why an agent run's context was cancelled. Every cancellation
// site should attach one so the activity trace can report the real initiator.
type AbortCause struct {
	Code  string
	Short string
	Text  string
}

func (c *AbortCause) Error() string { return c.Text }

func cause(code, short, text string) *AbortCause {
	return &AbortCause{Code: code, Short: short, Text: text}
}

// Causef builds a cause that includes runtime-specific detail.
func Causef(code, short, format string, args ...any) *AbortCause {
	return &AbortCause{Code: code, Short: short, Text: fmt.Sprintf(format, args...)}
}

var (
	// Task-level execution context.
	AbortPausedByUser = cause("paused_by_user", "사용자가 작업을 일시정지했다",
		"사용자가 작업 제어 API(POST /api/tasks/{id}/control, action=pause)로 작업을 일시정지했다. 이번 Planner/Worker 실행은 능동적으로 취소됐다. 실행 중인 의도는 frontier(open)로 되돌아가며, 작업을 재개하면 다시 할당되어 처음부터 실행된다")
	AbortPausedByOrchestrator = cause("paused_by_orchestrator", "오케스트레이션 Agent 가 작업을 일시정지했다",
		"오케스트레이션 Agent 가 pause_task 도구를 호출해 본 작업을 일시정지했다. 이번 Planner/Worker 실행은 능동적으로 취소됐다. 실행 중인 의도는 frontier(open)로 되돌아가며 재개 후 다시 실행된다")
	AbortTaskDeleted = cause("task_deleted", "작업이 삭제됨",
		"작업이 삭제되는 중이다(DELETE /api/tasks/{id}). 삭제 배리어가 이 작업에서 실행 중인 Planner, Worker, 메인 Agent 를 취소했다. 이번 실행 결과는 더 이상 사용되지 않는다")
	AbortPausedOnReload = cause("paused_on_reload", "백엔드가 작업의 일시정지 상태를 복원했다",
		"백엔드 시작 시 데이터베이스에 저장된 상태에 따라 작업 일시정지를 복원했다. 이번 실행은 취소됐다. 정상적인 경우 복원 단계에는 실행 중인 Agent 가 없다")
	AbortGoalMet = cause("goal_met", "계획자가 작업 목표 달성을 판정했다",
		"계획자가 작업 목표 달성을 판정해 작업을 done 으로 바꾸고, 이어서 아직 실행 중인 Worker 를 취소했다. 이 의도들은 실패가 아니라 stopped 로 표시된다")
	AbortSettleDrainTimeout = cause("settle_drain_timeout", "작업 타임아웃 마무리 대기 시간이 소진됐다",
		"작업이 timeout 에 도달한 뒤 실행 중인 Worker 의 정상 마무리를 기다렸지만 90 초 drain 유예로도 부족해 하드 취소를 실행했다. 의도는 exhausted 로 표시되며 마무리 단계에서 이미 기록된 사실과 자산은 보존된다")

	// Per-work context.
	AbortKilledByPlanner = cause("killed_by_planner", "계획자가 이 의도를 종료했다",
		"계획자가 kill_work 를 호출해 이 의도를 능동적으로 종료했다. 보통 방향이 어긋났거나 계속할 가치가 없다는 뜻이다. 의도는 stopped 로 표시되며 자동으로 다시 할당되지 않는다")
	AbortWorkPausedByUser = cause("work_paused_by_user", "사용자가 이 Worker 의도를 일시정지했다",
		"사용자가 실행 중인 Worker 를 일시정지했다. 이번 호출은 취소되고 의도는 paused 로 바뀐다. 이미 등록된 의도, 사실, 취약점, 활동 기록은 모두 보존되며 재개 후 처음부터 다시 실행된다")
	AbortWorkCancelledByUser = cause("work_cancelled_by_user", "사용자가 이 Worker 의도를 삭제했다",
		"사용자가 실행 중인 Worker 를 삭제했다. 이번 호출은 취소된다. Worker 가 쓰기 구간을 벗어난 뒤 서버는 사용자가 선택한 삭제 모드로 이 의도를 처리한다 —— 가짜 삭제는 삭제됨으로만 표시하고 모든 산출물을 보존하며, 진짜 삭제는 이 의도와 이 의도만이 뒷받침하는 하위 노드를 연쇄 제거한다")
	AbortWorkFinished = cause("work_finished", "Worker 가 정상 종료되어 context 를 해제했다",
		"Worker 가 정상 종료되어 엔진이 detachWork 에서 그 context 자원을 해제했다. 실행 중단이 아니다. 중단 메시지에 이것이 나타나면 취소와 종료 이벤트가 경합한 것이다")
	AbortPausedRaceGuard = cause("paused_race_guard", "작업 일시정지 중에는 새 실행을 시작하지 않는다",
		"작업이 일시정지 상태일 때 엔진은 새 실행 context 발급을 거부한다. claim 과 일시정지 사이의 경합으로 Worker 가 계속 시작되는 것을 막기 위함이다. 이미 할당된 의도는 frontier 로 되돌아간다")

	// Main Agent and standalone conversation contexts.
	AbortChatStoppedByUser = cause("chat_stopped_by_user", "사용자가 이번 대화를 중지했다",
		"사용자가 중지를 눌러 이번 라운드의 메인 Agent 또는 세션 Agent 실행을 능동적으로 중단했다. 이미 생성된 활동 기록은 보존되며 다음 메시지를 계속 보낼 수 있다")
	AbortChatPausedWithTask = cause("chat_paused_with_task", "작업이 일시정지되어 메인 Agent 대화가 중단됐다",
		"사용자가 작업을 일시정지할 때 실행 중인 메인 Agent 대화도 함께 취소됐다. 이미 생성된 활동 기록은 보존된다. 작업을 재개해도 이번 라운드 메시지는 자동으로 재생되지 않는다")
	AbortChatTurnFinished = cause("chat_turn_finished", "이번 대화가 정상 종료되어 context 를 해제했다",
		"이번 대화는 정상 종료됐고 서버가 해당 라운드의 context 자원을 해제하는 중이다. 실행 중단이 아니다. 중단 메시지에 이것이 나타나면 취소와 종료 이벤트가 경합한 것이다")

	// Process-level and per-run hard backstop.
	AbortShutdown = cause("shutdown", "백엔드 프로세스가 종료 중이다",
		"백엔드 프로세스가 SIGINT 또는 SIGTERM 을 받아 재시작·업데이트·종료 중이다. 실행 중인 모든 Agent 가 취소된다. 재시작 후 남은 running 의도는 open 으로 초기화되어 다시 실행된다")
	AbortRunHardTimeout = cause("run_hard_timeout", "단일 실행의 하드 타임아웃 안전장치가 발동했다",
		"단일 실행이 소프트 월클록 예산과 추가 유예를 넘겼다. 모델 요청이나 어떤 도구가 오래 반환하지 않아 정상적인 턴 경계 마무리를 실행할 수 없었다는 뜻이다. 중단 전 마지막으로 반환되지 않은 도구 호출을 중점적으로 확인한다")
)

// AbortReason resolves the named cause attached to a cancelled run context.
func AbortReason(ctx context.Context) (code, short, text string, ok bool) {
	c := context.Cause(ctx)
	if c == nil {
		return "", "", "", false
	}
	var ac *AbortCause
	if errors.As(c, &ac) {
		return ac.Code, ac.Short, ac.Text, true
	}
	switch {
	case errors.Is(c, context.DeadlineExceeded):
		return "deadline_exceeded", "상위 context 가 deadline 에 도달했다",
			"상위 context 가 deadline 에 도달했지만 설정 측이 WithTimeoutCause 로 명시적 원인을 붙이지 않았다: " + c.Error(), true
	case errors.Is(c, context.Canceled):
		return "canceled_no_cause", "취소 측이 명시적 원인을 붙이지 않았다",
			"상위 context 가 취소됐지만 취소 측이 context.WithCancelCause 로 명시적 원인을 붙이지 않았다. agent/cancelcause.go 에 원인을 등록하고 그 취소 지점에 연결한다", true
	default:
		return "other", firstLine(c.Error(), 80), c.Error(), true
	}
}
