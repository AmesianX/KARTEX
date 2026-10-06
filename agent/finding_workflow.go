package agent

import (
	"encoding/json"
	"fmt"

	"github.com/Autumn-27/artex/db"
	actool "github.com/Autumn-27/norma/tool"
)

const findingIDGuidance = "\n\n**취약점 번호 규약**: finding_id 는 독립 취약점 레코드 ID 이고, finding_node_id 는 탐색 노드 ID 다. list_findings / list_task_findings / node_detail / get_task_node_detail 의 id 는 탐색 노드 ID 로 유지되므로, 같은 반환값의 finding_id 에서 독립 번호를 읽어야 한다. get_finding_traffic / bind_finding_traffic 은 독립 finding_id 를 쓴다. 구 update_finding_report 의 finding_id 파라미터에는 여전히 finding_node_id 를 넘긴다. report_finding 첫 줄의 숫자를 증거 도구에 쓰지 않으며, 번호 오류를 만난 뒤 다른 숫자를 추측하지도 않는다."

// The server supplies the persisted setting. A missing setting/host is off.
// Consulted at assembly and again on writes so an already-running session
// cannot keep binding after the user switches the feature off.
var FindingTrafficBindingEnabled func() bool

func findingTrafficBindingEnabled() bool {
	return FindingTrafficBindingEnabled != nil && FindingTrafficBindingEnabled()
}

// Applied after ToolResolve: user descriptions and prompts remain intact, while
// all actual reporters (including Planner and custom chat agents) see the same
// API contract. Disabled/unbound tools are never reintroduced here.
func findingWorkflowTools(agentKey string, tools []actool.CoreTool) ([]actool.CoreTool, string) {
	if !findingTrafficBindingEnabled() {
		out := make([]actool.CoreTool, 0, len(tools))
		for _, tool := range tools {
			if tool.Name() == "bind_finding_traffic" {
				continue
			}
			if agentKey == "reporter" && (tool.Name() == "traffic_search" || tool.Name() == "traffic_get" || tool.Name() == "traffic_blob") {
				continue
			}
			switch tool.Name() {
			case "report_finding", "add_hint", "add_task_hint":
				// Work on a copy: toggling back on must restore the original schema.
				raw, _ := json.Marshal(tool.InputSchema())
				var schema map[string]any
				if json.Unmarshal(raw, &schema) == nil {
					stripTrafficParameters(schema)
					tool = DecorateTool(tool, tool.Description(), schema)
				}
			}
			out = append(out, tool)
		}
		return out, ""
	}
	out := append([]actool.CoreTool(nil), tools...)
	has := map[string]bool{}
	for i, tool := range out {
		has[tool.Name()] = true
		note := ""
		switch tool.Name() {
		case "report_finding":
			note = "\n기본적으로 보고 Agent 가 리포트를 작성하기 전에 트래픽을 확인하고 연결한다. 보고자는 evidence 에 검증 명령, 핵심 출력, 이미 가진 실제 트래픽 ID 와 그 용도를 남겨, 보고 Agent 가 실행 기록과 대조해 확인할 수 있게 한다. 연결을 위해 추가로 패킷을 찾을 필요는 없다. 명시적 즉시 연결도 지원한다: traffic_refs 또는 evidence_hint_id 로 검증된 참조를 제출할 수 있고, 후자는 본 작업에서 지정한 hint 의 구조화된 참조를 읽는다. 어느 하나라도 유효하지 않으면 이번 보고는 전부 실패한다. TCP/패킷 없는 경우에는 이 선택 파라미터들이 필요하지 않다. 반환되는 finding_id 와 finding_node_id 는 각각 독립 레코드와 탐색 노드를 뜻한다."
		case "add_hint", "add_task_hint":
			note = "\n확인된 취약점을 인계할 때는 해당 힌트의 traffic_refs 에 검증된 트래픽의 ID, 용도, 설명, 순서를 유지한다(한 건은 최상위에, 일괄은 해당 hints 요소에 넣는다). 그리고 text 에 그것이 증명하는 구체적인 취약점을 적는다. 호출자는 텍스트만 인계하고 기존 트래픽 참조를 버릴 수 없다. 검증되지 않은 후보는 증거로 전달할 수 없다."
		case "get_finding_traffic", "bind_finding_traffic", "list_findings", "list_task_findings", "node_detail", "get_task_node_detail", "update_finding_report":
			note = findingIDGuidance
		}
		if note != "" {
			out[i] = DecorateTool(tool, tool.Description()+note, tool.InputSchema())
		}
	}
	guidance := ""
	if has["report_finding"] || has["add_task_hint"] || has["add_hint"] {
		guidance = "\n\n**트래픽 증거 인계(선택)**: 자동 연결은 기본적으로 보고 Agent 가 취약점이 저장된 뒤 리포트 작성 전에 수행한다. 보고자는 evidence 에 검증 명령, 핵심 출력, 이미 가진 실제 트래픽 ID 와 그 용도를 남기고, 작업 중에는 intent_id 를 함께 넘겨 보고 Agent 가 추적할 수 있게 한다. 연결을 위해 추가로 패킷을 찾을 필요는 없다. Auto / Planner 가 대신 보고할 때 실행자가 이미 가진 참조를 버리지 않는다. add_hint / add_task_hint 로 traffic_refs 를 인계할 수 있고, 명시적 즉시 연결은 여전히 report_finding 의 traffic_refs / evidence_hint_id 와 호환된다. TCP 이거나 패킷이 없을 때도 정상 등록하며, ID 를 추측하거나 패킷을 보충하려고 같은 탐지를 반복하지 않는다."
		if has["add_task_hint"] && !has["add_hint"] {
			guidance += "\n플랫폼 대화에 작업 컨텍스트가 없으면 report_finding 을 직접 호출하지 않는다. add_task_hint 로 해당 작업에 인계해 작업 Agent 가 등록하게 하고, list_task_findings 로 결과를 확인한다."
		}
		if has["prove_goal"] || has["goal_met"] {
			guidance += "\n목표 완료를 판정하기 전에 이번에 확보한 증거의 보고/인계를 먼저 끝낸다. 증거 인계가 끝나지 않았는데 텍스트 취약점이 등록됐다는 이유만으로 작업을 끝내거나 Worker 를 취소하지 않는다. 패킷이 없으면 기다리거나 억지로 캡처할 필요는 없다."
		}
	}
	if has["update_finding_report"] && has["bind_finding_traffic"] && has["get_finding_traffic"] {
		guidance += "\n\n**리포트 작성 전 트래픽 자동 연결(활성화됨)**: 너는 이번에 촉발된 취약점의 트래픽을 확인하고 연결한 뒤 리포트를 작성한다. 먼저 report_finding 이 반환한 JSON 또는 get_task_node_detail / list_task_findings 에서 명확한 finding_id 와 finding_node_id 를 얻는다. 취약점 상세, 해당 의도의 실행 기록, 기존 증거 목록을 읽고, 보고자가 인계한 실제 ID 를 우선 사용한다. 이번 검증이 HTTP 이고 트래픽 도구를 쓸 수 있다면 traffic_search 로 후보를 선별하고, traffic_get 으로 요청/응답이 실제로 그 취약점을 뒷받침하는지 하나씩 확인한다. 도메인과 시간은 선별에만 쓰며 귀속을 증명하지 않는다. 확인된 증거를 재현 순서대로 bind_finding_traffic(finding_id, traffic_refs) 으로 연결하고, baseline / proof / verification / supporting 을 선택해 용도를 밝힌다. 이번 취약점만 다루며, 취약점을 중복 생성하거나 대상을 다시 탐지하지 않는다. 연결에 성공하면 get_finding_traffic 을 다시 호출해 최신 version 을 얻고, 필요한 본문을 읽은 뒤 실제로 읽은 version 을 evidence_version 으로 update_finding_report 에 넘긴다(그 finding_id 파라미터에는 여전히 finding_node_id 를 쓴다). 이미 연결된 것을 중복 추가할 필요는 없다. TCP, 미수집, 도구 사용 불가, 정확히 일치하는 것이 없는 경우에는 자동 연결을 건너뛰고 텍스트/명령 증거를 근거로 정상적으로 리포트를 쓰면서 이유를 밝힌다. 트래픽을 채우려고 추측해서는 안 된다. 연결 실패를 성공이라고 주장하지 않고, 기존 증거를 보존하며 리포트에 연결하지 않은 이유를 밝힌다."
	}
	if guidance != "" || has["get_finding_traffic"] || has["update_finding_report"] {
		guidance += findingIDGuidance
	}
	return out, guidance
}

func stripTrafficParameters(schema map[string]any) {
	props, _ := schema["properties"].(map[string]any)
	delete(props, "traffic_refs")
	delete(props, "evidence_hint_id")
	if required, ok := schema["required"].([]any); ok {
		kept := required[:0]
		for _, key := range required {
			if key != "traffic_refs" && key != "evidence_hint_id" {
				kept = append(kept, key)
			}
		}
		schema["required"] = kept
	}
	if hints, ok := props["hints"].(map[string]any); ok {
		if items, ok := hints["items"].(map[string]any); ok {
			stripTrafficParameters(items)
		}
	}
}

// HintTrafficSchema is shared by the task-local and cross-task hint tools.
func HintTrafficSchema() map[string]any {
	return map[string]any{"type": "array", "description": "선택: 이미 확인했고 이 힌트의 구체적인 취약점에 대응하는 트래픽 참조. 순서를 유지한다. 인계 후 report_finding 에 evidence_hint_id 를 넘겨 이 참조들을 함께 전달할 수 있다.", "items": obj(map[string]any{"traffic_id": str("실제 트래픽 ID"), "role": str("baseline / proof / verification / supporting"), "note": str("이 트래픽이 뒷받침하는 결론")}, "traffic_id")}
}

func (t *ToolSet) findingRefsFromHint(hintID int64, explicit []db.TrafficRef) ([]db.TrafficRef, error) {
	if hintID <= 0 {
		return db.NormalizeTrafficRefs(explicit)
	}
	n, err := t.ts.GetNode(hintID) // local store only: inherited hints cannot supply evidence
	if err != nil {
		return nil, err
	}
	if n == nil || n.Kind != db.KindHint {
		return nil, fmt.Errorf("evidence_hint_id=%d 는 본 작업의 힌트 노드여야 한다(상속된 힌트는 연결에 직접 쓸 수 없다)", hintID)
	}
	var payload struct {
		Refs []db.TrafficRef `json:"traffic_refs"`
	}
	if err := json.Unmarshal(n.Payload, &payload); err != nil {
		return nil, err
	}
	return db.NormalizeTrafficRefs(append(append([]db.TrafficRef{}, explicit...), payload.Refs...))
}
