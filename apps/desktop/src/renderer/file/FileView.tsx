// 보기 탭 내용 (다듬기 P1-B): 탐색기의 화면 지도·설정·문서·이미지 등 전용 편집기가 없는 파일을 읽기 전용으로 보인다.
// JSON은 두 칸 들여쓰기와 구문 색(원문 낱말 그대로), 그 밖 글자는 원문, 이미지는 그림. 고치기는 아직 없다
import { useMemo, useState } from "react";
import { formatJson, type JsonLine, type SegKind } from "./jsonFormat";
import { useFileViews, type FileView as FileViewState } from "./fileViewStore";
import css from "./file.module.css";

/** 이보다 큰 JSON은 색 없이 원문으로 (요소 수 보호) */
export const HIGHLIGHT_LIMIT = 256 * 1024;

const SEG_CLASS: Record<SegKind, string | undefined> = {
  key: css.key,
  string: css.string,
  number: css.number,
  literal: css.literal,
  punct: css.punct,
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** 그림 주소. 렌더러는 같은 주소의 그림을 메모리에서 다시 쓰므로, 다시 읽을 때마다 표식(?v=)을 바꾼다 */
export function imageUrl(path: string, version: number): string {
  return `kbimg://ws/${path.split("/").map(encodeURIComponent).join("/")}?v=${version}`;
}

function JsonBody({ lines }: { lines: JsonLine[] }) {
  return (
    <pre className={css.code} data-part="file-json">
      {lines.map((line, i) => (
        <div key={i} className={css.line}>
          {"  ".repeat(line.depth)}
          {line.segs.map((s, j) => (
            <span key={j} className={SEG_CLASS[s.kind]} data-seg={s.kind}>
              {s.text}
            </span>
          ))}
        </div>
      ))}
    </pre>
  );
}

function ImageBody({ view }: { view: FileViewState }) {
  const [size, setSize] = useState<{ version: number; w: number; h: number } | null>(null);
  const [failed, setFailed] = useState<number | null>(null);
  if (failed === view.version) {
    return (
      <div className={css.message} role="alert" data-part="file-error">
        그림을 읽을 수 없어요
      </div>
    );
  }
  return (
    <div className={css.imageWrap}>
      {size !== null && size.version === view.version && (
        <div className={css.imageSize} data-part="file-image-size">
          {size.w}×{size.h}
        </div>
      )}
      {/* version이 바뀌면 새 주소의 <img>로 다시 읽는다 */}
      <img
        key={view.version}
        className={css.image}
        data-part="file-image"
        src={imageUrl(view.path, view.version)}
        alt={view.path}
        onLoad={(e) => setSize({ version: view.version, w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        onError={() => setFailed(view.version)}
      />
    </div>
  );
}

function TextBody({ view }: { view: FileViewState }) {
  const lines = useMemo(
    () => (view.kind === "json" && view.text.length <= HIGHLIGHT_LIMIT && !view.truncated ? formatJson(view.text) : null),
    [view.kind, view.text, view.truncated],
  );
  const notes: string[] = [];
  if (view.truncated && view.bytes !== null) notes.push(`앞 1 MB만 보여요 (전체 ${formatBytes(view.bytes)})`);
  if (view.kind === "json" && lines === null && !view.truncated) {
    notes.push(view.text.length > HIGHLIGHT_LIMIT ? "커서 색 없이 원문을 보여요" : "JSON으로 읽을 수 없어 원문을 보여요");
  }
  return (
    <>
      {notes.length > 0 && (
        <div className={css.note} data-part="file-note">
          {notes.join(" · ")}
        </div>
      )}
      {lines !== null ? (
        <JsonBody lines={lines} />
      ) : (
        <pre className={`${css.code} ${css.wrap}`} data-part="file-text">
          {view.text}
        </pre>
      )}
    </>
  );
}

/** 탭 내용: 파일 하나의 읽기 전용 보기 */
export function FileView({ path }: { path: string }) {
  const view = useFileViews((s) => s.views.get(path));
  let body;
  if (view === undefined || (view.status === "loading" && view.version === 0)) {
    body = <div className={css.message}>여는 중…</div>;
  } else if (view.status === "error") {
    body = (
      <div className={css.message} role="alert" data-part="file-error">
        <strong>{view.error === "파일이 없어요" ? view.error : "파일을 읽을 수 없어요"}</strong>
        <span className={css.messagePath}>{path}</span>
        {view.error !== "파일이 없어요" && <span>{view.error}</span>}
      </div>
    );
  } else if (view.kind === "image") {
    body = <ImageBody view={view} />;
  } else if (view.binary) {
    body = (
      <div className={css.message} data-part="file-binary">
        <strong>글자 파일이 아니라 보일 수 없어요</strong>
        <span className={css.messagePath}>{path}</span>
      </div>
    );
  } else {
    body = <TextBody view={view} />;
  }
  return (
    <div
      className={css.view}
      data-part="file-view"
      data-path={path}
      data-kind={view?.kind ?? ""}
      data-status={view?.status ?? "loading"}
      data-version={view?.version ?? 0}
    >
      <div className={css.head} data-part="file-view-head">
        <span className={css.readonly}>읽기 전용</span>
        {view?.bytes != null && <span>{formatBytes(view.bytes)}</span>}
      </div>
      <div className={css.body}>{body}</div>
    </div>
  );
}
