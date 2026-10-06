package agent

import (
	"strings"

	"github.com/Autumn-27/artex/db"
)

// constraintBlock renders this task's operation constraints (task_constraints) as a
// high-priority block appended to the planner/worker system prompt. allow/deny are
// grouped; empty string when there are no constraints (or ts is nil). The framing
// deliberately puts these ABOVE the exploration/expansion heuristics so a declared
// boundary wins the tug-of-war against "chase another entry surface".
func constraintBlock(ts *db.ExplorationStore) string {
	if ts == nil {
		return ""
	}
	rows, err := ts.ListConstraints()
	if err != nil || len(rows) == 0 {
		return ""
	}
	var allow, deny []string
	for _, c := range rows {
		text := strings.TrimSpace(c.Text)
		if text == "" {
			continue
		}
		if c.Kind == "allow" {
			allow = append(allow, "- "+text)
		} else {
			deny = append(deny, "- "+text)
		}
	}
	if len(allow) == 0 && len(deny) == 0 {
		return ""
	}
	var b strings.Builder
	b.WriteString("\n\n[동작 제약(최우선. 아래의 모든 탐색/확장 휴리스틱을 압도한다. 의도를 생성할 때마다, 동작을 실행할 때마다 먼저 위반 여부를 자체 점검하고, 위반이면 진행하지 않는다)]:")
	if len(allow) > 0 {
		b.WriteString("\n허용 동작:\n")
		b.WriteString(strings.Join(allow, "\n"))
	}
	if len(deny) > 0 {
		b.WriteString("\n금지 동작:\n")
		b.WriteString(strings.Join(deny, "\n"))
	}
	b.WriteString("\n(제약 밖의 새 목표/새 포트/새 호스트를 발견한 것이 권한 획득을 뜻하지는 않는다. 위의 허용 범위 안에 들지 않으면 out-of-scope 사실로 기록하고 건너뛴다. 그것을 위해 의도를 파생시키거나 동작을 실행하지 않는다.)")
	return b.String()
}
