// 사이드바 "플러그인" (M6 U1 기본값): [+ 플러그인 추가]·[정리], 준비 띠(준비… / 다시 잠그기…), 목록 줄
// (점·이름·판·공유/격리). 줄을 누르면 상세 탭(plugin:<id>)
import { openPluginTab, useTabs, pluginTabPath } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import shell from "../app/shell.module.css";
import {
  bannerView,
  busyText,
  ENV_STATUS_TEXT,
  envText,
  gcSummary,
  KIND_TEXT,
  pluginTitle,
  type BannerView,
} from "./model";
import { openAddDialog, showRunning, startGc, startPrepare, startRelock, usePlugins } from "./pluginStore";
import css from "./plugins.module.css";

/** 준비 띠 (U2): 잠금 있고 환경 없음·깨짐 → [준비…], 조건 다름 → [다시 잠그기…] */
export function PluginBanner({ view, disabled }: { view: BannerView; disabled: boolean }) {
  return (
    <div role="alert" className={css.banner} data-part="plugins-banner" data-kind={view.kind}>
      <span className={css.bannerIcon} aria-hidden="true">
        ⚠
      </span>
      <span className={css.bannerText}>
        {view.text}
        {view.detail !== null && <span className={css.bannerDetail}>{view.detail}</span>}
      </span>
      <button
        type="button"
        className={css.bannerButton}
        disabled={disabled}
        onClick={() => void (view.kind === "relock" ? startRelock() : startPrepare())}
      >
        {view.kind === "relock" ? "다시 잠그기…" : "준비…"}
      </button>
    </div>
  );
}

export function PluginsSidebar() {
  const list = usePlugins((s) => s.list);
  const loadError = usePlugins((s) => s.loadError);
  const running = usePlugins((s) => s.running);
  const runningStage = usePlugins((s) => (s.running === null ? null : (s.ops[s.running.opId]?.message ?? null)));
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const active = useTabs((s) => s.active);
  const banner = bannerView(list);
  const gc = gcSummary(list?.gc_candidates);
  const other = busyText(list?.busy, running?.opId ?? null);
  const blocked = !connected || running !== null || other !== null;
  return (
    <>
      <div className={shell.sidebarHeader} data-part="sidebar-header">
        <span>플러그인</span>
      </div>
      <div className={css.actions}>
        <button type="button" className={css.addButton} data-part="plugin-add" disabled={blocked} onClick={openAddDialog}>
          + 플러그인 추가
        </button>
        <button
          type="button"
          className={css.smallButton}
          data-part="plugin-gc"
          title={gc === null ? "지울 환경이 없어요" : `안 쓰는 환경 정리: ${gc}`}
          disabled={blocked || gc === null}
          onClick={() => void startGc()}
        >
          ⋯ 정리
        </button>
      </div>
      {banner !== null && <PluginBanner view={banner} disabled={blocked} />}
      {running !== null && (
        <button type="button" className={css.busy} data-part="plugin-running" onClick={showRunning}>
          {KIND_TEXT[running.kind]} 중… {runningStage ?? ""}
        </button>
      )}
      {other !== null && (
        <div className={css.busy} data-part="plugin-busy">
          {other}
        </div>
      )}
      {loadError !== null && (
        <div role="alert" className={css.loadError} data-part="plugins-load-error">
          플러그인 목록을 읽지 못했어요: {loadError.message}
        </div>
      )}
      <div role="list" aria-label="플러그인 목록" className={css.list} data-part="plugin-list">
        {list !== null && list.plugins.length === 0 && (
          <div className={css.empty}>
            설치한 플러그인이 없어요.
            <br />
            Git 주소·wheel·폴더에서 추가해요.
          </div>
        )}
        {list?.plugins.map((p) => {
          const title = pluginTitle(p);
          return (
            <button
              key={p.id}
              type="button"
              role="listitem"
              className={css.row}
              data-part="plugin-row"
              data-plugin={p.id}
              data-status={p.env_status}
              aria-current={active === pluginTabPath(p.id) ? "true" : undefined}
              title={`${p.id} · ${ENV_STATUS_TEXT[p.env_status]}`}
              onClick={() => openPluginTab(p.id, title)}
            >
              <span className={css.statusDot} data-status={p.env_status} aria-hidden="true" />
              <span className={css.rowTitle}>{title}</span>
              <span className={css.rowVersion}>{p.version}</span>
              <span className={css.rowEnv}>{p.env_status === "ready" ? envText(p.env) : ENV_STATUS_TEXT[p.env_status]}</span>
            </button>
          );
        })}
      </div>
    </>
  );
}
