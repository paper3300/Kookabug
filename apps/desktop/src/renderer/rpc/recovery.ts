// daemon에 다시 붙은 뒤 복구 (M2 계획 2.3 6, 검수 M3·M4, T7 검수 2차).
// daemon은 연결이 끝나면 그 연결이 연 문서 참조를 풀고, 아무도 참조하지 않는 문서는 지운다. 그래서 복구
// 단위는 daemon(start_id)이 아니라 **연결**이다:
// - 새 연결마다 열린 문서를 모두 graph.open으로 다시 열어 그 연결의 doc_id에 붙는다. 같은 daemon에
//   다시 붙었어도, 앞 연결에서 이미 다시 열었던 문서도 다시 연다 (앞 연결의 성공은 이 연결의 성공이 아니다)
//   버퍼 값·dirty·실행 취소 기록·base_revision은 렌더러에 있으므로 그대로 둔다
//     · 디스크 revision = base_revision → 새 doc_id만 바꾼다
//     · 다르고 dirty → 새 doc_id + 충돌 띠 (base_revision은 그대로라 force 없이 저장하면 revision_conflict)
//     · 다르고 clean → 디스크 값으로 다시 연다
//   다 붙이면 한 번 검증한다. 다시 여는 도중 끊기면 다음 연결에서 처음부터 다시 연다
// - 같은 연결에서 연결됨이 두 번 오면 아무것도 하지 않는다 (중복 열기·참조를 만들지 않는다)
// - start_id가 바뀌었으면(daemon 교체) 옛 frame_id를 전부 만료로 본다
// - 실행 구독은 새 연결마다 적용한 마지막 seq부터 다시 한다
// 문서 표(T8)·target 편집기(T12)·실행 화면(T11)은 각자 Host를 등록한다
import type { ResultOf } from "@kookabug/schema";
import { toRpcError, type RpcCall, type RpcError } from "./client";

export type GraphOpenResult = ResultOf<"graph.open">;

export interface OpenDocRef {
  path: string;
  baseRevision: string | null;
  dirty: boolean;
}

export interface DocHost {
  docs(): OpenDocRef[];
  /** 새 doc_id에 붙인다. 버퍼·dirty·실행 취소 기록·base_revision은 그대로 */
  rebind(path: string, opened: GraphOpenResult): void;
  /** 디스크가 바뀌었는데 편집 중: 충돌 띠 */
  conflict(path: string, diskRevision: string): void;
  /** 디스크가 바뀌었고 편집하지 않음: 디스크 값으로 다시 연다 */
  reload(path: string, opened: GraphOpenResult): void;
  /** 다시 열지 못함 (파일이 지워짐·JSON 오류 등) */
  failed(path: string, error: RpcError): void;
  /** 다시 붙은 뒤 한 번 검증 */
  validateAll(): void;
}

export interface FrameHost {
  /** 편집기 정지 화면을 모두 만료로 (TARGET 탭은 "정지 화면을 다시 고르세요") */
  expireAll(): void;
}

export interface RunHost {
  /** 적용한 마지막 seq부터 다시 구독 */
  resubscribeAll(): Promise<void>;
}

export interface ConnectedInfo {
  root: string;
  startId: string;
  /** 주 프로세스의 연결 번호 (DaemonState.connection). 없으면 부를 때마다 새 연결로 본다 */
  connection?: number;
}

/** first: 이 워크스페이스의 첫 연결. same_connection: 이미 처리한 연결 */
export type RecoveryKind = "first" | "same_connection" | "same_daemon" | "daemon_replaced";

export class SessionRecovery {
  private last: ConnectedInfo | null = null;
  private readonly docHosts = new Set<DocHost>();
  private readonly frameHosts = new Set<FrameHost>();
  private readonly runHosts = new Set<RunHost>();

  constructor(private readonly call: RpcCall) {}

  addDocs(host: DocHost): () => void {
    this.docHosts.add(host);
    return () => this.docHosts.delete(host);
  }

  addFrames(host: FrameHost): () => void {
    this.frameHosts.add(host);
    return () => this.frameHosts.delete(host);
  }

  addRuns(host: RunHost): () => void {
    this.runHosts.add(host);
    return () => this.runHosts.delete(host);
  }

  /** 워크스페이스를 닫았다·바꿨다: 다음 연결은 처음 연결이다 */
  reset(): void {
    this.last = null;
  }

  /** 연결됨 상태를 받을 때마다 부른다 */
  async connected(info: ConnectedInfo): Promise<RecoveryKind> {
    const prev = this.last;
    const sameRoot = prev !== null && prev.root === info.root;
    if (
      sameRoot &&
      info.connection !== undefined &&
      prev.connection === info.connection &&
      prev.startId === info.startId
    ) {
      return "same_connection";
    }
    this.last = info;
    if (!sameRoot) return "first";
    const replaced = prev.startId !== info.startId;
    if (replaced) for (const host of this.frameHosts) host.expireAll();
    await Promise.all([...this.docHosts].map((host) => this.reopen(host, info)));
    await Promise.all([...this.runHosts].map((host) => host.resubscribeAll()));
    return replaced ? "daemon_replaced" : "same_daemon";
  }

  /** 이 연결에서 열린 문서를 모두 다시 연다. 끊기면 멈춘다 (다음 연결이 처음부터 한다) */
  private async reopen(host: DocHost, info: ConnectedInfo): Promise<void> {
    let rebound = false;
    for (const doc of host.docs()) {
      let opened: GraphOpenResult;
      try {
        opened = await this.call("graph.open", { path: doc.path });
      } catch (err) {
        if (this.last !== info) return;
        const error = toRpcError(err);
        if (error.kind === "not_connected") return;
        host.failed(doc.path, error);
        continue;
      }
      // 기다리는 동안 다른 연결로 바뀌었으면 이 결과는 쓰지 않는다 (그 연결이 다시 연다)
      if (this.last !== info) return;
      rebound = true;
      if (opened.revision === doc.baseRevision) {
        host.rebind(doc.path, opened);
      } else if (doc.dirty) {
        host.rebind(doc.path, opened);
        host.conflict(doc.path, opened.revision);
      } else {
        host.reload(doc.path, opened);
      }
    }
    if (rebound) host.validateAll();
  }
}
