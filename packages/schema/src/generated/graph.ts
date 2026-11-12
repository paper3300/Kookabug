/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 핀 타입: bool|int|float|string|secret|target|match|rect|point|image|window|process|any, list[T], dict[str,T], <플러그인>.<Type>, 유니온 A|B
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "PinType".
 */
export type PinType = string;
/**
 * 만들 때 정하고 바꾸지 않는다. $link가 '.'으로 노드와 출력을 나누므로 '.'을 쓸 수 없다
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "NodeId".
 */
export type NodeId = string;
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "ExitName".
 */
export type ExitName = string;
/**
 * in 핀 값: JSON 상수, 배열, 특수 값, $ 키가 없는 일반 객체. 특수 값은 배열·객체 안 어디든 올 수 있다
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Value".
 */
export type Value = (boolean | null | number | string) | Value[] | ObjectValue;
/**
 * $로 시작하는 키가 있으면 특수 값, 없으면 일반 객체
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "ObjectValue".
 */
export type ObjectValue = SpecialValue | {[key: string]: Value};
/**
 * <플러그인>.<분류>.<동작>
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "NodeType".
 */
export type NodeType = string;
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "QaCheatArgLimit".
 */
export type QaCheatArgLimit = QaCheatArgRange | QaCheatArgEnum;
/**
 * 노드ID.출력
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "LinkRef".
 */
export type LinkRef = string;
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "PinName".
 */
export type PinName = string;
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "PluginId".
 */
export type PluginId = string;
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "SecretKey".
 */
export type SecretKey = string;
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "SettingKey".
 */
export type SettingKey = string;
/**
 * 워크스페이스 루트 기준 *.target.json 경로 ('/' 구분)
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "TargetPath".
 */
export type TargetPath = string;

/**
 * 테스트·서브그래프 그래프 파일 (*.graph.json). 테스트와 서브그래프는 같은 형식이고 kind만 다르다
 */
export interface Graph {
  /**
   * 입력 효과 노드를 부르기 직전에 대상 창을 앞으로 가져오는 기본값. 없으면 켜짐 (UX4)
   */
  focus_before_input?: boolean;
  format: "kookabug.graph/0";
  interface?: Interface;
  kind: "subgraph" | "test";
  layout?: Layout;
  meta?: Meta;
  nodes: {
    [k: string]: Node | undefined;
  };
  /**
   * 그래프가 쓰는 플러그인 ID → 버전
   */
  plugins: {
    [k: string]: string | undefined;
  };
  qa?: Qa;
  record?: RecordPolicy;
}
/**
 * 서브그래프의 공개 핀. inputs → 호출 노드 입력, exits → 출구, outputs → 출력
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Interface".
 */
export interface Interface {
  exits: {
    [k: string]: InterfaceExit | undefined;
  };
  inputs?: {
    [k: string]: InterfaceInput | undefined;
  };
  outputs?: {
    [k: string]: InterfaceOutput | undefined;
  };
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "InterfaceExit".
 */
export interface InterfaceExit {
  description?: string;
  kind: "fail" | "ok";
  /**
   * 이 출구로 나갔을 때 도착하는 화면 (화면 지도용)
   */
  screen?: string;
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "InterfaceInput".
 */
export interface InterfaceInput {
  /**
   * 호출 노드가 값을 주지 않았을 때 쓰는 상수
   */
  default?: unknown;
  description?: string;
  type: PinType;
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "InterfaceOutput".
 */
export interface InterfaceOutput {
  description?: string;
  /**
   * exit 노드가 주지 않으면 null로 채운다
   */
  nullable?: boolean;
  type: PinType;
}
/**
 * 편집기 배치. 실행에는 영향이 없다
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Layout".
 */
export interface Layout {
  collapsed?: {
    [k: string]: LayoutGroup | undefined;
  };
  comments?: {
    [k: string]: LayoutComment | undefined;
  };
  nodes?: {
    [k: string]: Position | undefined;
  };
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "LayoutGroup".
 */
export interface LayoutGroup {
  nodes: NodeId[];
  title?: string;
  x: number;
  y: number;
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "LayoutComment".
 */
export interface LayoutComment {
  /**
   * [x, y, w, h]
   *
   * @minItems 4
   * @maxItems 4
   */
  rect: [number, number, number, number];
  text: string;
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Position".
 */
export interface Position {
  x: number;
  y: number;
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Meta".
 */
export interface Meta {
  description?: string;
  tags?: string[];
  title?: string;
}
/**
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Node".
 */
export interface Node {
  config?: NodeConfig;
  /**
   * 입력 효과 노드를 부르기 직전에 대상 창을 앞으로 가져올지. 없으면 그래프의 focus_before_input을 따른다 (UX4)
   */
  focus_before_input?: boolean;
  /**
   * 입력 핀 값. 상수 또는 특수 값
   */
  in?: {
    [k: string]: Value | undefined;
  };
  /**
   * exec 연결: 출구 이름 → 다음 노드 ID
   */
  next?: {
    [k: string]: NodeId | undefined;
  };
  record?: RecordPolicy;
  title?: string;
  type: NodeType;
  version: number;
}
/**
 * 연결할 수 없는 노드 설정. 키는 노드 스키마가 정한다 (retry만 공통)
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "NodeConfig".
 */
export interface NodeConfig {
  retry?: RetryConfig;
  [k: string]: unknown | undefined;
}
/**
 * 노드 config.retry. 노드 스키마의 retry 선언 범위 안에서만 켠다
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "RetryConfig".
 */
export interface RetryConfig {
  /**
   * 첫 실행 포함
   */
  max_attempts: number;
  /**
   * 재시도할 fail 출구. 생략하면 노드 스키마의 retry.on 전부
   *
   * @minItems 1
   */
  on?: [ExitName, ...ExitName[]];
}
/**
 * 기록 정책. 상위(워크스페이스 → 테스트 → 서브그래프 → 노드)에서 끈 것은 하위에서 켤 수 없다
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "RecordPolicy".
 */
export interface RecordPolicy {
  screenshots?: "off" | "on";
  video?: "failed_only" | "off" | "on";
}
/**
 * M8 테스트별 QA 옵션 kookabug.qa/0 (KB문서 10장). 지원하지 않는 실행기는 최상위 추가 속성이라 거부한다. 서브그래프는 cheats만 쓰고 상위 허용을 줄이는 방향(교집합)으로만 적용
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "Qa".
 */
export interface Qa {
  cheats?: {
    allow: QaCheatAllow[];
  };
  claims?: QaClaim[];
  feature?: string;
  format: "kookabug.qa/0";
  /**
   * @minItems 1
   */
  profiles?: [string, ...string[]];
  repair?: {
    allowed_changes?: "locator"[];
    preserve_oracle?: boolean;
  };
}
/**
 * 테스트가 요청하는 치트 범위 (권한 부여가 아니다 — 실제 허용은 교집합). max_calls는 루트 실행 전체에서 센다
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "QaCheatAllow".
 */
export interface QaCheatAllow {
  args?: {
    [k: string]: QaCheatArgLimit | undefined;
  };
  id: string;
  max_calls: number;
}
export interface QaCheatArgRange {
  max?: number;
  min?: number;
}
export interface QaCheatArgEnum {
  /**
   * @minItems 1
   */
  enum: [string, ...string[]];
}
/**
 * 이 테스트가 검증하는 주장 revision과 그 검증 노드
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "QaClaim".
 */
export interface QaClaim {
  /**
   * @minItems 1
   */
  assertions: [NodeId, ...NodeId[]];
  id: string;
  rev: number;
}
/**
 * $로 시작하는 키 하나만 가진 객체. 닫힌 목록
 *
 * This interface was referenced by `Graph`'s JSON-Schema
 * via the `definition` "SpecialValue".
 */
export interface SpecialValue {
  $link?: LinkRef;
  /**
   * 해석하지 않고 그대로 쓰는 값
   */
  $literal?: unknown;
  $secret?: SecretKey;
  $setting?: SettingKey;
  $target?: TargetPath;
  [k: string]: unknown | undefined;
}
