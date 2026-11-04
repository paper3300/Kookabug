/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

export const recorderFragmentSchema: unknown = {
  "$defs": {
    "ExitName": {
      "pattern": "^[a-z_][a-z0-9_]*$",
      "title": "ExitName",
      "type": "string"
    },
    "FragmentNode": {
      "additionalProperties": false,
      "description": "노드 하나. in은 그래프 in 핀 값 규칙(특수 값 $link·$secret·$setting·$target·$literal) 그대로이고, $link의 노드 자리는 로컬 ID다 (예: {\"$link\": \"r2.match\"}). next는 출구 → 다음 노드 로컬 ID. 렌더러 insertFragment가 로컬 ID를 새 노드 ID로 바꾸면서 in 안 모든 $link(배열·객체 안쪽까지)와 next를 같이 바꾼다. 비밀값 구간의 글자는 {\"$secret\": \"<키>\"}로만 들어간다 — 원문은 조각 어디에도 없다",
      "properties": {
        "config": {
          "description": "노드 설정 (그래프 Node.config 그대로)",
          "type": "object"
        },
        "in": {
          "additionalProperties": {
            "$ref": "#/$defs/FragmentValue"
          },
          "description": "입력 핀 이름 → 값",
          "type": "object"
        },
        "local_id": {
          "$ref": "#/$defs/LocalId"
        },
        "next": {
          "additionalProperties": {
            "$ref": "#/$defs/LocalId"
          },
          "description": "exec 연결: 출구 이름 → 이 조각 안 다음 노드 로컬 ID",
          "type": "object"
        },
        "title": {
          "type": "string"
        },
        "type": {
          "$ref": "#/$defs/NodeType"
        },
        "version": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "in",
        "local_id",
        "title",
        "type",
        "version"
      ],
      "title": "FragmentNode",
      "type": "object"
    },
    "FragmentObject": {
      "additionalProperties": {
        "$ref": "#/$defs/FragmentValue"
      },
      "description": "특수 값 키가 없는 일반 객체 (값은 다시 Value). 특수 값 키와 다른 키를 섞으면 특수 값도 일반 객체도 아니다. 그 밖의 $로 시작하는 키는 그래프 Value 검사(kookabug_core.recorder.fragment)가 거부한다",
      "not": {
        "anyOf": [
          {
            "required": [
              "$link"
            ]
          },
          {
            "required": [
              "$literal"
            ]
          },
          {
            "required": [
              "$secret"
            ]
          },
          {
            "required": [
              "$setting"
            ]
          },
          {
            "required": [
              "$target"
            ]
          }
        ]
      },
      "title": "FragmentObject",
      "type": "object"
    },
    "FragmentSpecialValue": {
      "description": "특수 값: $ 키 하나만 가진 객체 (그래프 SpecialValue와 같고, $link만 로컬 링크)",
      "oneOf": [
        {
          "additionalProperties": false,
          "properties": {
            "$link": {
              "$ref": "#/$defs/LocalLink"
            }
          },
          "required": [
            "$link"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "$literal": {
              "description": "해석하지 않고 그대로 쓰는 값",
              "tsType": "unknown"
            }
          },
          "required": [
            "$literal"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "$secret": {
              "pattern": "^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$",
              "type": "string"
            }
          },
          "required": [
            "$secret"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "$setting": {
              "pattern": "^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$",
              "type": "string"
            }
          },
          "required": [
            "$setting"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "$target": {
              "pattern": "^[^\\\\]+\\.target\\.json$",
              "type": "string"
            }
          },
          "required": [
            "$target"
          ],
          "type": "object"
        }
      ],
      "title": "FragmentSpecialValue"
    },
    "FragmentValue": {
      "anyOf": [
        {
          "type": [
            "boolean",
            "null",
            "number",
            "string"
          ]
        },
        {
          "items": {
            "$ref": "#/$defs/FragmentValue"
          },
          "type": "array"
        },
        {
          "$ref": "#/$defs/FragmentSpecialValue"
        },
        {
          "$ref": "#/$defs/FragmentObject"
        }
      ],
      "description": "in 핀 값 (그래프 Value 규칙): JSON 상수, 배열, 특수 값, 일반 객체. 특수 값은 배열·객체 안 어디든 온다",
      "title": "FragmentValue"
    },
    "FragmentWarning": {
      "additionalProperties": false,
      "description": "저장 결과에 보일 경고 (예: no_assertion — 검증이 없어 끝까지 가면 통과, attach_start — 재생 전에 게임을 같은 화면으로)",
      "properties": {
        "code": {
          "pattern": "^[a-z][a-z0-9_]*$",
          "type": "string"
        },
        "message": {
          "type": "string"
        }
      },
      "required": [
        "code",
        "message"
      ],
      "title": "FragmentWarning",
      "type": "object"
    },
    "LocalId": {
      "description": "조각 안 로컬 노드 ID (r + 번호). 그래프 노드 ID(n_ + base32)와 겹치지 않는다",
      "pattern": "^r[1-9][0-9]{0,5}$",
      "title": "LocalId",
      "type": "string"
    },
    "LocalLink": {
      "description": "조각 안 $link: <로컬 ID>.<출력 이름>",
      "pattern": "^r[1-9][0-9]{0,5}\\.[a-z_][a-z0-9_]*$",
      "title": "LocalLink",
      "type": "string"
    },
    "NodeType": {
      "description": "<플러그인>.<분류>.<동작>",
      "pattern": "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$",
      "title": "NodeType",
      "type": "string"
    },
    "OpenEnd": {
      "additionalProperties": false,
      "description": "열린 끝점: 삽입이면 렌더러가 원래 다음 노드를 이 노드의 이 출구에 잇는다",
      "properties": {
        "exit": {
          "$ref": "#/$defs/ExitName"
        },
        "node": {
          "$ref": "#/$defs/LocalId"
        }
      },
      "required": [
        "exit",
        "node"
      ],
      "title": "OpenEnd",
      "type": "object"
    }
  },
  "$id": "urn:kookabug:recorder-fragment:0",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "description": "녹화 커밋 조각 (recorder.commit_prepare 결과, M4 계획 2.9). daemon이 로컬 ID로 만들고 렌더러가 그래프에 넣는다(새 테스트·삽입 공용). chain = 실행 차례(첫 항목이 들어가는 노드, 모든 노드가 한 번씩). 새 테스트(mode new_test)는 현재 창을 정하는 노드(first_window_node: core.app.launch 또는 core.window.attach)로 시작하고 open_end가 없다(검증이 없으면 core.test.pass로 끝남). 삽입(mode insert)은 맨 앞 창 노드·종료 노드 없이 open_end로 끝난다",
  "else": {
    "not": {
      "required": [
        "open_end"
      ]
    },
    "required": [
      "first_window_node"
    ]
  },
  "if": {
    "properties": {
      "mode": {
        "const": "insert"
      }
    },
    "required": [
      "mode"
    ]
  },
  "properties": {
    "chain": {
      "items": {
        "$ref": "#/$defs/LocalId"
      },
      "minItems": 1,
      "type": "array"
    },
    "first_window_node": {
      "$ref": "#/$defs/LocalId"
    },
    "mode": {
      "enum": [
        "insert",
        "new_test"
      ]
    },
    "nodes": {
      "items": {
        "$ref": "#/$defs/FragmentNode"
      },
      "minItems": 1,
      "type": "array"
    },
    "open_end": {
      "$ref": "#/$defs/OpenEnd"
    },
    "warnings": {
      "items": {
        "$ref": "#/$defs/FragmentWarning"
      },
      "type": "array"
    }
  },
  "required": [
    "chain",
    "mode",
    "nodes",
    "warnings"
  ],
  "then": {
    "not": {
      "required": [
        "first_window_node"
      ]
    },
    "required": [
      "open_end"
    ]
  },
  "title": "RecorderFragment",
  "type": "object"
};
