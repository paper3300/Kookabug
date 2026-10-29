/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 핀 타입: bool|int|float|string|secret|target|match|rect|point|image|window|process|any, list[T], dict[str,T], <플러그인>.<Type>, 유니온 A|B
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "PinType".
 */
export type PinType = string;
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "ExitName".
 */
export type ExitName = string;
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "PinName".
 */
export type PinName = string;
/**
 * 이 출구로 나갈 때 주는 출력 이름
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "ExitOutputs".
 */
export type ExitOutputs = PinName[];
/**
 * <플러그인>.<분류>.<동작>
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "NodeType".
 */
export type NodeType = string;
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "PluginId".
 */
export type PluginId = string;

/**
 * 플러그인의 노드 스키마 (kookabug-sdk build 산출물, src/<패키지>/kookabug.schema.json). 팔레트와 실행 전 검증이 읽는다
 */
export interface NodeSchemaFile {
  format: "kookabug.nodes/0";
  /**
   * type 순으로 정렬
   */
  nodes: NodeDecl[];
  plugin: PluginInfo;
}
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "NodeDecl".
 */
export interface NodeDecl {
  /**
   * 검증 노드 (판정 5행)
   */
  assertion?: boolean;
  category?: string;
  config?: {
    [k: string]: ConfigDecl | undefined;
  };
  description?: string;
  /**
   * 게임에 영향을 주는 동작. input·process가 있으면 관측 재시도를 선언할 수 없다
   */
  effects?: ("capture" | "input" | "process")[];
  /**
   * 실행기가 직접 처리하는 노드 (core 전용)
   */
  engine?: string;
  /**
   * exec 노드의 출구. 종료 노드는 빈 배열
   */
  exits?: Exit[] | DynamicExits | FromInterface;
  inputs?:
    | {
        [k: string]: InputPin | undefined;
      }
    | FromInterface;
  outputs?:
    | {
        [k: string]: OutputPin | undefined;
      }
    | FromInterface;
  /**
   * exec 핀이 없는 순수 노드
   */
  pure?: boolean;
  retry?: RetryDecl;
  title: string;
  type: NodeType;
  version: number;
}
/**
 * config 항목 하나. default가 없으면 필수
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "ConfigDecl".
 */
export interface ConfigDecl {
  default?: unknown;
  description?: string;
  /**
   * @minItems 1
   */
  enum?: [unknown, ...unknown[]];
  maximum?: number;
  min_items?: number;
  minimum?: number;
  type: PinType;
}
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "Exit".
 */
export interface Exit {
  kind: "fail" | "ok";
  name: ExitName;
  outputs: ExitOutputs;
}
/**
 * config 값(문자열 배열)으로 출구를 만든다. 배열 순서가 우선순위. extra는 고정 출구
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "DynamicExits".
 */
export interface DynamicExits {
  extra?: Exit[];
  from_config: PinName;
  kind: "fail" | "ok";
  outputs: ExitOutputs;
}
/**
 * 핀을 그래프 interface에서 만든다 (graph.entry·exit·call)
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "FromInterface".
 */
export interface FromInterface {
  from_interface: "exits" | "inputs" | "outputs";
}
/**
 * 입력 핀. default도 optional도 없으면 필수
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "InputPin".
 */
export interface InputPin {
  default?: unknown;
  description?: string;
  /**
   * @minItems 1
   */
  enum?: [unknown, ...unknown[]];
  maximum?: number;
  min_items?: number;
  minimum?: number;
  nullable?: boolean;
  /**
   * default 없이 생략할 수 있는 입력. 생략과 null을 노드가 구분한다 (default와 같이 쓰지 않는다)
   */
  optional?: true;
  type: PinType;
}
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "OutputPin".
 */
export interface OutputPin {
  description?: string;
  nullable?: boolean;
  type: PinType;
}
/**
 * 노드 타입의 재시도 선언. 생략하면 never
 *
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "RetryDecl".
 */
export interface RetryDecl {
  mode: "never" | "observation";
  /**
   * 재시도할 수 있는 fail 출구
   *
   * @minItems 1
   */
  on?: [ExitName, ...ExitName[]];
}
/**
 * This interface was referenced by `NodeSchemaFile`'s JSON-Schema
 * via the `definition` "PluginInfo".
 */
export interface PluginInfo {
  id: PluginId;
  title?: string;
  version: string;
}
