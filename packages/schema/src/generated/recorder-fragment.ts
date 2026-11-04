/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 조각 안 로컬 노드 ID (r + 번호). 그래프 노드 ID(n_ + base32)와 겹치지 않는다
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "LocalId".
 */
export type LocalId = string;
/**
 * in 핀 값 (그래프 Value 규칙): JSON 상수, 배열, 특수 값, 일반 객체. 특수 값은 배열·객체 안 어디든 온다
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "FragmentValue".
 */
export type FragmentValue =
  (boolean | null | number | string) | FragmentValue[] | FragmentSpecialValue | FragmentObject;
/**
 * 특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "FragmentSpecialValue".
 */
export type FragmentSpecialValue =
  | {
      $link: LocalLink;
    }
  | {
      /**
       * 해석하지 않고 그대로 쓰는 값
       */
      $literal: unknown;
    }
  | {
      $secret: string;
    }
  | {
      $setting: string;
    }
  | {
      $target: string;
    };
/**
 * 조각 안 $link: <로컬 ID>.<출력 이름>
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "LocalLink".
 */
export type LocalLink = string;
/**
 * <플러그인>.<분류>.<동작>
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "NodeType".
 */
export type NodeType = string;
/**
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "ExitName".
 */
export type ExitName = string;

/**
 * 녹화 커밋 조각 (recorder.commit_prepare 결과, M4 계획 2.9). daemon이 로컬 ID로 만들고 렌더러가 그래프에 넣는다(새 테스트·삽입 공용). chain = 실행 차례(첫 항목이 들어가는 노드, 모든 노드가 한 번씩). 새 테스트(mode new_test)는 현재 창을 정하는 노드(first_window_node: core.app.launch 또는 core.window.attach)로 시작하고 open_end가 없다(검증이 없으면 core.test.pass로 끝남). 삽입(mode insert)은 맨 앞 창 노드·종료 노드 없이 open_end로 끝난다
 */
export interface RecorderFragment {
  /**
   * @minItems 1
   */
  chain: [LocalId, ...LocalId[]];
  first_window_node?: LocalId;
  mode: "insert" | "new_test";
  /**
   * @minItems 1
   */
  nodes: [FragmentNode, ...FragmentNode[]];
  open_end?: OpenEnd;
  warnings: FragmentWarning[];
}
/**
 * 노드 하나. in은 그래프 in 핀 값 규칙(특수 값 $link·$secret·$setting·$target·$literal) 그대로이고, $link의 노드 자리는 로컬 ID다 (예: {"$link": "r2.match"}). next는 출구 → 다음 노드 로컬 ID. 렌더러 insertFragment가 로컬 ID를 새 노드 ID로 바꾸면서 in 안 모든 $link(배열·객체 안쪽까지)와 next를 같이 바꾼다. 비밀값 구간의 글자는 {"$secret": "<키>"}로만 들어간다 — 원문은 조각 어디에도 없다
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "FragmentNode".
 */
export interface FragmentNode {
  /**
   * 노드 설정 (그래프 Node.config 그대로)
   */
  config?: {
    [k: string]: unknown | undefined;
  };
  /**
   * 입력 핀 이름 → 값
   */
  in: {
    [k: string]: FragmentValue | undefined;
  };
  local_id: LocalId;
  /**
   * exec 연결: 출구 이름 → 이 조각 안 다음 노드 로컬 ID
   */
  next?: {
    [k: string]: LocalId | undefined;
  };
  title: string;
  type: NodeType;
  version: number;
}
/**
 * 특수 값 키가 없는 일반 객체 (값은 다시 Value). 특수 값 키와 다른 키를 섞으면 특수 값도 일반 객체도 아니다. 그 밖의 $로 시작하는 키는 그래프 Value 검사(kookabug_core.recorder.fragment)가 거부한다
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "FragmentObject".
 */
export interface FragmentObject {
  [k: string]: FragmentValue | undefined;
}
/**
 * 열린 끝점: 삽입이면 렌더러가 원래 다음 노드를 이 노드의 이 출구에 잇는다
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "OpenEnd".
 */
export interface OpenEnd {
  exit: ExitName;
  node: LocalId;
}
/**
 * 저장 결과에 보일 경고 (예: no_assertion — 검증이 없어 끝까지 가면 통과, attach_start — 재생 전에 게임을 같은 화면으로)
 *
 * This interface was referenced by `RecorderFragment`'s JSON-Schema
 * via the `definition` "FragmentWarning".
 */
export interface FragmentWarning {
  code: string;
  message: string;
}
