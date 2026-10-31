/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

export const daemonRpcSchema: unknown = {
  "$defs": {
    "AgentClientInfo": {
      "additionalProperties": false,
      "description": "에이전트 연결 → 그 에이전트 주체 (id 필수)",
      "properties": {
        "attended": {
          "description": "사람이 지켜보는 연결인가 (생략하면 false)",
          "type": "boolean"
        },
        "id": {
          "description": "에이전트 주체 ID",
          "minLength": 1,
          "type": "string"
        },
        "kind": {
          "const": "agent"
        },
        "name": {
          "type": "string"
        },
        "version": {
          "type": "string"
        }
      },
      "required": [
        "id",
        "kind",
        "name",
        "version"
      ],
      "title": "AgentClientInfo",
      "type": "object"
    },
    "ClientInfo": {
      "oneOf": [
        {
          "$ref": "#/$defs/UiClientInfo"
        },
        {
          "$ref": "#/$defs/AgentClientInfo"
        }
      ],
      "title": "ClientInfo"
    },
    "CropRef": {
      "additionalProperties": false,
      "description": "정지 화면에서 자른 영역 (저장 전 템플릿)",
      "properties": {
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "rect": {
          "$ref": "#/$defs/Rect"
        }
      },
      "required": [
        "frame_id",
        "rect"
      ],
      "title": "CropRef",
      "type": "object"
    },
    "DaemonErrorCode": {
      "description": "JSON-RPC 표준: -32700 parse_error(읽은 뒤 연결을 닫는다), -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32100 request_failed (종류는 error.data.code)",
      "enum": [
        -32700,
        -32600,
        -32601,
        -32602,
        -32603,
        -32100
      ],
      "title": "DaemonErrorCode",
      "type": "integer"
    },
    "DaemonErrorObject": {
      "description": "표준 오류 또는 -32100 (DaemonErrorCode)",
      "oneOf": [
        {
          "$ref": "#/$defs/DaemonStandardError"
        },
        {
          "$ref": "#/$defs/DaemonRequestFailedError"
        }
      ],
      "title": "DaemonErrorObject"
    },
    "DaemonErrorResponse": {
      "additionalProperties": false,
      "properties": {
        "error": {
          "$ref": "#/$defs/DaemonErrorObject"
        },
        "id": {
          "anyOf": [
            {
              "$ref": "#/$defs/RequestId"
            },
            {
              "type": "null"
            }
          ],
          "description": "요청을 읽지 못했으면(JSON 아님·id 없음) null"
        },
        "jsonrpc": {
          "$ref": "#/$defs/JsonRpcVersion"
        }
      },
      "required": [
        "error",
        "id",
        "jsonrpc"
      ],
      "title": "DaemonErrorResponse",
      "type": "object"
    },
    "DaemonRequestFailedError": {
      "additionalProperties": false,
      "description": "앱 오류 -32100 request_failed. data(종류 data.code와 추가 필드)가 반드시 있다",
      "properties": {
        "code": {
          "const": -32100
        },
        "data": {
          "$ref": "#/$defs/RequestFailedData"
        },
        "message": {
          "type": "string"
        }
      },
      "required": [
        "code",
        "data",
        "message"
      ],
      "title": "DaemonRequestFailedError",
      "type": "object"
    },
    "DaemonShutdownParams": {
      "additionalProperties": false,
      "description": "진행 중인 실행이 있으면 run_active로 거부. force면 실행을 취소하고 마무리를 기다린 뒤 끝낸다",
      "properties": {
        "force": {
          "type": "boolean"
        }
      },
      "title": "DaemonShutdownParams",
      "type": "object"
    },
    "DaemonStandardError": {
      "additionalProperties": false,
      "description": "JSON-RPC 표준 오류",
      "properties": {
        "code": {
          "enum": [
            -32700,
            -32600,
            -32601,
            -32602,
            -32603
          ],
          "type": "integer"
        },
        "data": {
          "description": "생략하거나 사람이 읽는 정보",
          "tsType": "unknown"
        },
        "message": {
          "type": "string"
        }
      },
      "required": [
        "code",
        "message"
      ],
      "title": "DaemonStandardError",
      "type": "object"
    },
    "Diagnostic": {
      "additionalProperties": false,
      "description": "검증 진단 (kookabug_core.diagnostics.Diagnostic.to_dict)",
      "properties": {
        "code": {
          "type": "string"
        },
        "file": {
          "type": [
            "null",
            "string"
          ]
        },
        "message": {
          "type": "string"
        },
        "node": {
          "type": [
            "null",
            "string"
          ]
        },
        "pointer": {
          "type": [
            "null",
            "string"
          ]
        },
        "severity": {
          "enum": [
            "error",
            "warning"
          ]
        }
      },
      "required": [
        "code",
        "message",
        "severity"
      ],
      "title": "Diagnostic",
      "type": "object"
    },
    "DocId": {
      "description": "daemon이 연 문서 번호 (연결과 무관)",
      "minLength": 1,
      "title": "DocId",
      "type": "string"
    },
    "EmptyParams": {
      "additionalProperties": false,
      "description": "인자 없음",
      "title": "EmptyParams",
      "type": "object"
    },
    "EmptyResult": {
      "additionalProperties": false,
      "description": "결과 없음",
      "title": "EmptyResult",
      "type": "object"
    },
    "ExitShape": {
      "additionalProperties": false,
      "description": "출구. outputs는 그 출구로 나갈 때 값이 있는 출력 이름",
      "properties": {
        "kind": {
          "enum": [
            "fail",
            "ok"
          ]
        },
        "name": {
          "type": "string"
        },
        "outputs": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "kind",
        "name",
        "outputs"
      ],
      "title": "ExitShape",
      "type": "object"
    },
    "Frame": {
      "additionalProperties": false,
      "description": "편집기 정지 화면 (daemon 프레임 캐시, 최대 16장. 사라지면 frame_expired)",
      "properties": {
        "client_size": {
          "$ref": "#/$defs/Size"
        },
        "dpi": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "height": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "image": {
          "$ref": "#/$defs/ImageRef"
        },
        "width": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "client_size",
        "dpi",
        "frame_id",
        "height",
        "image",
        "width"
      ],
      "title": "Frame",
      "type": "object"
    },
    "GraphChangedParams": {
      "additionalProperties": false,
      "description": "열린 문서의 디스크 revision이 바뀜 (파일이 없어졌으면 null)",
      "properties": {
        "doc_id": {
          "$ref": "#/$defs/DocId"
        },
        "revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "doc_id",
        "revision"
      ],
      "title": "GraphChangedParams",
      "type": "object"
    },
    "GraphCloseParams": {
      "additionalProperties": false,
      "properties": {
        "doc_id": {
          "$ref": "#/$defs/DocId"
        }
      },
      "required": [
        "doc_id"
      ],
      "title": "GraphCloseParams",
      "type": "object"
    },
    "GraphCreateParams": {
      "additionalProperties": false,
      "description": "새 그래프 (canonical 틀). 파일이 있으면 exists. 결과는 graph.open과 같다",
      "properties": {
        "kind": {
          "enum": [
            "subgraph",
            "test"
          ]
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "kind",
        "path"
      ],
      "title": "GraphCreateParams",
      "type": "object"
    },
    "GraphOpenParams": {
      "additionalProperties": false,
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        }
      },
      "required": [
        "path"
      ],
      "title": "GraphOpenParams",
      "type": "object"
    },
    "GraphOpenResult": {
      "additionalProperties": false,
      "description": "value는 Python이 읽은 값. 원문 텍스트는 보내지 않는다",
      "properties": {
        "canonical": {
          "description": "원문이 canonical 형식인가",
          "type": "boolean"
        },
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "doc_id": {
          "$ref": "#/$defs/DocId"
        },
        "revision": {
          "$ref": "#/$defs/Revision"
        },
        "shapes": {
          "$ref": "#/$defs/NodeShapes"
        },
        "value": {
          "$ref": "#/$defs/GraphValue"
        }
      },
      "required": [
        "canonical",
        "diagnostics",
        "doc_id",
        "revision",
        "shapes",
        "value"
      ],
      "title": "GraphOpenResult",
      "type": "object"
    },
    "GraphSaveParams": {
      "additionalProperties": false,
      "description": "값 전체 저장 (M2 계획 2.6). 디스크가 base_revision과 다르면 revision_conflict(force면 덮어씀). 수 규칙(number_out_of_range·number_not_finite)에 걸리면 validation_failed",
      "properties": {
        "base_revision": {
          "$ref": "#/$defs/Revision"
        },
        "doc_id": {
          "$ref": "#/$defs/DocId"
        },
        "force": {
          "type": "boolean"
        },
        "value": {
          "$ref": "#/$defs/GraphValue"
        }
      },
      "required": [
        "base_revision",
        "doc_id",
        "value"
      ],
      "title": "GraphSaveParams",
      "type": "object"
    },
    "GraphSaveResult": {
      "additionalProperties": false,
      "properties": {
        "canonicalized": {
          "description": "canonical이 아니던 원문을 처음 편집해 저장해서 파일 전체가 canonical이 됨",
          "type": "boolean"
        },
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "revision": {
          "$ref": "#/$defs/Revision"
        },
        "wrote": {
          "description": "false면 지금 디스크 바이트와 같아 쓰지 않음 (mtime 그대로)",
          "type": "boolean"
        }
      },
      "required": [
        "canonicalized",
        "diagnostics",
        "revision",
        "wrote"
      ],
      "title": "GraphSaveResult",
      "type": "object"
    },
    "GraphValidateParams": {
      "additionalProperties": false,
      "description": "편집 버퍼 값으로 검증 (루트만 버퍼, 서브그래프·target·화면은 디스크)",
      "properties": {
        "doc_id": {
          "$ref": "#/$defs/DocId"
        },
        "seq": {
          "$ref": "#/$defs/RequestSeq"
        },
        "value": {
          "$ref": "#/$defs/GraphValue"
        }
      },
      "required": [
        "doc_id",
        "seq",
        "value"
      ],
      "title": "GraphValidateParams",
      "type": "object"
    },
    "GraphValidateResult": {
      "additionalProperties": false,
      "properties": {
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "seq": {
          "$ref": "#/$defs/RequestSeq"
        },
        "shapes": {
          "$ref": "#/$defs/NodeShapes"
        }
      },
      "required": [
        "diagnostics",
        "seq",
        "shapes"
      ],
      "title": "GraphValidateResult",
      "type": "object"
    },
    "GraphValue": {
      "description": "그래프 파일 값 전체 (JSON 트리). 편집 중이라 형식이 틀릴 수 있다. JS에서 보낼 때는 반드시 wireStringify로 직렬화한다",
      "title": "GraphValue",
      "tsType": "{ [key: string]: unknown }",
      "type": "object"
    },
    "ImageRef": {
      "description": "이미지는 RPC에 싣지 않는다. cache는 .kookabug/cache/editor/<이름>(kbimg://cache/<이름>), workspace는 워크스페이스 파일(kbimg://ws/<경로>)",
      "oneOf": [
        {
          "additionalProperties": false,
          "properties": {
            "cache": {
              "pattern": "^[A-Za-z0-9_-]+\\.png$",
              "type": "string"
            },
            "height": {
              "maximum": 9007199254740991,
              "minimum": 0,
              "type": "integer"
            },
            "width": {
              "maximum": 9007199254740991,
              "minimum": 0,
              "type": "integer"
            }
          },
          "required": [
            "cache",
            "height",
            "width"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "height": {
              "maximum": 9007199254740991,
              "minimum": 0,
              "type": "integer"
            },
            "width": {
              "maximum": 9007199254740991,
              "minimum": 0,
              "type": "integer"
            },
            "workspace": {
              "$ref": "#/$defs/WorkspacePath"
            }
          },
          "required": [
            "height",
            "width",
            "workspace"
          ],
          "type": "object"
        }
      ],
      "title": "ImageRef"
    },
    "JsonRpcVersion": {
      "const": "2.0",
      "title": "JsonRpcVersion"
    },
    "LeaseChangedParams": {
      "additionalProperties": false,
      "description": "입력 임대권 소유자 (없으면 null)",
      "properties": {
        "owner": {
          "anyOf": [
            {
              "description": "입력 임대권 옆 파일 내용",
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "owner"
      ],
      "title": "LeaseChangedParams",
      "type": "object"
    },
    "MatchInfo": {
      "additionalProperties": false,
      "properties": {
        "click": {
          "items": {
            "maximum": 9007199254740991,
            "minimum": -9007199254740991,
            "type": "integer"
          },
          "maxItems": 2,
          "minItems": 2,
          "type": "array"
        },
        "method": {
          "type": "string"
        },
        "rect": {
          "$ref": "#/$defs/Rect"
        },
        "scale": {
          "type": "number"
        },
        "score": {
          "type": "number"
        }
      },
      "required": [
        "click",
        "method",
        "rect",
        "scale",
        "score"
      ],
      "title": "MatchInfo",
      "type": "object"
    },
    "MethodName": {
      "description": "점으로 나눈 소문자 이름 (예: graph.open)",
      "pattern": "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$",
      "title": "MethodName",
      "type": "string"
    },
    "Methods": {
      "additionalProperties": false,
      "description": "메서드 표 (단일 출처). 메시지가 아니라 타입 표다: params·result 모양, 권한 도구, 렌더러 표면에 내놓는지(false = Electron 주 프로세스 내부용)",
      "properties": {
        "daemon.shutdown": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/DaemonShutdownParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/EmptyResult"
            },
            "tool": {
              "const": "ui_only"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "graph.close": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphCloseParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/EmptyResult"
            },
            "tool": {
              "const": "ui_only"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "graph.create": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphCreateParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/GraphOpenResult"
            },
            "tool": {
              "const": "kb_graph_create"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "graph.open": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphOpenParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/GraphOpenResult"
            },
            "tool": {
              "const": "kb_graph_get"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "graph.save": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphSaveParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/GraphSaveResult"
            },
            "tool": {
              "const": "kb_graph_patch"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "graph.validate": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphValidateParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/GraphValidateResult"
            },
            "tool": {
              "const": "kb_graph_validate"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "nodes.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/NodesListResult"
            },
            "tool": {
              "const": "kb_node_search"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "run.cancel": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/EmptyResult"
            },
            "tool": {
              "const": "kb_run_cancel"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "run.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunListParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunListResult"
            },
            "tool": {
              "const": "kb_run_status"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "run.start": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunStartParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunStartResult"
            },
            "tool": {
              "const": "kb_run_start"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "run.status": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunSummary"
            },
            "tool": {
              "const": "kb_run_status"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "run.subscribe": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunSubscribeParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/EmptyResult"
            },
            "tool": {
              "const": "kb_run_events"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "run.unsubscribe": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/EmptyResult"
            },
            "tool": {
              "const": "ui_only"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "session.hello": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/SessionHelloParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/SessionHelloResult"
            },
            "tool": {
              "const": "ui_only"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "target.capture": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/TargetCaptureParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Frame"
            },
            "tool": {
              "const": "kb_screen_capture"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "target.load_image": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/TargetLoadImageParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Frame"
            },
            "tool": {
              "const": "kb_image_find"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "target.open": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/TargetOpenParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/TargetOpenResult"
            },
            "tool": {
              "const": "kb_image_find"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "target.preview": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/TargetPreviewParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PreviewResult"
            },
            "tool": {
              "const": "kb_image_find"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "target.save": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/TargetSaveParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/TargetSaveResult"
            },
            "tool": {
              "const": "kb_target_create"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "windows.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/WindowsListResult"
            },
            "tool": {
              "const": "kb_screen_capture"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "workspace.info": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/WorkspaceInfoResult"
            },
            "tool": {
              "const": "kb_project_info"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        },
        "workspace.tree": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/WorkspaceTreeResult"
            },
            "tool": {
              "const": "kb_project_info"
            }
          },
          "required": [
            "params",
            "renderer",
            "result",
            "tool"
          ],
          "type": "object"
        }
      },
      "required": [
        "daemon.shutdown",
        "graph.close",
        "graph.create",
        "graph.open",
        "graph.save",
        "graph.validate",
        "nodes.list",
        "run.cancel",
        "run.list",
        "run.start",
        "run.status",
        "run.subscribe",
        "run.unsubscribe",
        "session.hello",
        "target.capture",
        "target.load_image",
        "target.open",
        "target.preview",
        "target.save",
        "windows.list",
        "workspace.info",
        "workspace.tree"
      ],
      "title": "Methods",
      "type": "object"
    },
    "NodeShape": {
      "additionalProperties": false,
      "description": "노드 하나의 핀·출구 (daemon이 계산, 에디터는 계산하지 않는다). unknown이면 레지스트리에 없는 타입·버전이거나 서브그래프를 읽지 못한 호출이라 JSON 키(in·next·다른 노드의 $link)로 만든 대체 모양이다",
      "properties": {
        "exits": {
          "items": {
            "$ref": "#/$defs/ExitShape"
          },
          "type": "array"
        },
        "inputs": {
          "items": {
            "$ref": "#/$defs/PinShape"
          },
          "type": "array"
        },
        "outputs": {
          "items": {
            "$ref": "#/$defs/OutputShape"
          },
          "type": "array"
        },
        "unknown": {
          "type": "boolean"
        }
      },
      "required": [
        "exits",
        "inputs",
        "outputs",
        "unknown"
      ],
      "title": "NodeShape",
      "type": "object"
    },
    "NodeShapes": {
      "additionalProperties": {
        "$ref": "#/$defs/NodeShape"
      },
      "description": "노드 ID → 모양",
      "title": "NodeShapes",
      "type": "object"
    },
    "NodesListResult": {
      "additionalProperties": false,
      "description": "팔레트: 레지스트리의 플러그인마다 노드 스키마 문서 하나 (kookabug_core.palette.export)",
      "properties": {
        "schemas": {
          "items": {
            "description": "노드 스키마 문서 (node-schema 형식 kookabug.nodes/0 그대로)",
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "schemas"
      ],
      "title": "NodesListResult",
      "type": "object"
    },
    "Notification": {
      "additionalProperties": false,
      "description": "응답이 없는 알림 (daemon → 클라이언트). 이름별 모양은 Notifications 표",
      "properties": {
        "jsonrpc": {
          "$ref": "#/$defs/JsonRpcVersion"
        },
        "method": {
          "$ref": "#/$defs/MethodName"
        },
        "params": {
          "$ref": "#/$defs/Params"
        }
      },
      "required": [
        "jsonrpc",
        "method"
      ],
      "title": "Notification",
      "type": "object"
    },
    "Notifications": {
      "additionalProperties": false,
      "description": "알림 표 (daemon → 클라이언트). 타입 표다",
      "properties": {
        "graph.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "lease.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/LeaseChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "run.ended": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunEndedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "run.event": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunEventParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "run.lagged": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunLaggedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "workspace.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/WorkspaceChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        }
      },
      "required": [
        "graph.changed",
        "lease.changed",
        "run.ended",
        "run.event",
        "run.lagged",
        "workspace.changed"
      ],
      "title": "Notifications",
      "type": "object"
    },
    "OutputShape": {
      "additionalProperties": false,
      "description": "출력 핀",
      "properties": {
        "name": {
          "type": "string"
        },
        "nullable": {
          "type": "boolean"
        },
        "type": {
          "type": "string"
        }
      },
      "required": [
        "name",
        "nullable",
        "type"
      ],
      "title": "OutputShape",
      "type": "object"
    },
    "Params": {
      "additionalProperties": true,
      "description": "이름 있는 인자만 쓴다 (배열 params는 쓰지 않는다). 메서드별 모양은 Methods 표의 params",
      "title": "Params",
      "type": "object"
    },
    "PinShape": {
      "additionalProperties": false,
      "description": "입력 핀. required = 기본값도 optional도 없음. 모르는 노드의 핀은 type 'any'",
      "properties": {
        "default": {
          "tsType": "unknown"
        },
        "description": {
          "type": "string"
        },
        "enum": {
          "items": {
            "tsType": "unknown"
          },
          "type": "array"
        },
        "maximum": {
          "type": "number"
        },
        "min_items": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "minimum": {
          "type": "number"
        },
        "name": {
          "type": "string"
        },
        "nullable": {
          "type": "boolean"
        },
        "optional": {
          "type": "boolean"
        },
        "required": {
          "type": "boolean"
        },
        "type": {
          "type": "string"
        }
      },
      "required": [
        "name",
        "nullable",
        "optional",
        "required",
        "type"
      ],
      "title": "PinShape",
      "type": "object"
    },
    "PluginSummary": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "title": {
          "type": "string"
        },
        "version": {
          "type": "string"
        }
      },
      "required": [
        "id",
        "version"
      ],
      "title": "PluginSummary",
      "type": "object"
    },
    "PreviewResult": {
      "additionalProperties": false,
      "description": "kookabug target test --json의 결과 필드(target_cmd.result_json) + 검색 범위 픽셀 + seq. 화면에는 찾음/못 찾음과 (최고) 점수만 쓴다 (candidates는 화면 안 대상 개수가 아니다)",
      "properties": {
        "best": {
          "anyOf": [
            {
              "description": "임계값을 못 넘은 최고 후보",
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        },
        "candidates": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "elapsed_ms": {
          "type": "number"
        },
        "expected_scale": {
          "type": "number"
        },
        "found": {
          "type": "boolean"
        },
        "match": {
          "anyOf": [
            {
              "$ref": "#/$defs/MatchInfo"
            },
            {
              "type": "null"
            }
          ]
        },
        "search": {
          "items": {
            "maximum": 9007199254740991,
            "minimum": -9007199254740991,
            "type": "integer"
          },
          "type": "array"
        },
        "search_rect_px": {
          "$ref": "#/$defs/Rect"
        },
        "seq": {
          "$ref": "#/$defs/RequestSeq"
        },
        "threshold": {
          "type": "number"
        }
      },
      "required": [
        "best",
        "candidates",
        "elapsed_ms",
        "expected_scale",
        "found",
        "match",
        "search",
        "search_rect_px",
        "seq",
        "threshold"
      ],
      "title": "PreviewResult",
      "type": "object"
    },
    "PreviewTemplate": {
      "description": "crop = 편집 중 새로 고른 영역, image = 기존 target 이미지(target 기준 경로)",
      "oneOf": [
        {
          "additionalProperties": false,
          "properties": {
            "crop": {
              "$ref": "#/$defs/CropRef"
            }
          },
          "required": [
            "crop"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "image": {
              "$ref": "#/$defs/WorkspacePath"
            }
          },
          "required": [
            "image"
          ],
          "type": "object"
        }
      ],
      "title": "PreviewTemplate"
    },
    "Principal": {
      "additionalProperties": false,
      "description": "연결의 주체 (kookabug_core.permissions.Principal)",
      "properties": {
        "attended": {
          "type": "boolean"
        },
        "id": {
          "type": "string"
        },
        "kind": {
          "enum": [
            "agent",
            "user"
          ]
        }
      },
      "required": [
        "attended",
        "id",
        "kind"
      ],
      "title": "Principal",
      "type": "object"
    },
    "Rect": {
      "description": "[x, y, w, h] 물리 픽셀",
      "items": {
        "maximum": 9007199254740991,
        "minimum": -9007199254740991,
        "type": "integer"
      },
      "maxItems": 4,
      "minItems": 4,
      "title": "Rect",
      "type": "array"
    },
    "Request": {
      "additionalProperties": false,
      "description": "응답을 기다리는 요청 (클라이언트 → daemon)",
      "properties": {
        "id": {
          "$ref": "#/$defs/RequestId"
        },
        "jsonrpc": {
          "$ref": "#/$defs/JsonRpcVersion"
        },
        "method": {
          "$ref": "#/$defs/MethodName"
        },
        "params": {
          "$ref": "#/$defs/Params"
        }
      },
      "required": [
        "id",
        "jsonrpc",
        "method"
      ],
      "title": "Request",
      "type": "object"
    },
    "RequestFailedCode": {
      "description": "-32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로",
      "enum": [
        "approval_required",
        "capture_failed",
        "capture_timeout",
        "capture_unsupported",
        "doc_not_open",
        "dpi_awareness_unavailable",
        "exists",
        "frame_expired",
        "idempotency_conflict",
        "input_desktop_unavailable",
        "invalid_json",
        "io_error",
        "key_unknown",
        "launch_failed",
        "not_found",
        "ocr_model_corrupt",
        "ocr_model_missing",
        "path_outside_workspace",
        "permission_denied",
        "platform_unavailable",
        "point_obscured",
        "private_path",
        "protocol_mismatch",
        "revision_conflict",
        "run_active",
        "run_busy",
        "run_not_found",
        "shutting_down",
        "target_elevated",
        "target_image_invalid",
        "target_invalid",
        "unauthenticated",
        "validation_failed",
        "window_gone",
        "window_minimized",
        "window_mismatch",
        "window_not_foreground",
        "window_not_found"
      ],
      "title": "RequestFailedCode",
      "type": "string"
    },
    "RequestFailedData": {
      "additionalProperties": false,
      "description": "error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found → run_id, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message",
      "properties": {
        "code": {
          "$ref": "#/$defs/RequestFailedCode"
        },
        "column": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": [
            "integer",
            "null"
          ]
        },
        "decision": {
          "description": "권한 판정 결과 (permission_denied·approval_required). kookabug_core.permissions.Decision 그대로",
          "type": "object"
        },
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "line": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": [
            "integer",
            "null"
          ]
        },
        "message": {
          "type": "string"
        },
        "path": {
          "type": "string"
        },
        "protocol": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "revision": {
          "type": [
            "string",
            "null"
          ]
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "code"
      ],
      "title": "RequestFailedData",
      "type": "object"
    },
    "RequestId": {
      "description": "보낸 쪽이 1부터 붙이는 요청 번호. 응답은 같은 번호로 짝짓는다",
      "maximum": 9007199254740991,
      "minimum": 1,
      "title": "RequestId",
      "type": "integer"
    },
    "RequestSeq": {
      "description": "요청 순번 (graph.validate·target.preview). 응답이 같은 값을 돌려주고, 클라이언트는 마지막으로 보낸 seq의 응답만 쓴다",
      "maximum": 9007199254740991,
      "minimum": 0,
      "title": "RequestSeq",
      "type": "integer"
    },
    "Revision": {
      "description": "그래프 파일 revision: 디스크 바이트의 sha256 hex",
      "pattern": "^[0-9a-f]{64}$",
      "title": "Revision",
      "type": "string"
    },
    "RunEndedParams": {
      "additionalProperties": false,
      "description": "감독자 마무리와 파일 끝까지 보낸 뒤",
      "properties": {
        "last_seq": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "outcome": {
          "$ref": "#/$defs/RunOutcome"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "last_seq",
        "outcome",
        "run_id"
      ],
      "title": "RunEndedParams",
      "type": "object"
    },
    "RunEventParams": {
      "additionalProperties": false,
      "properties": {
        "event": {
          "$ref": "urn:kookabug:events:0",
          "description": "events.jsonl 한 줄 (events.schema.json 형식 그대로)"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        }
      },
      "required": [
        "event",
        "run_id",
        "seq"
      ],
      "title": "RunEventParams",
      "type": "object"
    },
    "RunId": {
      "description": "실행 ID: 소문자·숫자 8자",
      "pattern": "^[a-z0-9]{8}$",
      "title": "RunId",
      "type": "string"
    },
    "RunIdParams": {
      "additionalProperties": false,
      "properties": {
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "run_id"
      ],
      "title": "RunIdParams",
      "type": "object"
    },
    "RunLaggedParams": {
      "additionalProperties": false,
      "description": "송신 큐가 차서 구독을 끊음 → 다시 구독",
      "properties": {
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "run_id"
      ],
      "title": "RunLaggedParams",
      "type": "object"
    },
    "RunListParams": {
      "additionalProperties": false,
      "properties": {
        "limit": {
          "maximum": 1000,
          "minimum": 1,
          "type": "integer"
        }
      },
      "title": "RunListParams",
      "type": "object"
    },
    "RunListResult": {
      "additionalProperties": false,
      "description": "최근 실행부터",
      "properties": {
        "runs": {
          "items": {
            "$ref": "#/$defs/RunSummary"
          },
          "type": "array"
        }
      },
      "required": [
        "runs"
      ],
      "title": "RunListResult",
      "type": "object"
    },
    "RunOutcome": {
      "additionalProperties": false,
      "description": "실행 결과 (run.end 판정·CLI 종료 코드 규칙의 값·마무리한 쪽)",
      "properties": {
        "exit_code": {
          "maximum": 9007199254740991,
          "minimum": -9007199254740991,
          "type": "integer"
        },
        "finalized_by": {
          "enum": [
            "runner",
            "supervisor"
          ]
        },
        "verdict": {
          "enum": [
            "error",
            "fail",
            "pass",
            "skipped"
          ]
        }
      },
      "required": [
        "exit_code",
        "finalized_by",
        "verdict"
      ],
      "title": "RunOutcome",
      "type": "object"
    },
    "RunStartParams": {
      "additionalProperties": false,
      "description": "디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy",
      "properties": {
        "deadline_ms": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "idempotency_key": {
          "minLength": 1,
          "type": "string"
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "profile": {
          "type": [
            "string",
            "null"
          ]
        },
        "settings": {
          "description": "$setting 키 → 값 (CLI --set)",
          "type": "object"
        }
      },
      "required": [
        "path"
      ],
      "title": "RunStartParams",
      "type": "object"
    },
    "RunStartResult": {
      "additionalProperties": false,
      "properties": {
        "graph": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "run_dir": {
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "graph",
        "run_dir",
        "run_id"
      ],
      "title": "RunStartResult",
      "type": "object"
    },
    "RunSubscribeParams": {
      "additionalProperties": false,
      "description": "after_seq = 클라이언트가 실제로 적용한 마지막 seq (처음이면 0). 순서·커서 규칙은 M2 계획 2.8",
      "properties": {
        "after_seq": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "after_seq",
        "run_id"
      ],
      "title": "RunSubscribeParams",
      "type": "object"
    },
    "RunSummary": {
      "additionalProperties": false,
      "description": "실행 요약 (record.reader.read_run). outcome은 끝난 실행만",
      "properties": {
        "graph": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "last_seq": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "outcome": {
          "anyOf": [
            {
              "$ref": "#/$defs/RunOutcome"
            },
            {
              "type": "null"
            }
          ]
        },
        "run_dir": {
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "started_at": {
          "anyOf": [
            {
              "$ref": "#/$defs/Timestamp"
            },
            {
              "type": "null"
            }
          ]
        },
        "state": {
          "enum": [
            "ended",
            "running"
          ]
        }
      },
      "required": [
        "graph",
        "last_seq",
        "outcome",
        "run_dir",
        "run_id",
        "started_at",
        "state"
      ],
      "title": "RunSummary",
      "type": "object"
    },
    "Seq": {
      "description": "저널 안 순번",
      "minimum": 1,
      "title": "Seq",
      "type": "integer"
    },
    "SessionHelloParams": {
      "additionalProperties": false,
      "description": "연결의 첫 메시지 (5초 안). 토큰은 session.json의 token",
      "properties": {
        "client": {
          "$ref": "#/$defs/ClientInfo"
        },
        "protocol": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "token": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        }
      },
      "required": [
        "client",
        "protocol",
        "token"
      ],
      "title": "SessionHelloParams",
      "type": "object"
    },
    "SessionHelloResult": {
      "additionalProperties": false,
      "properties": {
        "daemon_version": {
          "type": "string"
        },
        "principal": {
          "$ref": "#/$defs/Principal"
        },
        "protocol": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "start_id": {
          "type": "string"
        },
        "workspace": {
          "type": "string"
        }
      },
      "required": [
        "daemon_version",
        "principal",
        "protocol",
        "start_id",
        "workspace"
      ],
      "title": "SessionHelloResult",
      "type": "object"
    },
    "Size": {
      "description": "[w, h] 물리 픽셀",
      "items": {
        "maximum": 9007199254740991,
        "minimum": 0,
        "type": "integer"
      },
      "maxItems": 2,
      "minItems": 2,
      "title": "Size",
      "type": "array"
    },
    "SuccessResponse": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "$ref": "#/$defs/RequestId"
        },
        "jsonrpc": {
          "$ref": "#/$defs/JsonRpcVersion"
        },
        "result": {
          "description": "메서드별 결과 (JSON 값)",
          "tsType": "unknown"
        }
      },
      "required": [
        "id",
        "jsonrpc",
        "result"
      ],
      "title": "SuccessResponse",
      "type": "object"
    },
    "TargetCaptureParams": {
      "additionalProperties": false,
      "properties": {
        "window": {
          "description": "창 handle",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "window"
      ],
      "title": "TargetCaptureParams",
      "type": "object"
    },
    "TargetLoadImageParams": {
      "additionalProperties": false,
      "description": "워크스페이스·실행 폴더 PNG",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        }
      },
      "required": [
        "path"
      ],
      "title": "TargetLoadImageParams",
      "type": "object"
    },
    "TargetOpenParams": {
      "additionalProperties": false,
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        }
      },
      "required": [
        "path"
      ],
      "title": "TargetOpenParams",
      "type": "object"
    },
    "TargetOpenResult": {
      "additionalProperties": false,
      "properties": {
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "image": {
          "anyOf": [
            {
              "$ref": "#/$defs/ImageRef"
            },
            {
              "type": "null"
            }
          ]
        },
        "revision": {
          "$ref": "#/$defs/TargetRevision"
        },
        "spec": {
          "description": "target 파일 값 (target 형식)",
          "type": "object"
        }
      },
      "required": [
        "diagnostics",
        "image",
        "revision",
        "spec"
      ],
      "title": "TargetOpenResult",
      "type": "object"
    },
    "TargetPreviewParams": {
      "additionalProperties": false,
      "description": "저장 전 사양으로 그 프레임에서 찾는다. base_path는 image 경로를 풀 target 파일 경로",
      "properties": {
        "base_path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "seq": {
          "$ref": "#/$defs/RequestSeq"
        },
        "spec": {
          "description": "저장 전 target 사양",
          "type": "object"
        },
        "template": {
          "$ref": "#/$defs/PreviewTemplate"
        }
      },
      "required": [
        "frame_id",
        "seq",
        "spec",
        "template"
      ],
      "title": "TargetPreviewParams",
      "type": "object"
    },
    "TargetRevision": {
      "description": "target revision: sha256(JSON 바이트) + ':' + sha256(image가 가리키는 파일 바이트). 이미지가 없으면 'missing' (M2 계획 2.9)",
      "pattern": "^[0-9a-f]{64}:([0-9a-f]{64}|missing)$",
      "title": "TargetRevision",
      "type": "string"
    },
    "TargetSaveParams": {
      "additionalProperties": false,
      "description": "새 파일이면 base_revision null(파일이 있으면 exists), 기존 파일이면 target.open의 revision (M2 계획 2.9 저장 단계). crop이 없으면 이미지를 새로 만들지 않고 지금 image·recorded를 그대로 둔 채 JSON만 저장한다(기존 파일만, 검색 범위는 recorded.client_size 기준)",
      "properties": {
        "base_revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/TargetRevision"
            },
            {
              "type": "null"
            }
          ]
        },
        "crop": {
          "$ref": "#/$defs/CropRef"
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "spec": {
          "type": "object"
        }
      },
      "required": [
        "base_revision",
        "path",
        "spec"
      ],
      "title": "TargetSaveParams",
      "type": "object"
    },
    "TargetSaveResult": {
      "additionalProperties": false,
      "description": "preview = 저장한 파일을 다시 읽어 crop의 정지 화면에서 찾은 결과 (바로 매칭). crop 없이 저장했으면 찾을 정지 화면이 없어 null",
      "properties": {
        "image": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "preview": {
          "anyOf": [
            {
              "$ref": "#/$defs/PreviewResult"
            },
            {
              "type": "null"
            }
          ]
        },
        "revision": {
          "$ref": "#/$defs/TargetRevision"
        },
        "warnings": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "image",
        "preview",
        "revision",
        "warnings"
      ],
      "title": "TargetSaveResult",
      "type": "object"
    },
    "Timestamp": {
      "description": "UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
      "title": "Timestamp",
      "type": "string"
    },
    "ToolName": {
      "description": "권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon.shutdown만 거부)",
      "enum": [
        "kb_graph_create",
        "kb_graph_get",
        "kb_graph_patch",
        "kb_graph_validate",
        "kb_image_find",
        "kb_node_search",
        "kb_project_info",
        "kb_run_cancel",
        "kb_run_events",
        "kb_run_start",
        "kb_run_status",
        "kb_screen_capture",
        "kb_target_create",
        "ui_only"
      ],
      "title": "ToolName",
      "type": "string"
    },
    "TreeEntry": {
      "additionalProperties": false,
      "description": "탐색기 항목. 그래프는 graph_kind, 읽을 수 없으면 problem",
      "properties": {
        "git_ignored": {
          "type": "boolean"
        },
        "graph_kind": {
          "enum": [
            "subgraph",
            "test"
          ]
        },
        "kind": {
          "enum": [
            "agents",
            "graph",
            "lock",
            "other",
            "screen",
            "target",
            "workspace"
          ]
        },
        "name_only": {
          "description": "runs/·.kookabug/처럼 이름만 보이고 안을 나열하지 않는 폴더",
          "type": "boolean"
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "problem": {
          "type": "string"
        },
        "type": {
          "enum": [
            "dir",
            "file"
          ]
        }
      },
      "required": [
        "path",
        "type"
      ],
      "title": "TreeEntry",
      "type": "object"
    },
    "UiClientInfo": {
      "additionalProperties": false,
      "description": "UI 연결 → 판정하지 않는 사용자 주체",
      "properties": {
        "kind": {
          "const": "ui"
        },
        "name": {
          "type": "string"
        },
        "version": {
          "type": "string"
        }
      },
      "required": [
        "kind",
        "name",
        "version"
      ],
      "title": "UiClientInfo",
      "type": "object"
    },
    "WindowInfo": {
      "additionalProperties": false,
      "description": "보이는 최상위 창 하나",
      "properties": {
        "client_size": {
          "$ref": "#/$defs/Size"
        },
        "dpi": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "handle": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "pid": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "process": {
          "type": "string"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "client_size",
        "dpi",
        "handle",
        "pid",
        "process",
        "title"
      ],
      "title": "WindowInfo",
      "type": "object"
    },
    "WindowsListResult": {
      "additionalProperties": false,
      "properties": {
        "windows": {
          "items": {
            "$ref": "#/$defs/WindowInfo"
          },
          "type": "array"
        }
      },
      "required": [
        "windows"
      ],
      "title": "WindowsListResult",
      "type": "object"
    },
    "WorkspaceChangedParams": {
      "additionalProperties": false,
      "description": "1초 폴링으로 바뀐 파일 (mtime·크기)",
      "properties": {
        "paths": {
          "items": {
            "$ref": "#/$defs/WorkspacePath"
          },
          "type": "array"
        }
      },
      "required": [
        "paths"
      ],
      "title": "WorkspaceChangedParams",
      "type": "object"
    },
    "WorkspaceInfoResult": {
      "additionalProperties": false,
      "description": "루트(절대 경로), kookabug.json 요약(프로필 이름·진단), 플러그인, 상태 바용 실행 환경",
      "properties": {
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "plugins": {
          "items": {
            "$ref": "#/$defs/PluginSummary"
          },
          "type": "array"
        },
        "profiles": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "root": {
          "type": "string"
        },
        "runtime": {
          "additionalProperties": false,
          "properties": {
            "capture": {
              "type": [
                "string",
                "null"
              ]
            },
            "ocr": {
              "type": [
                "string",
                "null"
              ]
            },
            "platform": {
              "type": "string"
            },
            "python": {
              "type": "string"
            }
          },
          "required": [
            "capture",
            "ocr",
            "platform",
            "python"
          ],
          "type": "object"
        }
      },
      "required": [
        "diagnostics",
        "plugins",
        "profiles",
        "root",
        "runtime"
      ],
      "title": "WorkspaceInfoResult",
      "type": "object"
    },
    "WorkspacePath": {
      "description": "워크스페이스 루트 기준 경로 ('/' 구분). daemon이 루트 밖·.kookabug/ 안을 거부한다",
      "minLength": 1,
      "title": "WorkspacePath",
      "type": "string"
    },
    "WorkspaceTreeResult": {
      "additionalProperties": false,
      "properties": {
        "entries": {
          "items": {
            "$ref": "#/$defs/TreeEntry"
          },
          "type": "array"
        }
      },
      "required": [
        "entries"
      ],
      "title": "WorkspaceTreeResult",
      "type": "object"
    }
  },
  "$id": "urn:kookabug:daemon-rpc:0",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "description": "UI·에이전트 ↔ daemon JSON-RPC 2.0 메시지 하나 (WebSocket 텍스트 프레임 하나, UTF-8 JSON, 최대 16 MiB). 값 규칙은 M0b와 같다: NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단. 메서드·알림 모양은 $defs의 Methods·Notifications 표",
  "oneOf": [
    {
      "$ref": "#/$defs/Request"
    },
    {
      "$ref": "#/$defs/Notification"
    },
    {
      "$ref": "#/$defs/SuccessResponse"
    },
    {
      "$ref": "#/$defs/DaemonErrorResponse"
    }
  ],
  "title": "DaemonRpcMessage"
};
