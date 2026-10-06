#!/usr/bin/env python3
"""manual.json(코드와 섞여 자동 치환에서 제외된 조각) 중 실제 UI 텍스트를 줄 단위로 바꾼다.

사전 기반 자동 치환은 `{expr}` 가 섞인 JSX 조각과 TS 제네릭 오인 구간을 건드리지
않는다. 그 구간에 남은 UI 문자열은 **줄 전체가 정확히 일치할 때만** 교체한다.
`// 完成` 같은 주석 줄은 키에 없으므로 원문 그대로 남는다.
"""
import glob, os

# 리포 루트 = 이 스크립트(i18n-ko/)의 부모. 작업 경로에 묶이지 않게 한다.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LINES = {
 'a.kind !== "usage").length} 条事件': 'a.kind !== "usage").length} 건 이벤트',
 '层级（计数仍已计入上层）。用筛选或过滤框收窄可看到完整层级。':
   '계층입니다(카운트는 이미 상위에 포함됨). 필터나 검색창으로 좁히면 전체 계층을 볼 수 있습니다.',
 '创建深入意图': '심화 의도 생성',
 '0 ? parsedScope.rules.length : ""} 条': '0 ? parsedScope.rules.length : ""} 건',
 '99 ? "99+" : pending} 条新播报 · 回到最新': '99 ? "99+" : pending} 건 새 활동 · 최신으로',
 '} 复制': '} 복사',
 '新建': '새로 만들기',
 '加载更早的 Worker': '이전 Worker 불러오기',
 '暂停': '일시정지',
 '继续': '계속',
 '} 保存': '} 저장',
 '确认归档': '아카이브 확인',
 '永久删除': '영구 삭제',
 '的执行记录与探索链路将被永久删除。': '의 실행 기록과 탐색 경로가 영구 삭제됩니다.',
 '移动': '이동',
 '创建分类「': '분류 생성 「',
 '上传文件': '파일 업로드',
 '仅 LLM 出站请求走此代理，支持 http/https/socks5，可带账号密码（如':
   'LLM 아웃바운드 요청만 이 프록시를 거칩니다. http/https/socks5 를 지원하고 계정/비밀번호를 포함할 수 있습니다(예:',
 'socks5://user:pass@host:port，密码含特殊字符需 URL 编码）；留空表示不使用代理（直连）。':
   'socks5://user:pass@host:port, 비밀번호에 특수문자가 있으면 URL 인코딩이 필요). 비우면 프록시를 쓰지 않습니다(직접 연결).',
 '免费版额度约 2,000 次/月。前往 https://brave.com/search/api/ 获取 Key。':
   '무료 버전 한도는 월 약 2,000회입니다. https://brave.com/search/api/ 에서 Key 를 받으세요.',
 '为该 Agent 绑定固定 LLM 配置（点「保存配置」生效）。优先级：Agent 绑定 &gt; 任务/会话指定 &gt; 全局激活。':
   '이 Agent 에 고정 LLM 설정을 연결합니다(「설정 저장」을 눌러야 적용). 우선순위: Agent 연결 &gt; 작업/세션 지정 &gt; 전역 활성.',
 '复测 Agent': '재검증 Agent',
 '将读取原证据和测试约束，在独立会话中执行针对性验证。复测成功完成且确认修复后，漏洞状态自动改为「已修复」，其他结论保留原状态。':
   '원본 증거와 테스트 제약을 읽어 독립 세션에서 표적 검증을 수행합니다. 재검증이 성공적으로 끝나고 수정이 확인되면 취약점 상태가 자동으로 「수정됨」으로 바뀌며, 다른 결론은 기존 상태를 유지합니다.',
 # 아래는 실제 소스 줄 그대로가 키다. `{expr}` 가 붙어 있어 조각 기준 키와는 다르다.
 '{activity.filter((a) => a.kind !== "usage").length} 条事件':
   '{activity.filter((a) => a.kind !== "usage").length} 건 이벤트',
 '登记 {parsedScope.rules.length > 0 ? parsedScope.rules.length : ""} 条':
   '등록 {parsedScope.rules.length > 0 ? parsedScope.rules.length : ""} 건',
 '{pending > 99 ? "99+" : pending} 条新播报 · 回到最新':
   '{pending > 99 ? "99+" : pending} 건 새 활동 · 최신으로',
 '{copied ? <CheckIcon /> : <CopyIcon />} 复制':
   '{copied ? <CheckIcon /> : <CopyIcon />} 복사',
 '{saving && <Loader2Icon className="animate-spin" />} 保存':
   '{saving && <Loader2Icon className="animate-spin" />} 저장',
 '创建分类「{trimmed}」': '분류 생성 「{trimmed}」',
 '保存': '저장',
 '暂停 {pausableTaskIDs.length}': '일시정지 {pausableTaskIDs.length}',
 '继续 {resumableTaskIDs.length}': '계속 {resumableTaskIDs.length}',
 'return `${preview.join(" · ")}${rows.length > preview.length ? ` · 另 ${rows.length - preview.length} 条` : ""}`;':
   'return `${preview.join(" · ")}${rows.length > preview.length ? ` · 외 ${rows.length - preview.length} 건` : ""}`;',
}


def main():
    files = sorted(glob.glob(os.path.join(ROOT, 'web/src/**/*.ts'), recursive=True) +
                   glob.glob(os.path.join(ROOT, 'web/src/**/*.tsx'), recursive=True))
    hits, changed = 0, 0
    for f in files:
        if '/src/lib/mock/' in f:
            continue
        lines = open(f, encoding='utf-8').read().split('\n')
        out, touched = [], False
        for ln in lines:
            s = ln.strip()
            if s in LINES:
                out.append(ln.replace(s, LINES[s]))
                hits += 1
                touched = True
            else:
                out.append(ln)
        if touched:
            changed += 1
            open(f, 'w', encoding='utf-8').write('\n'.join(out))
    print(f'줄 교체 {hits}건 / 파일 {changed}개')


if __name__ == '__main__':
    main()
