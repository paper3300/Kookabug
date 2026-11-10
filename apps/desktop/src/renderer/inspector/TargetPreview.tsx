// 속성 창의 `$target` 칸 아래 대상 미리보기: 이 노드가 화면에서 찾을 그림(템플릿)과 찾기 조건 요약.
// - 대상 파일은 target.open(읽기 전용)으로 읽는다. TARGET 탭 문서 표(targetStore)에는 넣지 않는다
// - 그림은 RPC에 싣지 않고 kbimg://ws/ 로 그린다. 워크스페이스가 바뀔 때마다(트리 갱신) 다시 읽고 ?v= 를 올린다
// - 그림을 누르거나 "편집기에서 열기"를 누르면 TARGET 탭을 연다
import { useEffect, useState } from "react";
import type { daemonRpc } from "@kookabug/schema";
import { client, toRpcError } from "../rpc/client";
import { openTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { specFields } from "../target/spec";
import { ANCHOR_LABELS } from "../target/TargetEditor";
import css from "./inspector.module.css";

type Loaded =
  | { status: "loading" }
  | { status: "ready"; result: daemonRpc.TargetOpenResult; version: number }
  | { status: "error"; message: string };

let nextVersion = 0;

function wsUrl(path: string, version: number): string {
  return `kbimg://ws/${path.split("/").map(encodeURIComponent).join("/")}?v=${version}`;
}

export function TargetPreview({ path }: { path: string }) {
  // 트리가 다시 읽히면(workspace.changed) 새 배열이 된다 → 대상 파일·그림이 바뀌었을 수 있으니 다시 읽는다
  const entries = useWorkspace((s) => s.entries);
  const exists = entries.some((e) => e.type === "file" && e.path === path);
  const [loaded, setLoaded] = useState<Loaded>({ status: "loading" });

  useEffect(() => {
    if (!exists) return;
    let alive = true;
    client()
      .call("target.open", { path })
      .then(
        (result) => alive && setLoaded({ status: "ready", result, version: ++nextVersion }),
        (err: unknown) => alive && setLoaded({ status: "error", message: toRpcError(err).message }),
      );
    return () => {
      alive = false;
    };
  }, [path, exists, entries]);

  if (!exists) return null;
  if (loaded.status === "loading") return <div className={css.targetPreview} data-part="target-preview" data-state="loading" />;
  if (loaded.status === "error") {
    return (
      <div className={css.targetPreview} data-part="target-preview" data-state="error">
        <span className={css.muted}>대상 그림을 열지 못했어요: {loaded.message}</span>
      </div>
    );
  }

  return (
    <TargetPreviewView path={path} result={loaded.result} version={loaded.version} onOpen={() => openTab({ path, kind: "target" })} />
  );
}

/** 읽은 대상의 그림·요약 (그리기만) */
export function TargetPreviewView({
  path,
  result,
  version,
  onOpen: open,
}: {
  path: string;
  result: daemonRpc.TargetOpenResult;
  version: number;
  onOpen(): void;
}) {
  const image = result.image;
  const f = specFields(result.spec);
  const facts: string[] = [];
  if (image !== null) facts.push(`${image.width}×${image.height}`);
  facts.push(`일치 ${Math.round(f.threshold * 100)}%`);
  facts.push(f.region === null ? "화면 전체에서 찾기" : "정한 범위에서 찾기");
  facts.push(`클릭 ${ANCHOR_LABELS[f.anchor]}${f.offset[0] !== 0 || f.offset[1] !== 0 ? ` (${f.offset[0]}, ${f.offset[1]})` : ""}`);

  return (
    <div className={css.targetPreview} data-part="target-preview" data-state="ready">
      {image !== null && "workspace" in image ? (
        <button type="button" className={css.targetImageButton} title="TARGET 편집기에서 열기" onClick={open}>
          <img
            className={css.targetImage}
            data-part="target-image"
            src={wsUrl(image.workspace, version)}
            alt={`${path} 대상 그림`}
            width={image.width}
            height={image.height}
            draggable={false}
          />
        </button>
      ) : (
        <div className={css.muted}>저장된 그림이 없어요</div>
      )}
      <div className={css.targetFacts} data-part="target-facts">
        {facts.join(" · ")}
      </div>
      <div className={css.row}>
        <button type="button" className={css.button} data-part="open-target" onClick={open}>
          편집기에서 열기
        </button>
      </div>
    </div>
  );
}
