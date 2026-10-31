/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 *
 * This interface was referenced by `Session`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;

/**
 * .kookabug/session.json: 워크스페이스 daemon 하나의 접속 정보. daemon이 .kookabug/daemon.lock을 쥔 뒤 임시 파일 + replace로 쓰고, 끝날 때 자기 start_id인 경우에만 지운다. 판단 근거는 잠금이고, pid·process_created는 붙기 전에 보는 빠른 확인이다
 */
export interface Session {
  daemon_version: string;
  format: "kookabug.session/0";
  pid: number;
  port: number;
  /**
   * daemon 프로세스 생성 시각: Windows FILETIME(100ns 단위)을 10진 문자열로
   */
  process_created: string;
  protocol: number;
  /**
   * daemon이 시작할 때 정한 무작위 ID (16바이트 hex). 바뀌면 daemon이 교체된 것
   */
  start_id: string;
  started_at: Timestamp;
  /**
   * session.hello 인증 토큰 (32바이트 hex)
   */
  token: string;
  /**
   * 워크스페이스 루트 절대 경로
   */
  workspace: string;
}
