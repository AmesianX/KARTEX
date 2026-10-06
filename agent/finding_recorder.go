package agent

import (
	"context"

	"github.com/Autumn-27/artex/db"
)

// FindingRecorder is injected by the host; agents never synthesize or copy
// evidence bodies themselves. Its implementation owns the atomic write.
type FindingRecorder interface {
	Record(context.Context, db.RecordFindingInput, []db.TrafficRef) (*db.RecordedFinding, error)
}

// Tool-use guidance is appended without replacing the user's editable prompt.
// It does not require capture or claim that unavailable traffic tools exist.
const findingTrafficGuidance = "\n\n**취약점 트래픽 증거(선택)**: report_finding 으로 취약점을 보고할 때, 이미 확인해 취약점 결론을 뒷받침한다고 판단한 HTTP 요청/응답이 있으면 traffic_refs 에 재현 순서대로 실제 ID 를 연결할 수 있다. 도메인과 시간은 후보 선별용일 뿐이며 연관을 단정하지 않는다. TCP 등 HTTP 가 아닌 취약점, 수집되지 않았거나 정확히 일치하는 것이 없을 때는 생략하거나 [] 를 넘기고, evidence 에 명령 출력·로그 등 다른 검증 가능한 증거를 남기며 연결하지 않은 이유를 밝히는 것이 좋다. ID 를 추측하지 않고, 패킷을 보충하려고 같은 탐지를 반복하지도 않는다."

func (t *ToolSet) SetFindingRecorder(r FindingRecorder)   { t.findingRecorder = r }
func (w *Worker) SetFindingRecorder(r FindingRecorder)    { w.findingRecorder = r }
func (p *Planner) SetFindingRecorder(r FindingRecorder)   { p.findingRecorder = r }
func (m *MainAgent) SetFindingRecorder(r FindingRecorder) { m.findingRecorder = r }
