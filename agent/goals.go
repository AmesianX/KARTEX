package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/Autumn-27/artex/db"
	"github.com/Autumn-27/norma/agentcore"
	"github.com/Autumn-27/norma/llm"
	acperm "github.com/Autumn-27/norma/permission"
	actool "github.com/Autumn-27/norma/tool"
	"github.com/Autumn-27/norma/transcript"
)

// goalsDefaultTmpl is the built-in EDITABLE body (段 [A]) of the goals-decomposer
// prompt, seeded into agent_prompts. No template vars are used today.
const goalsDefaultTmpl = `너는 침투 테스트 목표 분해기다. 네 책무는 사용자 입력에서 **최종적으로 달성할 결과**를 식별하는 것이며, 공격 단계를 계획하는 것이 아니다.

**1단계(목표를 분해하기 전에 먼저 한다): 동작 제약 추출**
「작업 목표 / 작업 설명」에서 운영자가 [무엇을 해도 되고 무엇을 하면 안 되는 동작]에 대해 명확히 규정한 것을 식별해 set_constraints 로 하나씩 등록한다(설명과 목표에 동작 제약이 없으면 제약 추출을 하지 않아도 된다):
- type=deny: 금지된 동작(예: 「포트를 스캔하지 않는다」 「운영 환경에 쓰기/삭제 작업을 하지 않는다」 「무차별 공격 금지」 「특정 서브도메인은 건드리지 않는다」).
- type=allow: 명확히 허용/한정된 동작 범위(예: 「수동 정찰만 허용」 「특정 도메인만 대상」).
- 제약 ≠ 목표, 제약 ≠ 공격 단계: 제약은 동작 행위의 경계에 대한 규정이다.
- **제약은 [자기 완결적이어야 하고, 구체적인 대상을 고정해 써야] 한다**: 「현재 목표/현재 포트/현재 IP/현재 도메인/본 사이트」 같은 **지시어**를 작업 목표/설명의 **구체적인 값**으로 바꾼다. 제약은 실행 단계의 프롬프트에 따로 주입되므로, 컨텍스트에서 떨어지면 지시어가 무엇을 가리키는지 판단할 수 없다.
  예: 목표가 https://abc.example.net 이면 → 「abc.example.net 만 테스트 허용」이라고 쓰고 「현재 목표만 테스트 허용」이라고 쓰지 않는다. 「대상 포트 443 만 테스트하고 다른 포트는 스캔하지 않는다」라고 쓰고 「현재 포트만 테스트」라고 쓰지 않는다. 원문이 「현재 목표」라고만 했어도 목표 주소가 이미 분명하면 그 주소를 넣는다.
- **목표/설명에 [명시적으로 적히거나 강조된] 제약만 등록하고, 임의로 만드는 것은 금지한다**. 유형이 불확실하면 deny 를 쓴다(더 보수적).
- 목표/설명에 동작 제약이 실제로 전혀 없으면 set_constraints 를 호출하지 **않는다**.
제약 등록을 마친 뒤(있는 경우) 아래의 목표 분해를 진행한다.

**목표 = 최종 산출물/검증 가능한 결과**

**목표가 아닌 것(하위 목표로 넣는 것을 금지한다)**:
- 정보 수집, 정찰, 엔드포인트 스캔
- 취약점 분석과 검증 과정
- 공격 단계, 공략 수단
- 결과 검증 단계

**분해 원칙**:
- 사용자가 설명한 최종 목표가 하나뿐이면 → 하나를 출력한다
- **서로 독립적인** 최종 산출물이 여러 개 있으면 → 각각 나열한다
- 명확한 취약점 분류에 대응할 수 있으면 vulnclass 를 표기한다. 정보 수집/비즈니스 로직 계열 목표는 비워 둔다
- 사용자가 언급하지 않은 목표를 임의로 만드는 것은 금지한다

set_goals 를 호출해 결과를 제출한다.`

// goalsScopeTail is the code-owned tail appended after the editable goals body
// WHEN an asset store + task context are available. It teaches the decomposer to
// also lift the explicit asset scope out of the goal/description and register it
// via add_task_scope. Kept in code (not the DB-editable body) so it always applies
// on released DBs and can't be edited away — same pattern as the trafficTool tail.
const goalsScopeTail = `

**추가 책무: 테스트 자산 범위 등록**
목표 분해 외에, 「작업 목표 / 작업 설명」에서 **명시적으로 주어진 테스트 자산 범위**를 식별해 add_task_scope 로 등록한다(본 작업의 권한 경계이며 자산 테스트 커버리지의 분모다). **최소 범위 원칙: 사용자가 명확히 지목한 그 하나의 대상만 등록하고, 절대 임의로 넓히지 않는다.**
- 목표가 URL 이거나 호스트명이 포함된 주소라면(예: https://xxx.example.com/path, app.example.com) → 그 **전체 호스트명**을 취해 kind=subdomain, value=전체 호스트명 으로 한다.
  예: 목표 https://a1b2c3.lab.example.net/path → kind=subdomain, value=a1b2c3.lab.example.net(**example.net 이 아니다**).
  서브도메인이 있는 호스트명을 루트 도메인으로 줄이는 것은 **금지**한다 —— xxx.example.com 을 보고 example.com 전체를 등록하면 범위가 사용자 목표를 넘어서게 되어 최소 범위 원칙에 어긋난다.
- 사용자가 준 것이 **단독 루트 도메인이고 서브도메인이 전혀 없는** 경우(예: example.com 이라고만 적은 경우)이거나, 「사이트 전체 / 모든 서브도메인 / 전 도메인」 이라고 명확히 말한 경우에만 → kind=root_domain, value=example.com 을 쓴다.
- 순수 IP 나 네트워크 대역 → kind=ip / cidr, value=IP 또는 CIDR.
- 회사 범위(company)는 등록하지 **않는다** —— 작업이 막 생성된 시점에는 자산 시스템에 그 회사가 아직 없어 등록되지 않는다. 회사 단위 범위는 이후 plan 단계에서 처리한다.
그 밖의 규칙:
- **목표/설명에 명시적으로 적힌** 범위만 등록한다. 언급되지 않은 도메인/IP 를 임의로 만들거나 추론하는 것은 금지한다.
- reason 에는 어느 문장을 근거로 했는지 간단히 적어 감사에 대비한다.
- 목표/설명에 명확한 자산 범위가 전혀 없으면 add_task_scope 를 호출하지 **않는다**.
먼저 add_task_scope 로 범위를 등록하고(있는 경우), 그다음 set_goals 로 목표를 제출한다.`

// GoalSpec is one decomposed objective.
type GoalSpec struct {
	Text      string `json:"text"`
	VulnClass string `json:"vulnclass,omitempty"`
}

// DecomposeGoals asks the LLM to break a pentest task goal into discrete,
// independently-verifiable objectives (each becomes a goal node). Returns nil if
// no provider is configured or the call yields nothing — the caller then falls
// back to a rule-based split so goal nodes always exist.
//
// prov is supplied by the caller (rather than built here from a Config) so goal
// decomposition rides the SAME provider instance as the rest of the engine — it
// shares the rate limiter, gets recorded by llmrec, and participates in LLM
// failover instead of quietly bypassing all three.
//
// desc is the task's free-text description (背景：靶标范围/flag 数量/交战说明等).
// It is fed alongside the goal so the decomposer no longer splits blind — the
// prompt still forbids inventing anything the two texts don't state.
//
// emit, when non-nil, receives every LLM step (thinking/tool_use/result) with
// Worker="planner" so the round-0 goal-decomposition activity is visible in the UI.
//
// as + taskID, when non-nil/positive, wire the add_task_scope tool so the
// decomposer can register the explicit asset scope it extracts from the goal.
//
// ts is the task's exploration store: set_goals writes the decomposed goal nodes
// straight into it (the same managed tool the main agent uses to add goals at
// runtime). The returned specs are read back from the store so callers can emit
// per-goal activity and detect the "LLM produced nothing" case for their fallback.
func DecomposeGoals(ctx context.Context, prov llm.Provider, dataDir, goalText, desc string, as *db.AssetStore, ts *db.ExplorationStore, taskID int64, emit func(db.Activity)) []GoalSpec {
	if prov == nil {
		return nil
	}
	return DecomposeGoalsWithProvider(ctx, prov, dataDir, goalText, desc, as, ts, taskID, false, 0, emit)
}

// DecomposeGoalsWithProvider is the task-runtime variant used when a task has an
// ordered provider chain. It preserves the same tools and write behavior while
// letting the caller own provider selection/failover. maxTokens is the profile's
// per-reply output cap (0 = send none).
func DecomposeGoalsWithProvider(ctx context.Context, prov llm.Provider, dataDir, goalText, desc string, as *db.AssetStore, ts *db.ExplorationStore, taskID int64, nonStreaming bool, maxTokens int, emit func(db.Activity)) []GoalSpec {
	if prov == nil {
		return nil
	}
	// 目标拆解是一次性调用：不挂 transcript store，所以 agentcore 不会往 ctx 上挂
	// session id（它只在有 writer 时才挂，见 agentcore.Prompt）。而按 session-id 头
	// 做提示缓存/粘性路由的网关（opencode zen 缺 x-opencode-session 直接 400
	// MissingSessionID）读的就是 ctx 上这个值——不补就是「对话正常、拆解 400」。
	// 显式挂一个稳定 id：同一探索的拆解请求共享它（利于命中缓存），且命名与
	// planner/worker 不冲突，能被 llmrec.parseSession 正确归因。
	if ts != nil {
		ctx = transcript.WithSessionID(ctx, fmt.Sprintf("exp%d-goals", ts.ID()))
	}
	// worker="goals" tags the goal nodes' provenance; ts/taskID let set_goals link
	// each goal under the task root. This is the catalog's real set_goals tool, so a
	// web-edited description/schema on it applies here too.
	tsx := &ToolSet{as: as, ts: ts, taskID: taskID, worker: "goals"}
	// Description rides in the user message (same channel as the goal), NOT via the
	// {{.EngagementDescription}} template var — else a prompt that references the var
	// would inject the description twice. System prompt stays pure static instructions.
	sys := renderSystem("goals", goalsDefaultTmpl, GoalsVars{DataDir: dataDir, Now: nowStr()})
	// set_constraints 始终可用(不依赖 asset store):正文已含「先抽操作约束再拆目标」这步
	// (可在 agent 编辑页改措辞),这里只需接上工具。
	tools := []actool.CoreTool{tsx.setGoals(), tsx.setConstraints()}
	// Wire add_task_scope only when we have a real asset store + task to write to.
	// The scope-extraction tail is appended in lockstep so the prompt never asks for
	// a tool that isn't present.
	if as != nil && taskID > 0 {
		tools = append(tools, tsx.addTaskScope())
		sys += goalsScopeTail
	}
	userMsg := "작업 목표:\n" + goalText
	if d := strings.TrimSpace(desc); d != "" {
		userMsg += "\n\n작업 설명(배경 정보. 대상 범위/flag 개수/교전 규칙이 들어 있을 수 있다. 참고용이며 거기 언급되지 않은 내용을 임의로 만들지 않는다):\n" + d
	}
	// Use captureRun so every LLM step is emitted as an activity record (visible in
	// the plan tab under the round-0 marker). Falls back gracefully when emit is nil.
	captureEmit := func(r db.Activity) {
		if emit != nil {
			r.Worker = "planner"
			emit(r)
		}
	}
	captureRun(ctx, agentcore.Options{
		Provider:               prov,
		SystemPrompt:           []string{sys},
		Tools:                  tools,
		PermissionMode:         acperm.ModeBypass,
		DisableBackgroundTasks: true,
		// 3 步(抽约束 → 登记范围 → 拆目标)各需一次工具调用,给足回合避免收尾前漏调 set_goals。
		MaxTurns:     8,
		NonStreaming: nonStreaming, // 该 profile 选非流式时走 Provider.Complete
		MaxTokens:    maxTokens,    // 0 = 不发上限,由服务端默认值决定
	}, userMsg, captureEmit)
	// set_goals persisted the goals directly; read them back so the caller sees what
	// was written (empty slice ⇒ the LLM produced nothing ⇒ caller falls back).
	if ts == nil {
		return nil
	}
	nodes, _ := ts.ListByKind(db.KindGoal, 10000)
	var out []GoalSpec
	for _, n := range nodes {
		var p struct {
			Text      string `json:"text"`
			VulnClass string `json:"vulnclass"`
		}
		_ = json.Unmarshal(n.Payload, &p)
		if strings.TrimSpace(p.Text) != "" {
			out = append(out, GoalSpec{Text: p.Text, VulnClass: p.VulnClass})
		}
	}
	return out
}
