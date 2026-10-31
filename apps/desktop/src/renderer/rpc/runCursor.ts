// 실행 구독 커서 (M2 계획 2.8 "구독 순서와 커서", 2.3 6). 커서 = 렌더러가 실제로 적용한 마지막 seq.
// - 받은 이벤트는 seq 순으로 적용한다. 역행·중복은 버린다
// - 빈틈(앞 seq가 안 옴)이 보이면 그 구독을 끊고 적용한 마지막 seq부터 다시 구독한다
// - run.lagged를 받으면 적용한 마지막 seq부터 한 번 다시 구독한다 (daemon이 알려 주는 seq는 쓰지 않는다)
// - daemon에 다시 붙으면 끝나지 않은 실행을 전부 적용한 마지막 seq부터 다시 구독한다
// 실행 화면(T11)이 apply로 이벤트를 받아 쓴다
import type { RpcCall } from "./client";

export type CursorResult = "applied" | "duplicate" | "gap" | "unknown_run";

interface RunTrack {
  applied: number;
  ended: boolean;
  /** 지금 다시 구독 중 (같은 빈틈으로 두 번 보내지 않는다) */
  resubscribing: boolean;
}

export class RunCursors {
  private readonly runs = new Map<string, RunTrack>();

  constructor(
    private readonly call: RpcCall,
    private readonly apply: (runId: string, seq: number, event: unknown) => void,
  ) {}

  /** 적용한 마지막 seq (구독하지 않은 실행이면 null) */
  applied(runId: string): number | null {
    return this.runs.get(runId)?.applied ?? null;
  }

  async subscribe(runId: string, afterSeq = 0): Promise<void> {
    const track = this.runs.get(runId) ?? { applied: afterSeq, ended: false, resubscribing: false };
    track.applied = Math.max(track.applied, afterSeq);
    this.runs.set(runId, track);
    await this.call("run.subscribe", { run_id: runId, after_seq: track.applied });
  }

  async unsubscribe(runId: string): Promise<void> {
    this.runs.delete(runId);
    await this.call("run.unsubscribe", { run_id: runId });
  }

  /** 프로젝트를 바꿨다: 앞 워크스페이스 실행은 더 따라가지 않는다 */
  reset(): void {
    this.runs.clear();
  }

  /** run.event 하나. apply가 던지면 커서를 올리지 않고 그 오류를 그대로 던진다 */
  event(runId: string, seq: number, event: unknown): CursorResult {
    const track = this.runs.get(runId);
    if (track === undefined) return "unknown_run";
    if (seq <= track.applied) return "duplicate";
    if (seq !== track.applied + 1) {
      void this.resubscribe(runId);
      return "gap";
    }
    // 커서는 적용이 끝난 뒤에만 올린다. 적용이 실패하면 커서를 그대로 두고 오류를 위로 올린다:
    // 다음 이벤트는 빈틈으로 보여 이 seq부터 다시 구독하고, 재접속·lagged도 이 seq부터 다시 받는다
    this.apply(runId, seq, event);
    track.applied = seq;
    return "applied";
  }

  /** run.lagged: 적용한 마지막 seq부터 다시 */
  lagged(runId: string): void {
    if (this.runs.has(runId)) void this.resubscribe(runId);
  }

  /** run.ended: 이 실행은 더 다시 구독하지 않는다 */
  ended(runId: string): void {
    const track = this.runs.get(runId);
    if (track) track.ended = true;
  }

  /** daemon에 다시 붙은 뒤: 끝나지 않은 실행을 모두 커서부터 다시 구독한다 */
  async resubscribeAll(): Promise<void> {
    await Promise.all([...this.runs].filter(([, t]) => !t.ended).map(([id]) => this.resubscribe(id)));
  }

  private async resubscribe(runId: string): Promise<void> {
    const track = this.runs.get(runId);
    if (track === undefined || track.resubscribing) return;
    track.resubscribing = true;
    try {
      await this.call("run.subscribe", { run_id: runId, after_seq: track.applied });
    } catch {
      // 연결이 없으면 다음 연결 때 resubscribeAll이 다시 한다
    } finally {
      track.resubscribing = false;
    }
  }
}
