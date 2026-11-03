// 보기 탭 내용 (다듬기 P1-B). 전용 편집기가 없는 탐색기 파일을 읽기 전용으로 보인다.
// - 글자 파일은 workspace.read(앞 1 MiB)로 읽는다. 이미지는 RPC에 싣지 않고 kbimg://ws/로 그린다 (M2 계획 2.4)
// - 열린 보기 탭만 들고 있다 (탭을 닫으면 버린다). workspace.changed에 그 경로가 있으면 다시 읽는다. 다시 읽는 동안은
//   앞 내용을 그대로 보인다(깜빡이지 않게). 늦게 온 앞 응답은 버린다(경로마다 요청 번호)
// - 이미지는 바뀔 때 version만 올린다 (<img>를 새로 만들어 다시 읽는다)
import { create } from "zustand";
import { client, toRpcError, type RpcCall } from "../rpc/client";
import { fileViewKind, useTabs, type FileViewKind } from "../store/tabs";

export interface FileView {
  path: string;
  kind: FileViewKind;
  status: "loading" | "ready" | "error";
  text: string;
  /** 파일 전체 크기 (이미지는 null) */
  bytes: number | null;
  truncated: boolean;
  binary: boolean;
  /** 읽지 못한 이유 (not_found면 "파일이 없어요") */
  error: string | null;
  /** 다시 읽을 때마다 오른다 (이미지는 그림 주소 표식, 모델 전체에서 겹치지 않는다) */
  version: number;
}

interface FileViewState {
  views: ReadonlyMap<string, FileView>;
}

export const useFileViews = create<FileViewState>(() => ({ views: new Map() }));

export class FileViewModel {
  private seq = new Map<string, number>();
  private counter = 0;

  constructor(
    private readonly call: () => RpcCall,
    private readonly store = useFileViews,
  ) {}

  private update(path: string, fn: (v: FileView) => FileView): void {
    this.store.setState((s) => {
      const view = s.views.get(path);
      if (view === undefined) return s;
      const views = new Map(s.views);
      views.set(path, fn(view));
      return { views };
    });
  }

  get(path: string): FileView | undefined {
    return this.store.getState().views.get(path);
  }

  /** 열린 보기 탭 목록에 맞춘다: 새 탭은 읽고, 닫힌 탭은 버린다 */
  sync(paths: readonly string[]): void {
    const open = new Set(paths);
    const views = this.store.getState().views;
    const added = paths.filter((p) => !views.has(p));
    const gone = [...views.keys()].filter((p) => !open.has(p));
    if (added.length === 0 && gone.length === 0) return;
    this.store.setState((s) => {
      const next = new Map(s.views);
      for (const p of gone) {
        next.delete(p);
        this.seq.delete(p);
      }
      for (const p of added) {
        next.set(p, {
          path: p,
          kind: fileViewKind(p),
          status: "loading",
          text: "",
          bytes: null,
          truncated: false,
          binary: false,
          error: null,
          version: 0,
        });
      }
      return { views: next };
    });
    for (const p of added) void this.load(p);
  }

  async load(path: string): Promise<void> {
    const view = this.get(path);
    if (view === undefined) return;
    // 번호는 모델 전체에서 하나씩 오른다: 탭을 닫았다 다시 열어도 앞 요청의 늦은 응답과 겹치지 않는다
    const n = ++this.counter;
    this.seq.set(path, n);
    if (view.kind === "image") {
      // 그림 주소 표식이 된다: 닫았다 다시 연 탭도 앞 주소(렌더러가 메모리에 둔 옛 그림)와 겹치지 않게 모델 번호를 쓴다
      this.update(path, (v) => ({ ...v, status: "ready", error: null, version: n }));
      return;
    }
    try {
      const r = await this.call()("workspace.read", { path });
      if (this.seq.get(path) !== n) return;
      this.update(path, (v) => ({
        ...v,
        status: "ready",
        text: r.text,
        bytes: r.bytes,
        truncated: r.truncated,
        binary: r.binary,
        error: null,
        version: v.version + 1,
      }));
    } catch (err) {
      if (this.seq.get(path) !== n) return;
      const e = toRpcError(err);
      const error = e.kind === "not_found" ? "파일이 없어요" : e.message;
      this.update(path, (v) => ({ ...v, status: "error", error, version: v.version + 1 }));
    }
  }

  /** workspace.changed: 그 경로의 보기를 다시 읽는다 (경로 목록이 비면 모두) */
  changed(paths: readonly string[]): void {
    for (const path of this.store.getState().views.keys()) {
      if (paths.length === 0 || paths.includes(path)) void this.load(path);
    }
  }

  /** 다시 붙은 뒤: 끊긴 동안 바뀌었을 수 있다 */
  reloadAll(): void {
    this.changed([]);
  }

  reset(): void {
    this.seq.clear();
    this.store.setState({ views: new Map() });
  }
}

export const fileViewModel = new FileViewModel(() => client().call);

useTabs.subscribe((state) => {
  fileViewModel.sync(state.tabs.filter((t) => t.kind === "file").map((t) => t.path));
});
