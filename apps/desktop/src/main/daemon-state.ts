// 렌더러에 보내는 daemon 연결 상태 모양. 렌더러 타입 검사도 이 파일을 읽으므로 Node API를 쓰지 않는다

export type DaemonStatus = "idle" | "connecting" | "connected" | "disconnected" | "mismatch" | "error";
export type DaemonErrorKind = "cli_not_found" | "spawn_failed" | "timeout";

/** 구조화 복제되는 평범한 값 */
export interface DaemonState {
  status: DaemonStatus;
  root: string | null;
  appProtocol: number;
  startId?: string;
  /**
   * 연결 번호 (붙을 때마다 1씩 오른다). daemon은 연결이 끝나면 그 연결이 연 문서 참조를 푼다:
   * 번호가 바뀌면 같은 daemon이어도 열린 문서를 다시 열어야 한다
   */
  connection?: number;
  daemonVersion?: string;
  /** daemon의 프로토콜 판 */
  protocol?: number;
  attempt?: number;
  retryInMs?: number;
  error?: DaemonErrorKind;
  message?: string;
  logPath?: string;
  tried?: string[];
  /** 판 다름: 다시 시작이 진행 중인 실행 때문에 거부됨 */
  runActive?: boolean;
}
