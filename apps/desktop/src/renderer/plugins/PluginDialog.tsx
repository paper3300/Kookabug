// 플러그인 작업 대화 상자 (M6 U1): 추가(원천 → 미리보기 → 신뢰 확인 → 진행 → 결과), 준비 신뢰 카드,
// 다시 잠그기·제거·정리 확인. 신뢰 카드 문구 "이 플러그인은 내 PC에서 내 권한으로 실행돼요. 출처를 믿을 때만
// 설치하세요." 모든 값은 daemon이 인증 정보를 가린 것이고, 로컬 절대 경로는 model.hidePaths로 마지막 이름만
import { useEffect, useRef, useState, type ReactNode } from "react";
import shell from "../app/shell.module.css";
import {
  dependencies,
  errorView,
  gcSummary,
  hidePaths,
  ISOLATION_TEXT,
  KIND_TEXT,
  PERMISSION_NOTE,
  pluginPermissions,
  pluginTitle,
  progressSteps,
  resultTitle,
  TRUST_WARNING,
  type Isolation,
  type PluginsList,
  type PreviewResult,
  type SourceDraft,
  type SourceKind,
} from "./model";
import { PermissionList, SourceLine } from "./parts";
import { cancelRunning, closeFlow, confirmFlow, retryAdd, submitSource, usePlugins, type Flow } from "./pluginStore";
import css from "./plugins.module.css";

const SOURCE_TABS: [SourceKind, string][] = [
  ["git", "Git 주소"],
  ["wheel", "wheel 파일·주소"],
  ["path", "폴더"],
];

const SOURCE_FIELD: Record<SourceKind, { label: string; placeholder: string }> = {
  git: { label: "Git 주소", placeholder: "https://github.com/…/kookabug-plugin-sample" },
  wheel: { label: "wheel 파일 경로 또는 https 주소", placeholder: "D:\\plugins\\sample-0.1.0-py3-none-any.whl" },
  path: { label: "플러그인 폴더", placeholder: "plugins/sample" },
};

function Frame({ title, part, children, wide }: { title: string; part: string; children: ReactNode; wide?: boolean }) {
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = boxRef.current;
    (box?.querySelector<HTMLElement>("[data-autofocus=true]") ?? box?.querySelector<HTMLElement>("[data-primary=true]"))?.focus();
  }, [part]);
  return (
    <div className={shell.dialogBackdrop}>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`${shell.dialog} ${wide ? css.dialogWide : css.dialog}`}
        data-part={part}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Escape") {
            e.preventDefault();
            closeFlow();
          }
        }}
      >
        <div className={shell.dialogTitle}>{title}</div>
        {children}
      </div>
    </div>
  );
}

function Buttons({ children }: { children: ReactNode }) {
  return <div className={shell.dialogButtons}>{children}</div>;
}

function SourceStep({ draft: initial, error, pending }: { draft: SourceDraft; error: string | null; pending: boolean }) {
  const [draft, setDraft] = useState(initial);
  const set = (patch: Partial<SourceDraft>) => setDraft((d) => ({ ...d, ...patch }));
  const field = SOURCE_FIELD[draft.kind];
  const submit = () => void submitSource(draft);
  return (
    <Frame title="플러그인 추가" part="plugin-add-dialog">
      <div className={css.segments} role="tablist" aria-label="원천 종류">
        {SOURCE_TABS.map(([kind, label]) => (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={draft.kind === kind}
            className={css.segment}
            disabled={pending}
            onClick={() => set({ kind })}
          >
            {label}
          </button>
        ))}
      </div>
      <form
        className={css.form}
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className={shell.dialogField}>
          <span>{field.label}</span>
          <span className={shell.inputBox}>
            <input
              aria-label={field.label}
              data-autofocus="true"
              placeholder={field.placeholder}
              value={draft.text}
              disabled={pending}
              onChange={(e) => set({ text: e.target.value })}
            />
          </span>
        </label>
        {draft.kind === "git" && (
          <label className={shell.dialogField}>
            <span>버전 (태그·브랜치·커밋, 비우면 기본 브랜치)</span>
            <span className={shell.inputBox}>
              <input aria-label="버전" placeholder="v0.1.0" value={draft.ref} disabled={pending} onChange={(e) => set({ ref: e.target.value })} />
            </span>
          </label>
        )}
        {draft.kind === "wheel" && (
          <label className={shell.dialogField}>
            <span>sha256 (https 주소면 필수)</span>
            <span className={shell.inputBox}>
              <input aria-label="sha256" value={draft.sha256} disabled={pending} onChange={(e) => set({ sha256: e.target.value })} />
            </span>
          </label>
        )}
        <label className={shell.dialogField}>
          <span>환경</span>
          <select
            aria-label="환경"
            className={css.select}
            value={draft.isolation}
            disabled={pending}
            onChange={(e) => set({ isolation: e.target.value as Isolation })}
          >
            {(Object.keys(ISOLATION_TEXT) as Isolation[]).map((k) => (
              <option key={k} value={k}>
                {ISOLATION_TEXT[k]}
              </option>
            ))}
          </select>
        </label>
        <div className={css.hint}>미리보기는 원천을 받아 정보만 읽어요. 플러그인 코드는 신뢰 확인 뒤에만 실행돼요.</div>
        {error !== null && (
          <div role="alert" className={css.formError} data-part="plugin-add-error">
            {error}
          </div>
        )}
        {pending && (
          <div className={css.muted} data-part="plugin-previewing">
            원천을 받는 중이에요…
          </div>
        )}
        <Buttons>
          <button type="button" className={shell.dialogButton} onClick={closeFlow}>
            취소
          </button>
          <button type="submit" className={shell.dialogPrimary} data-primary={false} disabled={pending}>
            미리보기
          </button>
        </Buttons>
      </form>
    </Frame>
  );
}

function Warning({ children }: { children: ReactNode }) {
  return (
    <div className={css.warning} data-part="trust-warning">
      <span aria-hidden="true">⚠</span>
      <span>{children}</span>
    </div>
  );
}

/** 카드를 연 뒤 잠금이 바뀌어 내용을 새로 바꿨다 (B5 검수 H): 다시 보고 확인하라고 알린다 */
function ChangedNotice({ changed }: { changed: boolean | undefined }) {
  if (changed !== true) return null;
  return (
    <div role="alert" className={css.formError} data-part="card-changed">
      잠금이 바뀌었어요 — 바뀐 내용을 다시 확인해 주세요.
    </div>
  );
}

function ConfirmButtons({ label, busy, danger }: { label: string; busy: boolean; danger?: boolean }) {
  return (
    <Buttons>
      <button type="button" className={shell.dialogButton} onClick={closeFlow}>
        취소
      </button>
      <button
        type="button"
        className={danger ? css.dangerPrimary : shell.dialogPrimary}
        data-primary="true"
        data-part="flow-confirm"
        disabled={busy}
        onClick={() => void confirmFlow()}
      >
        {label}
      </button>
    </Buttons>
  );
}

/** 신뢰 카드 (설치): 이름·판·출처(커밋)·권한(아이콘+뜻)·의존성 수, 함께 신뢰할 기존 플러그인 */
export function TrustCard({ preview, busy }: { preview: PreviewResult; busy: boolean }) {
  const deps = dependencies(preview.dependencies);
  const title = preview.title ?? preview.id;
  return (
    <Frame title="이 플러그인을 신뢰하고 설치할까요?" part="plugin-trust" wide>
      <Warning>{TRUST_WARNING}</Warning>
      <div className={css.cardHead}>
        <b className={css.cardTitle}>{title}</b>
        <span className={css.mono}>
          {preview.id} · {preview.replaces !== null ? `${preview.replaces} → ${preview.version}` : preview.version}
        </span>
      </div>
      <dl className={css.facts}>
        <dt>출처</dt>
        <dd>
          <SourceLine source={preview.source} />
        </dd>
        <dt>환경</dt>
        <dd>{ISOLATION_TEXT[preview.isolation]}</dd>
        <dt>권한</dt>
        <dd>
          <PermissionList permissions={preview.permissions} />
        </dd>
        <dt>의존성</dt>
        <dd>
          <details className={css.deps} data-part="trust-deps">
            <summary>{deps.length}개</summary>
            <ul className={css.depList}>
              {deps.map((d) => (
                <li key={d} className={css.mono}>
                  {d}
                </li>
              ))}
            </ul>
          </details>
        </dd>
      </dl>
      {preview.untrusted.length > 0 && (
        <div className={css.untrusted} data-part="trust-untrusted">
          이 잠금의 다른 플러그인 {preview.untrusted.length}개도 신뢰해요 ({preview.untrusted.join(", ")}) — 이 PC에서 아직 신뢰 확인을 하지 않은
          잠금이라, 환경을 다시 만들 때 그 플러그인 코드도 실행돼요.
        </div>
      )}
      <div className={css.note}>{PERMISSION_NOTE}</div>
      <ConfirmButtons label="신뢰하고 설치" busy={busy} />
    </Frame>
  );
}

function LockPlugins({ list }: { list: PluginsList }) {
  return (
    <ul className={css.lockList} data-part="lock-plugins">
      {list.plugins.map((p) => (
        <li key={p.id} className={css.lockItem} data-plugin={p.id}>
          <div className={css.cardHead}>
            <b className={css.cardTitle}>{pluginTitle(p)}</b>
            <span className={css.mono}>
              {p.id} · {p.version}
            </span>
          </div>
          <SourceLine source={p.source} />
          <PermissionList permissions={pluginPermissions(p)} />
        </li>
      ))}
    </ul>
  );
}

function SyncCard({ list, busy, changed }: { list: PluginsList; busy: boolean; changed?: boolean }) {
  return (
    <Frame title="이 프로젝트의 플러그인을 준비할까요?" part="plugin-sync-trust" wide>
      <ChangedNotice changed={changed} />
      <Warning>잠금(kookabug.lock)의 플러그인 {list.plugins.length}개가 내 PC에서 내 권한으로 실행돼요. 출처를 믿을 때만 준비하세요.</Warning>
      <div className={css.muted}>커밋된 wheel과 잠금의 의존성 판 그대로 환경을 만들어요 (빌드 없음). 한 번 신뢰하면 이 잠금이 바뀌기 전까지 다시 묻지 않아요.</div>
      <LockPlugins list={list} />
      <div className={css.note}>{PERMISSION_NOTE}</div>
      <ConfirmButtons label="신뢰하고 준비" busy={busy} />
    </Frame>
  );
}

export function RelockCard({ list, busy, changed }: { list: PluginsList; busy: boolean; changed?: boolean }) {
  return (
    <Frame title="이 앱의 Python·SDK로 다시 잠글까요?" part="plugin-relock-confirm" wide>
      <ChangedNotice changed={changed} />
      {list.stale_reason !== null && <div className={css.mono}>{hidePaths(list.stale_reason)}</div>}
      <Warning>새 환경을 만들며 잠금의 플러그인 {list.plugins.length}개를 확인 실행해요. 출처를 믿을 때만 진행하세요.</Warning>
      <div className={css.muted}>플러그인 판은 그대로 두고 앱의 SDK로 환경과 잠금을 새로 만들어요. 잠금 파일이 바뀌니 Git에 커밋해 팀과 나누세요. 실패하면 잠금은 그대로예요.</div>
      <LockPlugins list={list} />
      <ConfirmButtons label="다시 잠그기" busy={busy} />
    </Frame>
  );
}

function ProgressStep({ flow }: { flow: Extract<Flow, { step: "progress" }> }) {
  const op = usePlugins((s) => s.ops[flow.opId]);
  const steps = progressSteps(flow.kind, op?.stages ?? []);
  return (
    <Frame title={`${flow.title} ${KIND_TEXT[flow.kind]} 중`} part="plugin-progress">
      {steps.length > 0 && (
        <ol className={css.steps} data-part="progress-steps">
          {steps.map((s) => (
            <li key={s.label} className={css.step} data-state={s.state}>
              <span className={css.stepMark} aria-hidden="true">
                {s.state === "done" ? "✓" : s.state === "active" ? "●" : "○"}
              </span>
              {s.label}
            </li>
          ))}
        </ol>
      )}
      <div className={css.muted} data-part="progress-message">
        {op?.message ?? "시작했어요"}
      </div>
      <div className={css.hint}>창을 닫아도 작업은 계속돼요. 실패하거나 취소해도 기존 플러그인은 그대로예요.</div>
      <Buttons>
        <button type="button" className={shell.dialogButton} data-part="progress-cancel" onClick={() => void cancelRunning()}>
          취소
        </button>
        <button type="button" className={shell.dialogPrimary} data-primary="true" onClick={closeFlow}>
          닫기 (계속 진행)
        </button>
      </Buttons>
    </Frame>
  );
}

function ResultStep({ flow }: { flow: Extract<Flow, { step: "result" }> }) {
  const view = flow.error === null ? null : errorView({ ...flow.error, op_id: flow.error.op_id ?? flow.opId ?? undefined });
  const title = flow.ok ? `${flow.title} — ${resultTitle(flow.kind, true)}` : resultTitle(flow.kind, false);
  return (
    <Frame title={title} part={flow.ok ? "plugin-result-ok" : "plugin-result-failed"}>
      {view !== null && (
        <>
          <div role="alert" className={css.formError} data-part="result-error">
            {view.summary}
          </div>
          <details className={css.deps} data-part="result-detail">
            <summary>자세히</summary>
            <ul className={css.depList}>
              {view.detail.map((d, i) => (
                <li key={i} className={css.mono}>
                  {d}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
      {flow.ok && flow.kind === "install" && <div className={css.muted}>탐색기의 노드 팔레트에 이 플러그인 분류가 생겼어요.</div>}
      <Buttons>
        {!flow.ok && flow.kind === "install" && (
          <button type="button" className={shell.dialogButton} onClick={retryAdd}>
            다시 추가
          </button>
        )}
        <button type="button" className={shell.dialogPrimary} data-primary="true" onClick={closeFlow}>
          닫기
        </button>
      </Buttons>
    </Frame>
  );
}

export function PluginDialog() {
  const flow = usePlugins((s) => s.flow);
  if (flow === null) return null;
  switch (flow.step) {
    case "source":
      return <SourceStep key="source" draft={flow.draft} error={flow.error} pending={false} />;
    case "previewing":
      return <SourceStep key="previewing" draft={flow.draft} error={null} pending />;
    case "trust":
      return flow.kind === "install" ? (
        <TrustCard preview={flow.preview} busy={flow.busy} />
      ) : (
        <SyncCard list={flow.list} busy={flow.busy} changed={flow.changed} />
      );
    case "confirm":
      if (flow.kind === "relock") return <RelockCard list={flow.list} busy={flow.busy} changed={flow.changed} />;
      if (flow.kind === "remove") {
        const title = pluginTitle(flow.plugin);
        return (
          <Frame title={`${title} 플러그인을 제거할까요?`} part="plugin-remove-confirm">
            <ChangedNotice changed={flow.changed} />
            <div className={shell.dialogMessage}>
              잠금에서 빼요. 이 플러그인 노드를 쓰는 그래프는 검증 오류가 나요. 환경 폴더·wheel 파일은 "안 쓰는 환경 정리"로 지워요.
            </div>
            <ConfirmButtons label="제거" busy={flow.busy} danger />
          </Frame>
        );
      }
      if (flow.kind === "gc") {
        return (
          <Frame title="안 쓰는 환경을 정리할까요?" part="plugin-gc-confirm">
            <ChangedNotice changed={flow.changed} />
            <div className={shell.dialogMessage}>
              {gcSummary(flow.candidates) ?? "지울 것이 없어요"}을(를) 지워요. 잠금이 쓰는 환경과 실행 중인 환경은 남겨요. 제거한 플러그인의 wheel이 지워지면
              Git 변경으로 보여요.
            </div>
            <ConfirmButtons label="정리" busy={flow.busy} danger />
          </Frame>
        );
      }
      return null;
    case "progress":
      return <ProgressStep flow={flow} />;
    case "result":
      return <ResultStep flow={flow} />;
  }
}
