"use client";

// LLM 重试配置的共用件：五层重试各自的「次数 + 间隔」。
//
// 五层从内到外：建连(SDK) → 空响应(SDK) → 同 provider 安全窗口 → 轮询熔断 → 意图重跑。
// 前三层跟着端点走，所以每个模型配置都能覆盖全局默认；后两层是进程级的，只有全局一份。
//
// 所有输入都遵循同一套「留空 = 不配置」语义，与后端 db.RetryRule 一致：
//   次数   空/0 = 用内置默认 | -1 = 关闭这层重试 | >0 = 用这个次数
//   间隔   空/0 = 用这层原本的指数退避 | >0 = 改用这个固定毫秒间隔

import * as React from "react";

import { Loader2Icon, SaveIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";
import type { LLMRetryOverride, LLMRetryPolicy, LLMRetryRule } from "@/lib/types";

export const ZERO_RULE: LLMRetryRule = { attempts: 0, interval_ms: 0 };
export const ZERO_OVERRIDE: LLMRetryOverride = {
  connect: ZERO_RULE,
  empty: ZERO_RULE,
  stream: ZERO_RULE,
};
const ZERO_POLICY: LLMRetryPolicy = {
  ...ZERO_OVERRIDE,
  breaker: ZERO_RULE,
  intent: ZERO_RULE,
};

type LayerMeta = {
  title: string;
  /** 这层重试发生在哪、由谁执行 */
  where: string;
  /** 什么样的错误会走到这层——具体到状态码，别让人猜 */
  trigger: string;
  /** 长得像但【不】走这层的错误，省得填了没反应还以为是 bug */
  skips?: string;
  desc: string;
  attemptsLabel: string;
  /** 次数留空时的默认值，用于占位符 */
  defAttempts: number;
  /** 间隔留空时的默认策略，用于占位符 */
  defInterval: string;
  /** 次数填 -1 的含义 */
  offHint: string;
};

export const RETRY_LAYERS = {
  connect: {
    title: "연결 재시도",
    where: "SDK · 200을 받기 전까지",
    trigger:
      "연결이 안 되거나 아직 200을 받지 못한 경우: 연결 리셋 / 읽기·쓰기 타임아웃 / DNS 실패 등 네트워크 계층 오류, 그리고 HTTP 408, 429, 500, 502, 503, 504.",
    skips: "그 외 상태 코드(400 / 401 / 403 / 404 / 413 / 422 등)는 확정적 거부여서 재전송해도 같이 실패하므로 바로 올립니다.",
    desc: "같은 요청을 그대로 재전송합니다. 스트림이 일단 시작되면(200을 받은 뒤) 중간에 끊겨도 이 계층이 담당하지 않습니다.",
    attemptsLabel: "재시도 횟수",
    defAttempts: 3,
    defInterval: "0.5s→1s→2s 지수(최대 8s)",
    offHint: "-1 = 재시도 없이 실패를 바로 올림",
  },
  empty: {
    title: "빈 응답 재시도",
    where: "SDK · openai 형식만",
    trigger:
      "HTTP 200이고 finish_reason도 정상 stop인데 응답에 내용 블록이 하나도 없는 경우 — 게이트웨이 빈 프레임, 사고 필드 프레임 유실, 샘플링 끊김이 모두 이렇게 보입니다.",
    skips: "max_tokens로 잘려서 내용이 없는 경우는 제외합니다(출력 상한을 올려 해결해야 하며, 재전송하면 또 같은 벽에 부딪힙니다).",
    desc: "prompt 전체를 재전송하므로 긴 컨텍스트에서는 비쌉니다. 횟수를 크게 주지 마세요.",
    attemptsLabel: "재시도 횟수",
    defAttempts: 2,
    defInterval: "0.5s→1s→2s 지수(최대 8s)",
    offHint: "-1 = 빈 응답을 그대로 반환",
  },
  stream: {
    title: "같은 provider 안전 윈도우 내 재시도",
    where: "이 프로젝트 · 산출물 전달 전까지",
    trigger:
      "스트림이 이미 수립된(200을 받은) 뒤에 생긴 문제: 연결 중단, 공급자 overloaded, 스트림 내 429 / 5xx 오류 이벤트 — 그리고 호출자에게 토큰을 하나도 넘기지 않은 상태.",
    skips:
      "한도 소진(402 / insufficient_quota, 라운드로빈이 설정 교체 담당), 컨텍스트 초과(413 / context length, 압축이 담당), 400 / 401 / 403 / 404 / 422 확정적 거부는 모두 재시도하지 않습니다.",
    desc: "같은 설정에서 같은 요청을 재생합니다. 아직 아무 출력도 전달하지 않았으므로 재생이 모델 출력이나 도구 실행을 중복시키지 않습니다.",
    attemptsLabel: "재시도 횟수",
    defAttempts: 2,
    defInterval: "0.5s→1s 지수(최대 4s)",
    offHint: "-1 = 스트림 끊기면 바로 상위 의도 재실행에 넘김",
  },
  breaker: {
    title: "라운드로빈 차단",
    where: "이 프로젝트 · 프로세스 단위, 전역 하나",
    trigger:
      "일시적 실패(429, 5xx, 네트워크 오류)가 연속 누적되어 임계값에 도달하면 차단합니다. 잔액 부족(402), 키 만료(401 / 403), 모델 없음(404) 같은 확정적 실패는 임계값과 무관하게 첫 번째에 바로 차단합니다.",
    skips: "한 번 성공하면 0으로 초기화되므로, 간헐적으로 불안정한 설정이 누적되어 차단되지는 않습니다.",
    desc: "차단되면 쿨다운에 들어가고, 쿨다운 동안 라운드로빈이 이 설정을 건너뜁니다. 상태는 DB에 저장되어 재시작해도 유지됩니다.",
    attemptsLabel: "연속 실패 몇 회에 차단",
    defAttempts: 3,
    defInterval: "1min→5min→30min 단계",
    offHint: "-1 = 일시적 실패는 절대 차단하지 않음(확정적 실패는 여전히 차단)",
  },
  intent: {
    title: "의도 재실행",
    where: "이 프로젝트 · 프로세스 단위, 전역 하나",
    trigger:
      "앞의 계층들이 모두 막지 못한 경우: worker가 model_error로 끝납니다 — 내부 재시도를 모두 소진했거나, 스트림이 출력을 전달하기 시작한 뒤에 끊긴 경우(그때는 재생이 안전하지 않아 전체를 다시 해야 합니다).",
    skips: "한도 소진은 라운드로빈의 설정 교체가 처리하므로 여기서 재실행하지 않습니다. 작업이 일시정지 / 종료 / 마무리에 들어가면 즉시 자리를 비우고 백오프 시간을 점유하지 않습니다.",
    desc: "의도 전체를 처음부터 다시 실행합니다. 가장 바깥 계층이므로 한 번 재실행하면 내부 계층들의 횟수가 다시 곱해집니다.",
    attemptsLabel: "재실행 횟수",
    defAttempts: 2,
    defInterval: "고정 3s",
    offHint: "-1 = 재실행 없이 해당 의도를 바로 blocked로 판정",
  },
} satisfies Record<string, LayerMeta>;

type LayerKey = keyof typeof RETRY_LAYERS;

/** 毫秒的人话，只用于在输入框旁边回显，免得数零。 */
function humanMs(ms: number) {
  if (!Number.isFinite(ms) || ms <= 0) return "";
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${Number((ms / 1000).toFixed(2))}s`;
  return `${Number((ms / 60_000).toFixed(2))}min`;
}

/** 受控数字输入：空串 ↔ 0，中间态（"-"、"1e"）原样留在本地，不打扰父级。 */
function NumField({
  id,
  value,
  onChange,
  placeholder,
  min,
}: {
  id: string;
  value: number;
  onChange: (n: number) => void;
  placeholder: string;
  min: number;
}) {
  const [text, setText] = React.useState(value === 0 ? "" : String(value));
  // 父级换了一整套值（读取到策略、切换配置）时跟上；自己敲字时不会走到这里，
  // 因为那时 value 已经等于本地文本 parse 后的结果。
  React.useEffect(() => {
    const incoming = value === 0 ? "" : String(value);
    setText((cur) => (Number(cur || 0) === value ? cur : incoming));
  }, [value]);
  return (
    <Input
      id={id}
      type="number"
      min={min}
      className="w-28 shrink-0"
      value={text}
      placeholder={placeholder}
      onChange={(e) => {
        setText(e.target.value);
        const n = Number(e.target.value);
        onChange(e.target.value.trim() === "" || !Number.isFinite(n) ? 0 : Math.trunc(n));
      }}
    />
  );
}

/** 一层重试的两个旋钮。idPrefix 用来在同一页出现多次时保住 label 的 htmlFor。 */
export function RetryRuleFields({
  layer,
  idPrefix,
  value,
  onChange,
  compact,
}: {
  layer: LayerKey;
  idPrefix: string;
  value: LLMRetryRule;
  onChange: (r: LLMRetryRule) => void;
  /** true = 配置抽屉里的紧凑版：省掉展开说明，只留「什么错误会走到这层」这一句 */
  compact?: boolean;
}) {
  const meta = RETRY_LAYERS[layer];
  const human = humanMs(value.interval_ms);
  return (
    <div className={compact ? "grid gap-2" : "grid gap-3 rounded-lg border p-3"}>
      <div className="grid gap-0.5">
        <div className="flex flex-wrap items-baseline gap-2">
          <Label className="text-sm">{meta.title}</Label>
          <span className="text-muted-foreground text-xs">{meta.where}</span>
        </div>
        {/* 哪些错误会走到这层，具体到状态码——填了旋钮却看不到效果，多半是错误压根不落在这层。 */}
        <p className="text-muted-foreground text-xs">
          <span className="font-medium text-foreground">트리거</span>：{meta.trigger}
        </p>
        {!compact && meta.skips && (
          <p className="text-muted-foreground text-xs">
            <span className="font-medium text-foreground">이 계층 거치지 않음</span>：{meta.skips}
          </p>
        )}
        {!compact && <p className="text-muted-foreground text-xs">{meta.desc}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor={`${idPrefix}-${layer}-n`} className="text-muted-foreground text-xs">
            {meta.attemptsLabel}
          </Label>
          <NumField
            id={`${idPrefix}-${layer}-n`}
            min={-1}
            value={value.attempts}
            placeholder={`기본 ${meta.defAttempts}`}
            onChange={(n) => onChange({ ...value, attempts: n })}
          />
        </div>
        <div className="flex items-center gap-2">
          <Label htmlFor={`${idPrefix}-${layer}-ms`} className="text-muted-foreground text-xs">
            간격 ms
          </Label>
          <NumField
            id={`${idPrefix}-${layer}-ms`}
            min={0}
            value={value.interval_ms}
            placeholder="기본 백오프"
            onChange={(n) => onChange({ ...value, interval_ms: n })}
          />
          <span className="text-muted-foreground text-xs">{human ? `고정 ${human}` : meta.defInterval}</span>
        </div>
      </div>
      {!compact && <p className="text-muted-foreground text-xs">비움 = 기본값 사용; {meta.offHint}。</p>}
    </div>
  );
}

/** 模型配置抽屉里的三层覆盖（跟着端点走的那三层）。 */
export function ProfileRetryFields({
  value,
  onChange,
}: {
  value: LLMRetryOverride;
  onChange: (o: LLMRetryOverride) => void;
}) {
  return (
    <div className="grid gap-3 rounded-lg border p-3">
      <div className="grid gap-0.5">
        <Label className="text-sm">재시도 재정의</Label>
        <p className="text-muted-foreground text-xs">
          이 설정에만 적용되어 「재시도와 백오프」의 전역 기본값을 덮어씁니다. 각 칸을 비우면 전역을 따릅니다. 횟수에 -1 을 넣으면 이 계층의 재시도를 끕니다. 간격을 넣으면 지수 백오프 대신 고정 간격을 씁니다. 차단과 의도 재실행은 프로세스 단위여서 전역 페이지에서만 조정할 수 있습니다.
        </p>
      </div>
      {(["connect", "empty", "stream"] as const).map((k) => (
        <div key={k} className="border-t pt-3 first:border-t-0 first:pt-0">
          <RetryRuleFields
            compact
            layer={k}
            idPrefix="pf"
            value={value[k]}
            onChange={(r) => onChange({ ...value, [k]: r })}
          />
        </div>
      ))}
    </div>
  );
}

/** 「重试与退避」tab：五层的全局默认值。 */
export function RetryPolicyPanel() {
  const [policy, setPolicy] = React.useState<LLMRetryPolicy>(ZERO_POLICY);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const p = await api.llmRetryPolicy();
      setPolicy({ ...ZERO_POLICY, ...p });
    } catch (e) {
      toast.error(`재시도 정책 읽기 실패: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    if (saving) return;
    setSaving(true);
    try {
      // 后端会把越界值夹回区间并回传，直接用回传值刷新，所见即所存。
      const saved = await api.saveLLMRetryPolicy(policy);
      setPolicy({ ...ZERO_POLICY, ...saved });
      toast.success("저장했습니다. 즉시 적용됩니다(진행 중인 이번 턴 호출은 이전 파라미터를 계속 사용)");
    } catch (e) {
      toast.error(`저장 실패: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  }

  const set = (k: LayerKey) => (r: LLMRetryRule) => setPolicy((p) => ({ ...p, [k]: r }));

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-dashed p-10 text-muted-foreground text-sm">
        <Loader2Icon className="size-4 animate-spin" /> 재시도 정책 읽는 중…
      </div>
    );
  }

  return (
    <div className="grid gap-4">
      <div className="rounded-lg border bg-muted/30 p-3 text-muted-foreground text-xs leading-relaxed">
        모델 호출 한 번의 실패는 다섯 계층의 재시도를 안쪽에서 바깥쪽으로 차례로 거칩니다:
        <span className="text-foreground"> 연결 수립 → 빈 응답 → 같은 provider 안전 윈도우 → 라운드로빈 차단 → 의도 재실행</span>
        . 안쪽 계층을 소진해야 바깥 계층 차례가 오므로 횟수는 
        <span className="text-foreground">곱셈</span>
         입니다 — 각 계층을 최대로 올리면 한 번의 흔들림에 수십 번의 요청이 타버립니다. 전부 비우면 현재 기본값이며, 이 페이지가 없던 때의 동작과 완전히 같습니다. 앞의 세 계층은 각 모델 설정에서 개별로 덮어쓸 수 있습니다.
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(Object.keys(RETRY_LAYERS) as LayerKey[]).map((k) => (
          <RetryRuleFields key={k} layer={k} idPrefix="gl" value={policy[k]} onChange={set(k)} />
        ))}
      </div>

      <div className="flex gap-2">
        <Button onClick={save} disabled={saving}>
          {saving ? <Loader2Icon className="animate-spin" /> : <SaveIcon />}
          저장
        </Button>
        <Button variant="outline" onClick={() => setPolicy(ZERO_POLICY)} disabled={saving}>
          전체 기본값 복원
        </Button>
      </div>
    </div>
  );
}
