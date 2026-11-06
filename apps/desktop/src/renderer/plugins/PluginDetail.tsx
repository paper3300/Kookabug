// 플러그인 상세 탭 (`plugin:<id>`, M6 U1 기본값): 이름·ID·판·[제거], 출처, 환경, 권한 표, 노드, 의존성(펼치기)
import {
  dependencies,
  ENV_STATUS_TEXT,
  envText,
  isolationReason,
  PERMISSION_NOTE,
  pluginTitle,
  type PluginEntry,
} from "./model";
import { PermissionTable, SourceLine } from "./parts";
import { startRemove, usePlugins } from "./pluginStore";
import css from "./plugins.module.css";

function modulesOf(entry: PluginEntry): string[] {
  const raw = entry.manifest.modules;
  return Array.isArray(raw) ? raw.filter((m): m is string => typeof m === "string") : [];
}

export function PluginDetail({ id }: { id: string }) {
  const entry = usePlugins((s) => s.list?.plugins.find((p) => p.id === id));
  const listed = usePlugins((s) => s.list !== null);
  const busy = usePlugins((s) => s.running !== null || (s.list?.busy ?? null) !== null);
  if (entry === undefined) {
    return (
      <div className={css.detail} data-part="plugin-detail" data-plugin={id}>
        <div className={css.detailInner}>
          <div className={css.muted}>{listed ? "이 플러그인은 잠금에 없어요 (제거됐어요)." : "플러그인 목록을 읽는 중이에요"}</div>
        </div>
      </div>
    );
  }
  return <PluginDetailBody entry={entry} busy={busy} />;
}

/** 상세 본문 (스토어 없이 그린다 — 검사도 이것을 그린다) */
export function PluginDetailBody({ entry, busy }: { entry: PluginEntry; busy: boolean }) {
  const id = entry.id;
  const title = pluginTitle(entry);
  const reason = isolationReason(entry);
  const deps = dependencies(entry.requires);
  return (
    <div className={css.detail} data-part="plugin-detail" data-plugin={id}>
      <div className={css.detailInner}>
        <div className={css.detailHead}>
          <h2 className={css.h2}>{title} 플러그인</h2>
          <span className={css.mono}>
            {entry.id} · {entry.version}
          </span>
          <span className={css.spacer} />
          <button
            type="button"
            className={css.dangerButton}
            data-part="plugin-remove"
            disabled={busy}
            onClick={() => startRemove(entry)}
          >
            제거
          </button>
        </div>
        <dl className={css.facts}>
          <dt>출처</dt>
          <dd>
            <SourceLine source={entry.source} />
          </dd>
          <dt>환경</dt>
          <dd data-part="plugin-env" data-status={entry.env_status}>
            <span className={css.statusDot} data-status={entry.env_status} aria-hidden="true" />
            {envText(entry.env)} · {ENV_STATUS_TEXT[entry.env_status]}
            {reason !== null && <span className={css.muted}> — {reason}</span>}
          </dd>
          <dt>모듈</dt>
          <dd className={css.mono}>{modulesOf(entry).join(", ")}</dd>
        </dl>

        <h3 className={css.h3}>권한</h3>
        <div className={css.note}>{PERMISSION_NOTE}</div>
        <PermissionTable entry={entry} />

        <h3 className={css.h3}>노드 {entry.nodes.length}개</h3>
        <div className={css.tableWrap}>
          <table className={css.table} data-part="plugin-nodes">
            <thead>
              <tr>
                <th>이름</th>
                <th>종류</th>
                <th>효과</th>
              </tr>
            </thead>
            <tbody>
              {entry.nodes.map((n) => (
                <tr key={n.type} data-node-type={n.type}>
                  <td>{n.title ?? n.type}</td>
                  <td className={css.mono}>{n.type}</td>
                  <td className={css.muted}>{n.effects.length === 0 ? "없음 (순수)" : n.effects.join(", ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <details className={css.deps} data-part="plugin-deps">
          <summary>의존성 {deps.length}개</summary>
          {deps.length === 0 ? (
            <div className={css.muted}>SDK 말고는 없어요</div>
          ) : (
            <ul className={css.depList}>
              {deps.map((d) => (
                <li key={d} className={css.mono}>
                  {d}
                </li>
              ))}
            </ul>
          )}
        </details>
      </div>
    </div>
  );
}
