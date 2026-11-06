// 플러그인 화면 조각: 권한 아이콘·권한 표(시안 Permissions 표 스타일)·원천 줄·플러그인 요약 줄
import type { ReactNode } from "react";
import { nodesByPermission, permissionInfo, sourceView, type PluginEntry } from "./model";
import css from "./plugins.module.css";

const ICON_PATHS: Readonly<Record<string, ReactNode>> = {
  capture: <path d="M2 5V2h3M11 2h3v3M14 11v3h-3M5 14H2v-3M6 8a2 2 0 1 0 4 0 2 2 0 1 0-4 0" />,
  input: <path d="M4 2l8 6-4 1 2 4-1.5.7-2-4L4 12z" />,
  process: <path d="M2 3h12v10H2zM2 6h12M6 9l2 1.5L6 12" />,
  filesystem: <path d="M4 2h5l3 3v9H4zM9 2v3h3" />,
  network: <path d="M8 2a6 6 0 1 0 0 12A6 6 0 1 0 8 2M2 8h12M8 2c2 2 2 10 0 12M8 2c-2 2-2 10 0 12" />,
  secrets: <path d="M10 2a4 4 0 1 0 0 .01M7.5 8.5L2 14M4 12l1.5 1.5M5.5 10.5L7 12" />,
};

/** 권한 아이콘 (16px, currentColor) */
export function PermissionIcon({ id }: { id: string }) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" aria-hidden="true">
      {ICON_PATHS[id] ?? <path d="M3 3h10v10H3z" />}
    </svg>
  );
}

/** 권한 목록 (신뢰 카드): 아이콘 + 이름 + 뜻. 없으면 "권한 선언 없음" */
export function PermissionList({ permissions }: { permissions: readonly string[] }) {
  if (permissions.length === 0) {
    return <div className={css.muted}>권한 선언 없음 — 계산만 하는 노드예요</div>;
  }
  return (
    <ul className={css.permList} data-part="permission-list">
      {permissions.map((id) => {
        const info = permissionInfo(id);
        return (
          <li key={id} className={css.permItem} data-permission={id}>
            <span className={css.permIcon} data-permission={id}>
              <PermissionIcon id={id} />
            </span>
            <b className={css.permLabel}>{info.label}</b>
            <span className={css.muted}>{info.meaning}</span>
          </li>
        );
      })}
    </ul>
  );
}

/** 권한 표 (상세 탭, 시안 Permissions 표): 권한 | 뜻 | 쓰는 노드 */
export function PermissionTable({ entry }: { entry: Pick<PluginEntry, "nodes" | "manifest"> }) {
  const rows = nodesByPermission(entry);
  return (
    <div className={css.tableWrap}>
      <table className={css.table} data-part="permission-table">
        <thead>
          <tr>
            <th>권한</th>
            <th>뜻</th>
            <th>쓰는 노드</th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={3} className={css.muted}>
                권한 선언 없음 — 계산만 하는 노드예요
              </td>
            </tr>
          )}
          {rows.map((r) => {
            const info = permissionInfo(r.id);
            return (
              <tr key={r.id} data-permission={r.id}>
                <td>
                  <span className={css.permCell}>
                    <span className={css.permIcon} data-permission={r.id}>
                      <PermissionIcon id={r.id} />
                    </span>
                    {info.label} <span className={css.mono}>{r.id}</span>
                  </span>
                </td>
                <td className={css.muted}>{info.meaning}</td>
                <td>{r.nodes.length === 0 ? <span className={css.muted}>없음</span> : r.nodes.join(", ")}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 원천 한 줄: 종류 · 주소(경로 가림) · ref·커밋 */
export function SourceLine({ source }: { source: Record<string, unknown> | null | undefined }) {
  const view = sourceView(source);
  return (
    <span className={css.source} data-part="plugin-source" data-kind={view.kind}>
      <span className={css.sourceKind}>{view.label}</span>
      <span className={css.mono}>{view.where}</span>
      {view.detail !== null && <span className={css.mono}>{view.detail}</span>}
    </span>
  );
}
