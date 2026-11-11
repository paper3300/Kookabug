/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

export const daemonRpcSchema: unknown = {
  "$defs": {
    "AgentCandidate": {
      "additionalProperties": false,
      "description": "감지 표의 에이전트 하나 (kookabug_core.agents.detect). 경로에서 찾기만 하고 설치하지 않는다(npx 어댑터는 연결할 때 받는다)",
      "properties": {
        "args": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "cli": {
          "description": "본체 CLI 실행 파일 이름 (claude·codex 등)",
          "type": "string"
        },
        "cli_path": {
          "description": "찾은 본체 CLI (없으면 null). 본체가 있어도 ACP 어댑터·npx가 없으면 installed는 false",
          "type": [
            "null",
            "string"
          ]
        },
        "command": {
          "type": "string"
        },
        "id": {
          "type": "string"
        },
        "installed": {
          "description": "지금 바로 연결할 수 있음 (via가 null이 아님)",
          "type": "boolean"
        },
        "name": {
          "type": "string"
        },
        "package": {
          "description": "본체만 있을 때 npx로 받을 ACP 어댑터 (이름@고정 판, 없으면 null)",
          "type": [
            "null",
            "string"
          ]
        },
        "path": {
          "description": "찾은 실행 파일 (없으면 null)",
          "type": [
            "null",
            "string"
          ]
        },
        "via": {
          "description": "연결 명령을 찾은 방법: path(어댑터가 PATH에 있음)·npx(고정 판 어댑터를 npx로 받음)·null(연결 불가)",
          "enum": [
            "path",
            "npx",
            null
          ]
        }
      },
      "required": [
        "args",
        "cli",
        "cli_path",
        "command",
        "id",
        "installed",
        "name",
        "package",
        "path",
        "via"
      ],
      "title": "AgentCandidate",
      "type": "object"
    },
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
        "job_token": {
          "description": "M8 3.14·R7: agent-job이 준 작업 토큰. 살아 있는 작업이면 주체에 그 작업이 붙고, 틀리거나 만료·폐기됐거나 다른 작업·주체의 토큰이면 job_token_invalid로 연결을 닫는다",
          "minLength": 16,
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
    "AgentConnection": {
      "additionalProperties": false,
      "description": "daemon에 붙은 agent 연결 하나 (kookabug mcp)",
      "properties": {
        "attended": {
          "type": "boolean"
        },
        "connection": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "id": {
          "type": "string"
        },
        "name": {
          "type": "string"
        },
        "since": {
          "$ref": "#/$defs/Timestamp"
        },
        "toolsets": {
          "items": {
            "$ref": "#/$defs/Toolset"
          },
          "type": "array"
        }
      },
      "required": [
        "attended",
        "connection",
        "id",
        "name",
        "since",
        "toolsets"
      ],
      "title": "AgentConnection",
      "type": "object"
    },
    "AgentConnectionsChangedParams": {
      "additionalProperties": false,
      "description": "agent 연결이 붙거나 끊기거나 툴셋을 켬 (ui 연결에만). 목록은 agent.connections로 다시 읽는다",
      "title": "AgentConnectionsChangedParams",
      "type": "object"
    },
    "AgentConnectionsResult": {
      "additionalProperties": false,
      "properties": {
        "connections": {
          "items": {
            "$ref": "#/$defs/AgentConnection"
          },
          "type": "array"
        }
      },
      "required": [
        "connections"
      ],
      "title": "AgentConnectionsResult",
      "type": "object"
    },
    "AgentProtectCorruptParams": {
      "additionalProperties": false,
      "description": "M7: 에이전트 보호 기록 파일이 손상돼 에이전트에게 창 이미지를 보내지 않는다 (ui 연결에만, daemon 수명에 한 번 — 값 없음). 사람이 파일을 고치거나 지우고 daemon을 다시 시작해야 풀린다",
      "properties": {
        "path": {
          "description": "워크스페이스 기준 보호 기록 파일",
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "title": "AgentProtectCorruptParams",
      "type": "object"
    },
    "AgentSecretRef": {
      "additionalProperties": false,
      "description": "비밀값 저장소의 키 (값은 실행 때 찾는다)",
      "properties": {
        "$secret": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "$secret"
      ],
      "title": "AgentSecretRef",
      "type": "object"
    },
    "AgentSpec": {
      "additionalProperties": false,
      "description": "판단 노드·에이전트 패널이 띄우는 ACP 에이전트 하나. env의 비밀값은 {\"$secret\": 키}로만 쓴다 (실행 때 찾음)",
      "properties": {
        "args": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "command": {
          "minLength": 1,
          "type": "string"
        },
        "env": {
          "additionalProperties": {
            "anyOf": [
              {
                "type": "string"
              },
              {
                "$ref": "#/$defs/AgentSecretRef"
              }
            ]
          },
          "description": "환경 변수 (이름 규칙은 사용자 설정 스키마가 쓰기 때 본다 — 틀리면 settings_invalid)",
          "type": "object"
        },
        "id": {
          "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$",
          "type": "string"
        },
        "name": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "id",
        "name",
        "command"
      ],
      "title": "AgentSpec",
      "type": "object"
    },
    "AgentToolsetsEnableParams": {
      "additionalProperties": false,
      "description": "툴셋을 켠다 (끄기는 없다). 켜도 각 도구의 권한 판정은 그대로다",
      "properties": {
        "toolsets": {
          "items": {
            "$ref": "#/$defs/Toolset"
          },
          "minItems": 1,
          "type": "array"
        }
      },
      "required": [
        "toolsets"
      ],
      "title": "AgentToolsetsEnableParams",
      "type": "object"
    },
    "AgentToolsetsEnableResult": {
      "additionalProperties": false,
      "properties": {
        "enabled": {
          "items": {
            "$ref": "#/$defs/Toolset"
          },
          "type": "array"
        },
        "tools": {
          "description": "이번에 새로 쓸 수 있게 된 도구 이름 (권한 표 이름)",
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "enabled",
        "tools"
      ],
      "title": "AgentToolsetsEnableResult",
      "type": "object"
    },
    "AgentToolsetsResult": {
      "additionalProperties": false,
      "description": "자기 연결의 켜진 툴셋 (M5 계획 D3). ui 연결은 툴셋과 무관해 모두 켜짐으로 답한다",
      "properties": {
        "available": {
          "items": {
            "$ref": "#/$defs/Toolset"
          },
          "type": "array"
        },
        "enabled": {
          "items": {
            "$ref": "#/$defs/Toolset"
          },
          "type": "array"
        }
      },
      "required": [
        "available",
        "enabled"
      ],
      "title": "AgentToolsetsResult",
      "type": "object"
    },
    "AgentsDetectResult": {
      "additionalProperties": false,
      "properties": {
        "candidates": {
          "items": {
            "$ref": "#/$defs/AgentCandidate"
          },
          "type": "array"
        }
      },
      "required": [
        "candidates"
      ],
      "title": "AgentsDetectResult",
      "type": "object"
    },
    "AgentsGetResult": {
      "additionalProperties": false,
      "description": "사용자 설정의 에이전트 목록 (M5 계획 3.12). 파일이 없으면 빈 목록·revision null",
      "properties": {
        "agents": {
          "items": {
            "$ref": "#/$defs/AgentSpec"
          },
          "type": "array"
        },
        "default_agent": {
          "type": [
            "null",
            "string"
          ]
        },
        "problem": {
          "description": "파일 형식이 틀려 목록을 읽지 못했으면 그 이유 (agents.set도 settings_invalid로 거부)",
          "type": [
            "null",
            "string"
          ]
        },
        "revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "사용자 설정 파일 revision (없으면 null)"
        },
        "source": {
          "description": "사용자 설정 파일 경로 (정할 수 없으면 null)",
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "agents",
        "default_agent",
        "problem",
        "revision",
        "source"
      ],
      "title": "AgentsGetResult",
      "type": "object"
    },
    "AgentsSetParams": {
      "additionalProperties": false,
      "description": "사용자 설정의 agents·default_agent만 바꾼다. 다른 키·순서는 보존, revision이 다르면 revision_conflict, 형식이 틀린 파일은 settings_invalid (permissions.set과 같은 쓰기 규칙)",
      "properties": {
        "agents": {
          "items": {
            "$ref": "#/$defs/AgentSpec"
          },
          "type": "array"
        },
        "base_revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "읽은 때의 파일 revision (파일이 없었으면 null)"
        },
        "default_agent": {
          "description": "null이면 키를 지운다",
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "agents",
        "base_revision",
        "default_agent"
      ],
      "title": "AgentsSetParams",
      "type": "object"
    },
    "AgentsSetResult": {
      "additionalProperties": false,
      "properties": {
        "revision": {
          "$ref": "#/$defs/Revision"
        }
      },
      "required": [
        "revision"
      ],
      "title": "AgentsSetResult",
      "type": "object"
    },
    "AppLaunchParams": {
      "additionalProperties": false,
      "description": "게임을 띄운다 (설정 game.executable·game.args·game.cwd, 프로필 계층 포함). 실행·녹화 중이면 거부, 무인 작업(running·ending)·검증 세션 중이면 사람 연결도 job_active·verification_active. 실행 Job 밖. 사람(마법사 2단계 띄우기)도 부른다",
      "properties": {
        "profile": {
          "type": [
            "null",
            "string"
          ]
        }
      },
      "title": "AppLaunchParams",
      "type": "object"
    },
    "AppLaunchResult": {
      "additionalProperties": false,
      "properties": {
        "pid": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "pid"
      ],
      "title": "AppLaunchResult",
      "type": "object"
    },
    "ApprovalAnswer": {
      "description": "사람 확인 답 (M5 3.6). allow_always는 프로젝트 계층(.kookabug/local.json)에 그 도구·인자에만 맞는 allow 규칙을 더한 뒤 실행한다. control 도구에는 받지 않는다(always_not_allowed). allow_session(M7 3.11)은 요청 연결의 지금 탐색 세션 동안 같은 도구·권한 인자(control은 창 제목, screens는 도구 전체)의 ask를 다시 묻지 않는다 — 메모리에만, 세션 끝·연결 끊김·예산 초과·daemon 재시작에 사라지고 deny 규칙이 먼저다. 요청에 session이 없으면 session_not_allowed",
      "enum": [
        "allow_always",
        "allow_once",
        "allow_session",
        "deny"
      ],
      "title": "ApprovalAnswer"
    },
    "ApprovalId": {
      "description": "사람 확인 요청 ID",
      "pattern": "^ap_[0-9a-f]{16}$",
      "title": "ApprovalId",
      "type": "string"
    },
    "ApprovalIdParams": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "$ref": "#/$defs/ApprovalId"
        }
      },
      "required": [
        "id"
      ],
      "title": "ApprovalIdParams",
      "type": "object"
    },
    "ApprovalListResult": {
      "additionalProperties": false,
      "properties": {
        "requests": {
          "items": {
            "$ref": "#/$defs/ApprovalRequest"
          },
          "type": "array"
        }
      },
      "required": [
        "requests"
      ],
      "title": "ApprovalListResult",
      "type": "object"
    },
    "ApprovalPreviewResult": {
      "additionalProperties": false,
      "description": "승인하면 쓰일 그래프 값 (쓰지 않는다, \"캔버스에서 보기\" U10)",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "기준 디스크 revision (새 파일이면 null)"
        },
        "value": {
          "$ref": "#/$defs/GraphValue"
        }
      },
      "required": [
        "path",
        "revision",
        "value"
      ],
      "title": "ApprovalPreviewResult",
      "type": "object"
    },
    "ApprovalRequest": {
      "additionalProperties": false,
      "description": "에이전트의 ask 판정 요청 하나 (approval.requested·approval.list). 기다리는 동안 daemon은 아무것도 쓰지 않는다",
      "properties": {
        "agent": {
          "additionalProperties": false,
          "properties": {
            "id": {
              "type": "string"
            },
            "name": {
              "type": "string"
            }
          },
          "required": [
            "id",
            "name"
          ],
          "title": "ApprovalAgent",
          "type": "object"
        },
        "always_rule": {
          "description": "\"항상 허용\"을 고르면 저장할 규칙 글자. control 도구·규칙으로 쓸 수 없는 인자면 null(단추 없음)",
          "type": [
            "null",
            "string"
          ]
        },
        "arg": {
          "description": "권한 인자 (그래프·target 경로, 실행 그래프 경로, 창 제목 등)",
          "type": "string"
        },
        "connection": {
          "description": "요청한 agent 연결 번호",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "expires_at": {
          "$ref": "#/$defs/Timestamp"
        },
        "id": {
          "$ref": "#/$defs/ApprovalId"
        },
        "method": {
          "$ref": "#/$defs/MethodName"
        },
        "previewable": {
          "description": "approval.preview로 바뀔 그래프 값을 볼 수 있다 (graph.patch·graph.save·graph.create)",
          "type": "boolean"
        },
        "session": {
          "anyOf": [
            {
              "type": "null"
            },
            {
              "additionalProperties": false,
              "properties": {
                "id": {
                  "type": "string"
                },
                "title": {
                  "type": "string"
                }
              },
              "required": [
                "id",
                "title"
              ],
              "title": "ApprovalSession",
              "type": "object"
            }
          ],
          "description": "M7 3.11: \"이 탐색 동안 허용\"(allow_session)을 쓸 수 있으면 요청 연결의 지금 탐색 세션, 아니면 null(단추 없음). control 도구와 screens 변경 도구에만"
        },
        "summary": {
          "description": "사람이 읽는 요약 줄",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "tool": {
          "$ref": "#/$defs/ToolName"
        }
      },
      "required": [
        "agent",
        "always_rule",
        "arg",
        "connection",
        "expires_at",
        "id",
        "method",
        "previewable",
        "session",
        "summary",
        "tool"
      ],
      "title": "ApprovalRequest",
      "type": "object"
    },
    "ApprovalResolvedParams": {
      "additionalProperties": false,
      "properties": {
        "by": {
          "description": "답한 ui 연결(ui:<번호>) 또는 daemon(시간 초과·요청 연결 끊김·탐색 세션 끝)",
          "type": "string"
        },
        "id": {
          "$ref": "#/$defs/ApprovalId"
        },
        "verdict": {
          "enum": [
            "allow_always",
            "allow_once",
            "allow_session",
            "cancelled",
            "deny",
            "timeout"
          ]
        }
      },
      "required": [
        "by",
        "id",
        "verdict"
      ],
      "title": "ApprovalResolvedParams",
      "type": "object"
    },
    "ApprovalRespondParams": {
      "additionalProperties": false,
      "description": "사람 확인 답. 끝난(답함·시간 초과·취소) 요청이면 not_found",
      "properties": {
        "id": {
          "$ref": "#/$defs/ApprovalId"
        },
        "verdict": {
          "$ref": "#/$defs/ApprovalAnswer"
        }
      },
      "required": [
        "id",
        "verdict"
      ],
      "title": "ApprovalRespondParams",
      "type": "object"
    },
    "BreakpointsResult": {
      "additionalProperties": false,
      "description": "debug.breakpoints.get·set 결과, debug.breakpoints.changed 알림 (다른 연결이 바꿨을 때)",
      "properties": {
        "breakpoints": {
          "$ref": "urn:kookabug:breakpoints:0#/$defs/BreakpointList"
        }
      },
      "required": [
        "breakpoints"
      ],
      "title": "BreakpointsResult",
      "type": "object"
    },
    "BreakpointsSetParams": {
      "additionalProperties": false,
      "description": "목록 전체를 바꾼다: .kookabug/breakpoints.json에 원자적으로 쓰고, 진행 중인 UI 실행에 밀어 넣는다(다음 경계부터)",
      "properties": {
        "breakpoints": {
          "$ref": "urn:kookabug:breakpoints:0#/$defs/BreakpointList"
        }
      },
      "required": [
        "breakpoints"
      ],
      "title": "BreakpointsSetParams",
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
    "ControlClickParams": {
      "additionalProperties": false,
      "description": "창을 클릭한다 (point와 target 중 하나). daemon이 한 스텝짜리 제어 실행으로 돌린다 (M5 3.9)",
      "properties": {
        "button": {
          "enum": [
            "left",
            "middle",
            "right"
          ]
        },
        "count": {
          "maximum": 3,
          "minimum": 1,
          "type": "integer"
        },
        "point": {
          "description": "[x, y] 클라이언트 영역 물리 픽셀",
          "items": {
            "maximum": 9007199254740991,
            "minimum": -9007199254740991,
            "type": "integer"
          },
          "maxItems": 2,
          "minItems": 2,
          "type": "array"
        },
        "target": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "window": {
          "description": "창 제목 (정확히 같은 제목의 창, 권한 인자)",
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "window"
      ],
      "title": "ControlClickParams",
      "type": "object"
    },
    "ControlKeyParams": {
      "additionalProperties": false,
      "properties": {
        "keys": {
          "description": "키 하나나 조합 (ctrl+a). 누르고 바로 뗀다",
          "minLength": 1,
          "type": "string"
        },
        "window": {
          "description": "창 제목 (정확히 같은 제목의 창, 권한 인자)",
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "keys",
        "window"
      ],
      "title": "ControlKeyParams",
      "type": "object"
    },
    "ControlResult": {
      "additionalProperties": false,
      "description": "제어 실행 결과 (runs/ 아래 source agent_control 기록). 실패면 error (메시지는 3.8로 가림)",
      "properties": {
        "error": {
          "additionalProperties": false,
          "properties": {
            "code": {
              "type": "string"
            },
            "message": {
              "type": "string"
            }
          },
          "required": [
            "code"
          ],
          "title": "ControlError",
          "type": "object"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "verdict": {
          "$ref": "#/$defs/Verdict"
        }
      },
      "required": [
        "run_id",
        "verdict"
      ],
      "title": "ControlResult",
      "type": "object"
    },
    "ControlTypeParams": {
      "additionalProperties": false,
      "description": "글자 입력 (text와 secret 중 하나). secret은 비밀값 키 — 값은 runner가 찾고 결과·기록·오류에 원문이 없다",
      "properties": {
        "secret": {
          "$ref": "#/$defs/SecretKey"
        },
        "text": {
          "type": "string"
        },
        "window": {
          "description": "창 제목 (정확히 같은 제목의 창, 권한 인자)",
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "window"
      ],
      "title": "ControlTypeParams",
      "type": "object"
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
    "ExploreChangedParams": {
      "additionalProperties": false,
      "description": "M7: 탐색 세션·후보가 바뀜 (ui 연결에만)",
      "properties": {
        "sessions": {
          "items": {
            "$ref": "#/$defs/ExploreSessionInfo"
          },
          "type": "array"
        }
      },
      "required": [
        "sessions"
      ],
      "title": "ExploreChangedParams",
      "type": "object"
    },
    "ExploreCounts": {
      "additionalProperties": false,
      "properties": {
        "moves": {
          "minimum": 0,
          "type": "integer"
        },
        "screens": {
          "minimum": 0,
          "type": "integer"
        },
        "untried": {
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "moves",
        "screens",
        "untried"
      ],
      "title": "ExploreCounts",
      "type": "object"
    },
    "ExploreEndParams": {
      "additionalProperties": false,
      "description": "explore.end (kb_explore_end): 이 연결의 탐색 세션을 끝낸다",
      "title": "ExploreEndParams",
      "type": "object"
    },
    "ExploreEndResult": {
      "additionalProperties": false,
      "properties": {
        "counts": {
          "$ref": "#/$defs/ExploreCounts"
        },
        "session": {
          "type": "string"
        }
      },
      "required": [
        "counts",
        "session"
      ],
      "title": "ExploreEndResult",
      "type": "object"
    },
    "ExploreListParams": {
      "additionalProperties": false,
      "description": "explore.list (사람 화면용): screens/_explored/의 탐색 세션들",
      "title": "ExploreListParams",
      "type": "object"
    },
    "ExploreListResult": {
      "additionalProperties": false,
      "properties": {
        "sessions": {
          "items": {
            "$ref": "#/$defs/ExploreSessionInfo"
          },
          "type": "array"
        }
      },
      "required": [
        "sessions"
      ],
      "title": "ExploreListResult",
      "type": "object"
    },
    "ExploreSessionInfo": {
      "additionalProperties": false,
      "properties": {
        "agent": {
          "type": "string"
        },
        "counts": {
          "$ref": "#/$defs/ExploreCounts"
        },
        "id": {
          "type": "string"
        },
        "max_steps": {
          "minimum": 1,
          "type": "integer"
        },
        "started_at": {
          "type": "string"
        },
        "status": {
          "enum": [
            "active",
            "ended",
            "interrupted"
          ]
        },
        "steps": {
          "minimum": 0,
          "type": "integer"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "agent",
        "counts",
        "id",
        "max_steps",
        "started_at",
        "status",
        "steps",
        "title"
      ],
      "title": "ExploreSessionInfo",
      "type": "object"
    },
    "ExploreStartParams": {
      "additionalProperties": false,
      "description": "explore.start (kb_explore_start, M7 3.4): 탐색 세션 (에이전트 연결마다 하나)",
      "properties": {
        "goal": {
          "type": "string"
        },
        "max_steps": {
          "maximum": 1000,
          "minimum": 1,
          "type": "integer"
        },
        "title": {
          "minLength": 1,
          "type": "string"
        },
        "window": {
          "type": "string"
        }
      },
      "required": [
        "title"
      ],
      "title": "ExploreStartParams",
      "type": "object"
    },
    "ExploreStartResult": {
      "additionalProperties": false,
      "properties": {
        "folder": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "max_steps": {
          "minimum": 1,
          "type": "integer"
        },
        "session": {
          "type": "string"
        }
      },
      "required": [
        "folder",
        "max_steps",
        "session"
      ],
      "title": "ExploreStartResult",
      "type": "object"
    },
    "Frame": {
      "additionalProperties": false,
      "description": "편집기 정지 화면 (daemon 프레임 캐시, 최대 16장. 사라지면 frame_expired)",
      "properties": {
        "agent_image": {
          "additionalProperties": false,
          "description": "agent 연결의 target.capture만 (M5 kb_screen_capture): 긴 변 1568·1 MiB 이하 PNG를 .kookabug/cache/agent/<cache>에 썼다 (읽은 쪽이 지운다)",
          "properties": {
            "cache": {
              "pattern": "^c\\d+/[0-9a-f]{16}\\.png$",
              "type": "string"
            },
            "height": {
              "minimum": 1,
              "type": "integer"
            },
            "width": {
              "minimum": 1,
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
        "protected": {
          "additionalProperties": false,
          "description": "agent 연결의 target.capture만 (M7 3.5a): 이 정지 화면은 보호 판정을 통과하지 못해 이미지를 어디에도 쓰지 않았다(agent_image 없음, image.cache 파일 없음). 사유와 안내만",
          "properties": {
            "hint": {
              "type": "string"
            },
            "reason": {
              "enum": [
                "guard_error",
                "protect_state_unknown",
                "secret_field",
                "secret_field_unknown",
                "sensitive_unchecked",
                "sensitive_visible",
                "window_unknown"
              ]
            }
          },
          "required": [
            "hint",
            "reason"
          ],
          "type": "object"
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
    "GraphCheckParams": {
      "additionalProperties": false,
      "description": "경로로 검증 (kb_graph_validate로 판정, M5). value가 없으면 디스크 값, 있으면 그 값(쓰지 않음)",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "value": {
          "$ref": "#/$defs/GraphValue"
        }
      },
      "required": [
        "path"
      ],
      "title": "GraphCheckParams",
      "type": "object"
    },
    "GraphCheckResult": {
      "additionalProperties": false,
      "properties": {
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        }
      },
      "required": [
        "diagnostics"
      ],
      "title": "GraphCheckResult",
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
        "ops": {
          "description": "만들 틀에 적용할 graph.patch 연산 (M5). 틀리면 파일을 만들지 않는다",
          "items": {
            "$ref": "#/$defs/GraphPatchOp"
          },
          "maxItems": 1000,
          "type": "array"
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
    "GraphListEntry": {
      "additionalProperties": false,
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
        "problem": {
          "type": "string"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "path"
      ],
      "title": "GraphListEntry",
      "type": "object"
    },
    "GraphListParams": {
      "additionalProperties": false,
      "description": "그래프 파일 목록 (kb_graph_list로 판정, M5). 범위는 workspace.tree와 같다",
      "properties": {
        "under": {
          "description": "이 폴더 아래만 (예: tests). 권한 인자",
          "type": "string"
        }
      },
      "title": "GraphListParams",
      "type": "object"
    },
    "GraphListResult": {
      "additionalProperties": false,
      "properties": {
        "graphs": {
          "items": {
            "$ref": "#/$defs/GraphListEntry"
          },
          "type": "array"
        }
      },
      "required": [
        "graphs"
      ],
      "title": "GraphListResult",
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
        "basis": {
          "description": "M8 3.6: 작업 연결이 본 작업 기준 사본이면 working",
          "enum": [
            "working"
          ]
        },
        "canonical": {
          "description": "원문이 canonical 형식인가",
          "type": "boolean"
        },
        "change": {
          "description": "M8 3.6: 그 작업 기준 변경 ID",
          "type": "string"
        },
        "created": {
          "additionalProperties": {
            "type": "string"
          },
          "description": "graph.create ops의 add_node ref → 새 노드 ID (M5, ops를 줬을 때만)",
          "type": "object"
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
        "read_only": {
          "description": "실행 폴더(runs/ 아래)의 스냅샷 그래프라 읽기만 한다. graph.save는 read_only로 거부 (M3, 없으면 false)",
          "type": "boolean"
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
    "GraphPatchNodeRef": {
      "description": "노드 ID 또는 같은 묶음의 add_node ref",
      "minLength": 1,
      "title": "GraphPatchNodeRef",
      "type": "string"
    },
    "GraphPatchOp": {
      "description": "graph.patch 연산 하나 (M5 계획 3.4). 노드 ID는 바꿀 수 없다",
      "oneOf": [
        {
          "additionalProperties": false,
          "description": "새 노드. ID는 daemon이 만든다 (n_ + 8자)",
          "properties": {
            "config": {
              "type": "object"
            },
            "in": {
              "type": "object"
            },
            "op": {
              "const": "add_node"
            },
            "position": {
              "$ref": "#/$defs/GraphPatchPosition"
            },
            "ref": {
              "description": "이 묶음 안 임시 이름 (결과 created에 ref → 새 ID)",
              "minLength": 1,
              "type": "string"
            },
            "title": {
              "type": "string"
            },
            "type": {
              "minLength": 1,
              "type": "string"
            },
            "version": {
              "maximum": 9007199254740991,
              "minimum": 1,
              "type": "integer"
            }
          },
          "required": [
            "op",
            "ref",
            "type"
          ],
          "title": "GraphPatchOp_add_node",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "노드 고치기 (type·id는 바꿀 수 없다)",
          "properties": {
            "config": {
              "description": "키 단위 병합. 값이 null이면 그 키를 지운다",
              "type": "object"
            },
            "id": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            },
            "in": {
              "description": "키 단위 병합. 값이 null이면 그 키를 지운다",
              "type": "object"
            },
            "op": {
              "const": "set_node"
            },
            "record": {
              "type": [
                "object",
                "null"
              ]
            },
            "title": {
              "type": [
                "string",
                "null"
              ]
            }
          },
          "required": [
            "id",
            "op"
          ],
          "title": "GraphPatchOp_set_node",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "노드와 그 노드를 가리키는 next·$link를 지운다",
          "properties": {
            "id": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            },
            "op": {
              "const": "remove_node"
            }
          },
          "required": [
            "id",
            "op"
          ],
          "title": "GraphPatchOp_remove_node",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "exec 연결 (next)",
          "properties": {
            "exit": {
              "pattern": "^[a-z_][a-z0-9_]*$",
              "type": "string"
            },
            "from": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            },
            "op": {
              "const": "connect"
            },
            "to": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            }
          },
          "required": [
            "exit",
            "from",
            "op",
            "to"
          ],
          "title": "GraphPatchOp_connect",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "exec 연결 끊기",
          "properties": {
            "exit": {
              "pattern": "^[a-z_][a-z0-9_]*$",
              "type": "string"
            },
            "from": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            },
            "op": {
              "const": "disconnect"
            }
          },
          "required": [
            "exit",
            "from",
            "op"
          ],
          "title": "GraphPatchOp_disconnect",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "데이터 연결 ($link)",
          "properties": {
            "from": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            },
            "op": {
              "const": "link"
            },
            "output": {
              "pattern": "^[a-z_][a-z0-9_]*$",
              "type": "string"
            },
            "pin": {
              "pattern": "^[a-z_][a-z0-9_]*$",
              "type": "string"
            },
            "to": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            }
          },
          "required": [
            "from",
            "op",
            "output",
            "pin",
            "to"
          ],
          "title": "GraphPatchOp_link",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "데이터 연결 끊기 (그 핀 값을 지운다)",
          "properties": {
            "op": {
              "const": "unlink"
            },
            "pin": {
              "pattern": "^[a-z_][a-z0-9_]*$",
              "type": "string"
            },
            "to": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            }
          },
          "required": [
            "op",
            "pin",
            "to"
          ],
          "title": "GraphPatchOp_unlink",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "레이아웃만",
          "properties": {
            "id": {
              "$ref": "#/$defs/GraphPatchNodeRef"
            },
            "op": {
              "const": "move"
            },
            "position": {
              "$ref": "#/$defs/GraphPatchPosition"
            }
          },
          "required": [
            "id",
            "op",
            "position"
          ],
          "title": "GraphPatchOp_move",
          "type": "object"
        },
        {
          "additionalProperties": false,
          "description": "그래프 머리 (null이면 지운다)",
          "properties": {
            "description": {
              "type": [
                "string",
                "null"
              ]
            },
            "op": {
              "const": "set_meta"
            },
            "title": {
              "type": [
                "string",
                "null"
              ]
            }
          },
          "required": [
            "op"
          ],
          "title": "GraphPatchOp_set_meta",
          "type": "object"
        }
      ],
      "title": "GraphPatchOp"
    },
    "GraphPatchParams": {
      "additionalProperties": false,
      "description": "경로로 그래프를 고친다 (M5 계획 3.4). 모두 적용하거나 하나도 안 한다. 디스크가 base_revision과 다르면 revision_conflict, 연산이 틀리면 patch_invalid, 적용한 값이 그래프 형식에 맞지 않으면 validation_failed",
      "properties": {
        "base_revision": {
          "$ref": "#/$defs/Revision"
        },
        "ops": {
          "items": {
            "$ref": "#/$defs/GraphPatchOp"
          },
          "maxItems": 1000,
          "minItems": 1,
          "type": "array"
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        }
      },
      "required": [
        "base_revision",
        "ops",
        "path"
      ],
      "title": "GraphPatchParams",
      "type": "object"
    },
    "GraphPatchPosition": {
      "additionalProperties": false,
      "properties": {
        "x": {
          "type": "number"
        },
        "y": {
          "type": "number"
        }
      },
      "required": [
        "x",
        "y"
      ],
      "title": "GraphPatchPosition",
      "type": "object"
    },
    "GraphPatchRemovedRef": {
      "additionalProperties": false,
      "properties": {
        "from": {
          "type": "string"
        },
        "key": {
          "description": "next면 출구 이름, link면 핀 이름",
          "type": "string"
        },
        "kind": {
          "enum": [
            "link",
            "next"
          ]
        }
      },
      "required": [
        "from",
        "key",
        "kind"
      ],
      "title": "GraphPatchRemovedRef",
      "type": "object"
    },
    "GraphPatchResult": {
      "additionalProperties": false,
      "properties": {
        "basis": {
          "description": "M8 E3: 작업 기준으로 썼으면 working (팀 파일은 그대로)",
          "enum": [
            "working"
          ]
        },
        "change": {
          "description": "M8 E3: 쓴 작업 기준 변경 ID",
          "type": "string"
        },
        "created": {
          "additionalProperties": {
            "type": "string"
          },
          "description": "add_node ref → 새 노드 ID",
          "type": "object"
        },
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "removed_refs": {
          "description": "remove_node가 함께 지운 연결",
          "items": {
            "$ref": "#/$defs/GraphPatchRemovedRef"
          },
          "type": "array"
        },
        "revision": {
          "$ref": "#/$defs/Revision"
        },
        "wrote": {
          "type": "boolean"
        }
      },
      "required": [
        "created",
        "diagnostics",
        "removed_refs",
        "revision",
        "wrote"
      ],
      "title": "GraphPatchResult",
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
    "Kb8AdoptRequestParams": {
      "additionalProperties": false,
      "description": "adopt.request: 사건의 작업 기준 변경 하나를 자동 채택 조건 1~8로 검사해 팀에 게시 (M8 3.8·R1). 검증 실행은 Kookabug가 고른다",
      "properties": {
        "case": {
          "pattern": "^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        },
        "change": {
          "pattern": "^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        },
        "negatives": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "frame_id": {
                "minLength": 1,
                "type": "string"
              },
              "note": {
                "minLength": 1,
                "type": "string"
              }
            },
            "required": [
              "frame_id",
              "note"
            ],
            "type": "object"
          },
          "maxItems": 16,
          "type": "array"
        }
      },
      "required": [
        "case",
        "change"
      ],
      "title": "Kb8AdoptRequestParams",
      "type": "object"
    },
    "Kb8AdoptRequestResult": {
      "additionalProperties": false,
      "properties": {
        "adopted": {
          "type": "boolean"
        },
        "adoption": {
          "type": [
            "string",
            "null"
          ]
        },
        "failed": {
          "anyOf": [
            {
              "additionalProperties": false,
              "properties": {
                "code": {
                  "type": "string"
                },
                "condition": {
                  "maximum": 8,
                  "minimum": 1,
                  "type": "integer"
                },
                "detail": {
                  "type": "string"
                }
              },
              "required": [
                "code",
                "condition",
                "detail"
              ],
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        },
        "kept": {
          "const": "working"
        },
        "manifest": {
          "type": [
            "string",
            "null"
          ]
        },
        "negatives": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "runs": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "adopted",
        "adoption",
        "failed",
        "kept",
        "manifest",
        "negatives",
        "runs"
      ],
      "title": "Kb8AdoptRequestResult",
      "type": "object"
    },
    "Kb8AdoptRevertParams": {
      "additionalProperties": false,
      "description": "adopt.revert: 채택(자동·수락)을 한 번 되돌린다 (사람 전용). 팀 파일이 채택 뒤 바이트일 때만",
      "properties": {
        "adoption": {
          "pattern": "^a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        }
      },
      "required": [
        "adoption"
      ],
      "title": "Kb8AdoptRevertParams",
      "type": "object"
    },
    "Kb8AdoptRevertResult": {
      "additionalProperties": false,
      "properties": {
        "adoption": {
          "type": "string"
        },
        "files": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "reverted": {
          "type": "string"
        }
      },
      "required": [
        "adoption",
        "files",
        "reverted"
      ],
      "title": "Kb8AdoptRevertResult",
      "type": "object"
    },
    "Kb8AdoptionsListResult": {
      "additionalProperties": false,
      "properties": {
        "adoptions": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "adoptions"
      ],
      "title": "Kb8AdoptionsListResult",
      "type": "object"
    },
    "Kb8CaseGetResult": {
      "additionalProperties": false,
      "properties": {
        "case": {
          "type": "object"
        },
        "sha256": {
          "type": "string"
        }
      },
      "required": [
        "case",
        "sha256"
      ],
      "title": "Kb8CaseGetResult",
      "type": "object"
    },
    "Kb8CaseIdParams": {
      "additionalProperties": false,
      "description": "사건 하나 (cases.get·cases.signals)",
      "properties": {
        "id": {
          "pattern": "^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "title": "Kb8CaseIdParams",
      "type": "object"
    },
    "Kb8CaseRevisionResult": {
      "additionalProperties": false,
      "properties": {
        "case": {
          "type": "string"
        },
        "revision": {
          "type": "integer"
        }
      },
      "required": [
        "case",
        "revision"
      ],
      "title": "Kb8CaseRevisionResult",
      "type": "object"
    },
    "Kb8CaseSignalsResult": {
      "additionalProperties": false,
      "description": "cases.signals (kb_triage_signals): 판단 재료만 모은다. 원인을 판정하지 않는다 (3.13)",
      "properties": {
        "case": {
          "type": "string"
        },
        "claims": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "diff": {
          "anyOf": [
            {
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        },
        "not_comparable": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "reruns": {
          "type": "object"
        },
        "screen": {
          "type": "object"
        },
        "sources": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "case",
        "claims",
        "diff",
        "not_comparable",
        "reruns",
        "screen",
        "sources"
      ],
      "title": "Kb8CaseSignalsResult",
      "type": "object"
    },
    "Kb8CaseSummary": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "revision": {
          "type": "integer"
        },
        "runs": {
          "type": "integer"
        },
        "signature": {
          "type": "string"
        },
        "state": {
          "type": "string"
        },
        "symptom": {
          "type": "object"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "id",
        "revision",
        "runs",
        "signature",
        "state",
        "symptom",
        "title"
      ],
      "title": "Kb8CaseSummary",
      "type": "object"
    },
    "Kb8CasesCloseParams": {
      "additionalProperties": false,
      "description": "cases.close (사람 전용): 사건을 resolved·closed로 (resolution by human)",
      "properties": {
        "base_revision": {
          "minimum": 1,
          "type": "integer"
        },
        "id": {
          "pattern": "^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        },
        "note": {
          "minLength": 1,
          "type": "string"
        },
        "state": {
          "enum": [
            "closed",
            "resolved"
          ]
        }
      },
      "required": [
        "base_revision",
        "id"
      ],
      "title": "Kb8CasesCloseParams",
      "type": "object"
    },
    "Kb8CasesListParams": {
      "additionalProperties": false,
      "description": "cases.list (kb_case_list): 사건 목록",
      "properties": {
        "state": {
          "enum": [
            "closed",
            "needs_info",
            "open",
            "resolved",
            "watching"
          ]
        }
      },
      "title": "Kb8CasesListParams",
      "type": "object"
    },
    "Kb8CasesListResult": {
      "additionalProperties": false,
      "properties": {
        "cases": {
          "items": {
            "$ref": "#/$defs/Kb8CaseSummary"
          },
          "type": "array"
        }
      },
      "required": [
        "cases"
      ],
      "title": "Kb8CasesListResult",
      "type": "object"
    },
    "Kb8CasesOpenParams": {
      "additionalProperties": false,
      "description": "cases.open (kb_case_open): 실패 실행으로 사건을 연다. 같은 시그니처 사건이 있으면 새로 열지 않고 그 사건 runs에 붙인다(attached). 원래 실패 증거는 Kookabug가 고정한다",
      "properties": {
        "run": {
          "minLength": 1,
          "type": "string"
        },
        "title": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "run"
      ],
      "title": "Kb8CasesOpenParams",
      "type": "object"
    },
    "Kb8CasesOpenResult": {
      "additionalProperties": false,
      "properties": {
        "attached": {
          "type": "boolean"
        },
        "case": {
          "type": "string"
        },
        "evidence": {
          "type": [
            "string",
            "null"
          ]
        },
        "hypotheses": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "revision": {
          "type": "integer"
        },
        "signature": {
          "type": "string"
        }
      },
      "required": [
        "attached",
        "case",
        "evidence",
        "hypotheses",
        "revision",
        "signature"
      ],
      "title": "Kb8CasesOpenResult",
      "type": "object"
    },
    "Kb8CasesUpdateParams": {
      "additionalProperties": false,
      "description": "cases.update (kb_case_update): 제목·상태(open·needs_info·watching)·가설·조치·필요 정보·재확인·연결. resolved·closed는 case_resolution_reserved, original·runs·signature·symptom·resolution은 바꾸지 못한다",
      "properties": {
        "base_revision": {
          "minimum": 1,
          "type": "integer"
        },
        "changes": {
          "type": "object"
        },
        "id": {
          "pattern": "^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        }
      },
      "required": [
        "base_revision",
        "changes",
        "id"
      ],
      "title": "Kb8CasesUpdateParams",
      "type": "object"
    },
    "Kb8CheatAdoption": {
      "anyOf": [
        {
          "additionalProperties": false,
          "properties": {
            "at": {
              "minLength": 1,
              "type": "string"
            },
            "by": {
              "const": "human"
            },
            "category": {
              "pattern": "^[a-z][a-z0-9_]{0,63}$",
              "type": "string"
            },
            "digest": {
              "pattern": "^[0-9a-f]{64}$",
              "type": "string"
            }
          },
          "required": [
            "at",
            "by",
            "category",
            "digest"
          ],
          "title": "Kb8CheatAdoptionValue",
          "type": "object"
        },
        {
          "type": "null"
        }
      ],
      "title": "Kb8CheatAdoption"
    },
    "Kb8CheatCategoriesSetParams": {
      "additionalProperties": false,
      "description": "cheats.categories.set: kookabug.json cheats 블록 (사람 전용). base_sha256은 지금 kookabug.json 바이트의 sha256 (다르면 revision_conflict)",
      "properties": {
        "base_sha256": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        },
        "categories": {
          "items": {
            "$ref": "#/$defs/Kb8CheatCategory"
          },
          "type": "array"
        },
        "enabled": {
          "type": "boolean"
        }
      },
      "required": [
        "base_sha256",
        "categories",
        "enabled"
      ],
      "title": "Kb8CheatCategoriesSetParams",
      "type": "object"
    },
    "Kb8CheatCategoriesSetResult": {
      "additionalProperties": false,
      "properties": {
        "sha256": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        }
      },
      "required": [
        "sha256"
      ],
      "title": "Kb8CheatCategoriesSetResult",
      "type": "object"
    },
    "Kb8CheatCategory": {
      "additionalProperties": false,
      "properties": {
        "description": {
          "type": "string"
        },
        "id": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "title": {
          "minLength": 1,
          "type": "string"
        },
        "unattended": {
          "type": "boolean"
        }
      },
      "required": [
        "id",
        "title"
      ],
      "title": "Kb8CheatCategory",
      "type": "object"
    },
    "Kb8CheatSummary": {
      "additionalProperties": false,
      "description": "cheats.list 항목: 정의 요약과 채택 상태 (adopted: 채택 digest가 지금 정의·구현과 같다)",
      "properties": {
        "adopted": {
          "type": "boolean"
        },
        "adoption": {
          "$ref": "#/$defs/Kb8CheatAdoption"
        },
        "args": {
          "type": "object"
        },
        "category": {
          "type": [
            "null",
            "string"
          ]
        },
        "effect": {
          "type": "string"
        },
        "id": {
          "type": "string"
        },
        "problem": {
          "description": "채택할 수 없거나 채택이 무효인 까닭 (없으면 null)",
          "type": [
            "null",
            "string"
          ]
        },
        "rev": {
          "minimum": 1,
          "type": "integer"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "adopted",
        "adoption",
        "args",
        "category",
        "effect",
        "id",
        "problem",
        "rev",
        "title"
      ],
      "title": "Kb8CheatSummary",
      "type": "object"
    },
    "Kb8CheatsAdoptParams": {
      "additionalProperties": false,
      "description": "cheats.adopt: 그 rev 정의를 분류와 함께 채택 (사람 전용)",
      "properties": {
        "category": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "id": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "rev": {
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "category",
        "id",
        "rev"
      ],
      "title": "Kb8CheatsAdoptParams",
      "type": "object"
    },
    "Kb8CheatsAdoptResult": {
      "additionalProperties": false,
      "properties": {
        "adoption": {
          "$ref": "#/$defs/Kb8CheatAdoption"
        },
        "id": {
          "type": "string"
        },
        "revision": {
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "adoption",
        "id",
        "revision"
      ],
      "title": "Kb8CheatsAdoptResult",
      "type": "object"
    },
    "Kb8CheatsListResult": {
      "additionalProperties": false,
      "description": "cheats.list: knowledge/cheats.json 치트와 kookabug.json 치트 정책",
      "properties": {
        "categories": {
          "items": {
            "$ref": "#/$defs/Kb8CheatCategory"
          },
          "type": "array"
        },
        "cheats": {
          "items": {
            "$ref": "#/$defs/Kb8CheatSummary"
          },
          "type": "array"
        },
        "enabled": {
          "type": "boolean"
        },
        "revision": {
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "categories",
        "cheats",
        "enabled",
        "revision"
      ],
      "title": "Kb8CheatsListResult",
      "type": "object"
    },
    "Kb8CheatsUnadoptParams": {
      "additionalProperties": false,
      "description": "cheats.unadopt: 채택 풀기 (사람 전용)",
      "properties": {
        "id": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "rev": {
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "id",
        "rev"
      ],
      "title": "Kb8CheatsUnadoptParams",
      "type": "object"
    },
    "Kb8ConfigBlockParams": {
      "additionalProperties": false,
      "description": "project.automation.set·project.sources.set (사람 전용): kookabug.json의 그 블록만 바꾼다. 지금 sha가 다르면 revision_conflict",
      "properties": {
        "base_sha256": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        },
        "value": {
          "type": [
            "array",
            "object"
          ]
        }
      },
      "required": [
        "base_sha256",
        "value"
      ],
      "title": "Kb8ConfigBlockParams",
      "type": "object"
    },
    "Kb8ConfigBlockResult": {
      "additionalProperties": false,
      "properties": {
        "sha256": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        }
      },
      "required": [
        "sha256"
      ],
      "title": "Kb8ConfigBlockResult",
      "type": "object"
    },
    "Kb8EvidencePinParams": {
      "additionalProperties": false,
      "description": "evidence.pin: 실행 기록에서 가림 처리한 최소 증거 묶음을 knowledge/evidence/에 고정 (지우거나 고치는 도구 없음)",
      "properties": {
        "note": {
          "minLength": 1,
          "type": "string"
        },
        "run": {
          "minLength": 1,
          "type": "string"
        },
        "step": {
          "minLength": 1,
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "note",
        "run"
      ],
      "title": "Kb8EvidencePinParams",
      "type": "object"
    },
    "Kb8EvidencePinResult": {
      "additionalProperties": false,
      "properties": {
        "files": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "id": {
          "type": "string"
        },
        "omitted": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "files",
        "id",
        "omitted"
      ],
      "title": "Kb8EvidencePinResult",
      "type": "object"
    },
    "Kb8JobBeginParams": {
      "additionalProperties": false,
      "description": "job.begin (사람 전용, agent-job CLI): 작업을 만들고 작업 토큰을 준다. 토큰은 이 응답에만 있고 daemon은 해시만 둔다. 부른 연결이 소유 연결이다(R8 — job.heartbeat, 끊기면 작업 끝). 사람 입력 임대권·녹화 중이면 토큰 없이 prep_failed",
      "properties": {
        "agent": {
          "description": "Agent 프로필 이름 (보고 표시용)",
          "pattern": "^[A-Za-z0-9_.-]{1,64}$",
          "type": "string"
        },
        "basis": {
          "enum": [
            "team",
            "working"
          ]
        },
        "budget": {
          "additionalProperties": false,
          "properties": {
            "minutes": {
              "minimum": 1,
              "type": "integer"
            },
            "runs": {
              "minimum": 1,
              "type": "integer"
            }
          },
          "type": "object"
        },
        "playbook": {
          "enum": [
            "author",
            "explore",
            "followup",
            "init",
            "lint",
            "probe",
            "repair",
            "triage"
          ]
        },
        "toolsets": {
          "items": {
            "$ref": "#/$defs/Toolset"
          },
          "type": "array"
        },
        "trigger": {
          "enum": [
            "ci",
            "manual",
            "schedule"
          ]
        },
        "ttl_s": {
          "maximum": 86400,
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "playbook"
      ],
      "title": "Kb8JobBeginParams",
      "type": "object"
    },
    "Kb8JobBeginResult": {
      "additionalProperties": false,
      "properties": {
        "agent_id": {
          "type": "string"
        },
        "expires_at": {
          "type": "string"
        },
        "job": {
          "type": "string"
        },
        "reason": {
          "enum": [
            "input_lease",
            "recording",
            "shutting_down"
          ]
        },
        "report": {
          "type": [
            "string",
            "null"
          ]
        },
        "started_at": {
          "type": "string"
        },
        "state": {
          "enum": [
            "prep_failed",
            "running"
          ]
        },
        "token": {
          "type": "string"
        }
      },
      "required": [
        "job",
        "state"
      ],
      "title": "Kb8JobBeginResult",
      "type": "object"
    },
    "Kb8JobBudgetParams": {
      "additionalProperties": false,
      "description": "M8: 작업 예산 상한에 닿음 (ui 연결에만)",
      "properties": {
        "job": {
          "type": "string"
        },
        "limit": {
          "type": "object"
        },
        "used": {
          "type": "object"
        }
      },
      "required": [
        "job",
        "limit",
        "used"
      ],
      "title": "Kb8JobBudgetParams",
      "type": "object"
    },
    "Kb8JobChangedParams": {
      "additionalProperties": false,
      "description": "M8: 작업 상태가 바뀜 (ui 연결에만)",
      "properties": {
        "job": {
          "type": "string"
        },
        "state": {
          "type": "string"
        },
        "used": {
          "type": "object"
        }
      },
      "required": [
        "job",
        "state",
        "used"
      ],
      "title": "Kb8JobChangedParams",
      "type": "object"
    },
    "Kb8JobEndParams": {
      "additionalProperties": false,
      "description": "job.end (사람 전용): 작업 토큰을 먼저 폐기하고 그 작업의 실행을 취소한다",
      "properties": {
        "job": {
          "pattern": "^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        },
        "reason": {
          "enum": [
            "budget_exhausted",
            "cancelled",
            "done",
            "failed",
            "interrupted",
            "timeout"
          ]
        }
      },
      "required": [
        "job",
        "reason"
      ],
      "title": "Kb8JobEndParams",
      "type": "object"
    },
    "Kb8JobEndResult": {
      "additionalProperties": false,
      "description": "작업 종료 경로(R8) 결과: 토큰 폐기 → 실행·채택 검증 취소 → 감독자 입력 복구 완료 → 보고. 같은 작업을 다시 끝내면 첫 결과. 입력 복구를 확인하지 못했으면 state ending·settled false·report null (보고·끝 알림 없음, 작업 슬롯 유지 — 다시 부르면 같은 완료를 기다린다)",
      "properties": {
        "cancelled": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "job": {
          "type": "string"
        },
        "probe_ok": {
          "description": "작업 연결이 kb_project_info를 불렀다 (agent-job probe)",
          "type": "boolean"
        },
        "report": {
          "type": [
            "string",
            "null"
          ]
        },
        "settled": {
          "type": "boolean"
        },
        "state": {
          "enum": [
            "budget_exhausted",
            "cancelled",
            "done",
            "ending",
            "failed",
            "interrupted",
            "prep_failed"
          ]
        },
        "used": {
          "$ref": "#/$defs/Kb8JobUsed"
        }
      },
      "required": [
        "cancelled",
        "job"
      ],
      "title": "Kb8JobEndResult",
      "type": "object"
    },
    "Kb8JobFinishParams": {
      "additionalProperties": false,
      "description": "job.finish (사람 전용): CLI가 끝났다 → 같은 종료 경로로 끝내고 보고를 만든다",
      "properties": {
        "exit_code": {
          "type": [
            "integer",
            "null"
          ]
        },
        "job": {
          "pattern": "^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        },
        "prep_reason": {
          "description": "prep_failed 사유 (고정 코드, 값·경로 없음)",
          "pattern": "^[a-z_]{1,64}$",
          "type": "string"
        },
        "state": {
          "enum": [
            "budget_exhausted",
            "cancelled",
            "done",
            "failed",
            "interrupted",
            "prep_failed"
          ]
        }
      },
      "required": [
        "job"
      ],
      "title": "Kb8JobFinishParams",
      "type": "object"
    },
    "Kb8JobHeartbeatResult": {
      "additionalProperties": false,
      "properties": {
        "job": {
          "type": "string"
        },
        "state": {
          "const": "running"
        }
      },
      "required": [
        "job",
        "state"
      ],
      "title": "Kb8JobHeartbeatResult",
      "type": "object"
    },
    "Kb8JobIdParams": {
      "additionalProperties": false,
      "properties": {
        "job": {
          "pattern": "^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        }
      },
      "required": [
        "job"
      ],
      "title": "Kb8JobIdParams",
      "type": "object"
    },
    "Kb8JobNoteParams": {
      "additionalProperties": false,
      "description": "job.note (kb_report_note): 작업 토큰 연결 전용. 보고의 Agent 요약 글 (4 KB, 글자 검사)",
      "properties": {
        "text": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "text"
      ],
      "title": "Kb8JobNoteParams",
      "type": "object"
    },
    "Kb8JobNoteResult": {
      "additionalProperties": false,
      "properties": {
        "bytes": {
          "type": "integer"
        },
        "job": {
          "type": "string"
        }
      },
      "required": [
        "bytes",
        "job"
      ],
      "title": "Kb8JobNoteResult",
      "type": "object"
    },
    "Kb8JobUsed": {
      "additionalProperties": false,
      "description": "작업이 쓴 예산 (실행 수는 run.start·자동 채택 검증 실행, 도구 호출 수는 작업 연결 요청)",
      "properties": {
        "minutes": {
          "minimum": 0,
          "type": "integer"
        },
        "runs": {
          "minimum": 0,
          "type": "integer"
        },
        "tool_calls": {
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "minutes",
        "runs",
        "tool_calls"
      ],
      "title": "Kb8JobUsed",
      "type": "object"
    },
    "Kb8JobsActivityEntry": {
      "additionalProperties": false,
      "description": "Agent가 부른 Kookabug 도구 한 번 (activity.jsonl 한 줄). 값·비밀값·긴 인자는 없다 — 대상은 경로·ID·창 제목 같은 짧은 글만",
      "properties": {
        "at": {
          "type": "string"
        },
        "result": {
          "description": "ok 또는 오류 코드",
          "type": "string"
        },
        "seq": {
          "minimum": 1,
          "type": "integer"
        },
        "target": {
          "type": "string"
        },
        "tool": {
          "type": "string"
        }
      },
      "required": [
        "at",
        "result",
        "seq",
        "target",
        "tool"
      ],
      "title": "Kb8JobsActivityEntry",
      "type": "object"
    },
    "Kb8JobsActivityParams": {
      "additionalProperties": false,
      "description": "jobs.activity (사람 전용 읽기, UX1): 작업의 활동 목록과 agent.log 꼬리. after를 주면 그 seq 뒤 줄만",
      "properties": {
        "after": {
          "minimum": 0,
          "type": "integer"
        },
        "job": {
          "pattern": "^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        }
      },
      "required": [
        "job"
      ],
      "title": "Kb8JobsActivityParams",
      "type": "object"
    },
    "Kb8JobsActivityResult": {
      "additionalProperties": false,
      "properties": {
        "entries": {
          "items": {
            "$ref": "#/$defs/Kb8JobsActivityEntry"
          },
          "type": "array"
        },
        "job": {
          "type": "string"
        },
        "log_tail": {
          "description": "비밀값을 가린 agent.log의 마지막 줄들 (최대 200줄, 글자 그대로)",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "started_at": {
          "type": [
            "null",
            "string"
          ]
        },
        "state": {
          "type": "string"
        },
        "used": {
          "anyOf": [
            {
              "$ref": "#/$defs/Kb8JobUsed"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "entries",
        "job",
        "log_tail",
        "started_at",
        "state",
        "used"
      ],
      "title": "Kb8JobsActivityResult",
      "type": "object"
    },
    "Kb8JobsListResult": {
      "additionalProperties": false,
      "properties": {
        "jobs": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "jobs"
      ],
      "title": "Kb8JobsListResult",
      "type": "object"
    },
    "Kb8KnowledgeApplyParams": {
      "additionalProperties": false,
      "description": "knowledge.apply (kb_knowledge_apply): 제한 변경 연산 묶음 (M8 3.3, kookabug.knowledge-ops/0). 전부 적용하거나 아무것도 쓰지 않는다. 같은 request_id 재요청은 지난 결과",
      "properties": {
        "ops": {
          "items": {
            "type": "object"
          },
          "maxItems": 200,
          "minItems": 1,
          "type": "array"
        },
        "request_id": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "ops",
        "request_id"
      ],
      "title": "Kb8KnowledgeApplyParams",
      "type": "object"
    },
    "Kb8KnowledgeApplyResult": {
      "description": "적용 결과 (코어 knowledge.ops.apply 그대로): applied·conflicts·working 등",
      "title": "Kb8KnowledgeApplyResult",
      "type": "object"
    },
    "Kb8KnowledgeChangedParams": {
      "additionalProperties": false,
      "description": "M8: knowledge/·wiki/가 바뀜 (ui 연결에만)",
      "properties": {
        "files": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "files"
      ],
      "title": "Kb8KnowledgeChangedParams",
      "type": "object"
    },
    "Kb8KnowledgeGetParams": {
      "additionalProperties": false,
      "description": "knowledge.get (kb_knowledge_get): 지식 파일(features/<기능>·lessons·cheats·unknowns) 또는 그 항목 하나. 주장 파일은 작업 기준 덧씌움(working)도 함께 준다",
      "properties": {
        "file": {
          "minLength": 1,
          "type": "string"
        },
        "id": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "file"
      ],
      "title": "Kb8KnowledgeGetParams",
      "type": "object"
    },
    "Kb8KnowledgeGetResult": {
      "additionalProperties": false,
      "properties": {
        "doc": {
          "type": "object"
        },
        "file": {
          "type": "string"
        },
        "item": {
          "type": "object"
        },
        "revision": {
          "type": "integer"
        },
        "sha256": {
          "type": [
            "string",
            "null"
          ]
        },
        "working": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "file",
        "revision",
        "sha256",
        "working"
      ],
      "title": "Kb8KnowledgeGetResult",
      "type": "object"
    },
    "Kb8KnowledgeSearchParams": {
      "additionalProperties": false,
      "description": "knowledge.search (kb_knowledge_search): 지식 항목(주장·경험칙·치트·미지수)의 ID·글자에서 찾는다 (대소문자·공백 무시 포함)",
      "properties": {
        "files": {
          "items": {
            "minLength": 1,
            "type": "string"
          },
          "maxItems": 64,
          "type": "array"
        },
        "limit": {
          "maximum": 200,
          "minimum": 1,
          "type": "integer"
        },
        "query": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "query"
      ],
      "title": "Kb8KnowledgeSearchParams",
      "type": "object"
    },
    "Kb8KnowledgeSearchResult": {
      "additionalProperties": false,
      "properties": {
        "matches": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "file": {
                "type": "string"
              },
              "id": {
                "type": "string"
              },
              "kind": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "rev": {
                "type": [
                  "integer",
                  "null"
                ]
              },
              "status": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "text": {
                "type": "string"
              }
            },
            "required": [
              "file",
              "id",
              "kind",
              "rev",
              "status",
              "text"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "truncated": {
          "type": "boolean"
        }
      },
      "required": [
        "matches",
        "truncated"
      ],
      "title": "Kb8KnowledgeSearchResult",
      "type": "object"
    },
    "Kb8LocalSettingsSetParams": {
      "additionalProperties": false,
      "description": "local.settings.set (사람 전용, B7 마법사 2단계): .kookabug/local.json settings의 게임 실행 키만 바꾼다 (이 PC). null이면 키를 지운다",
      "properties": {
        "base_revision": {
          "anyOf": [
            {
              "pattern": "^[0-9a-f]{64}$",
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "description": "주면 local.json revision 대조 (화면을 채울 때 wizard.get local_revision으로 읽은 값, 파일이 없었으면 null). 다르면 revision_conflict"
        },
        "settings": {
          "additionalProperties": false,
          "properties": {
            "game.args": {
              "anyOf": [
                {
                  "items": {
                    "type": "string"
                  },
                  "maxItems": 64,
                  "type": "array"
                },
                {
                  "type": "null"
                }
              ]
            },
            "game.cwd": {
              "anyOf": [
                {
                  "minLength": 1,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ]
            },
            "game.executable": {
              "anyOf": [
                {
                  "minLength": 1,
                  "type": "string"
                },
                {
                  "type": "null"
                }
              ]
            }
          },
          "type": "object"
        },
        "sources": {
          "additionalProperties": {
            "anyOf": [
              {
                "minLength": 1,
                "type": "string"
              },
              {
                "type": "null"
              }
            ]
          },
          "description": "원본 ID → 이 PC 경로 (local.json sources.<id>.path, 6단계 local 원본). null이면 지운다",
          "type": "object"
        }
      },
      "title": "Kb8LocalSettingsSetParams",
      "type": "object"
    },
    "Kb8LocalSettingsSetResult": {
      "additionalProperties": false,
      "properties": {
        "revision": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        }
      },
      "required": [
        "revision"
      ],
      "title": "Kb8LocalSettingsSetResult",
      "type": "object"
    },
    "Kb8LooseResult": {
      "description": "M8 다음 묶음(B5·B7)이 모양을 정하는 결과",
      "title": "Kb8LooseResult",
      "type": "object"
    },
    "Kb8ProjectQaInfoResult": {
      "additionalProperties": false,
      "description": "project.qa_info (kb_project_info): 플레이북 판·원본 상태·자동화 정책·치트 설정·경고 (M8 3.4·3.10·3.12)",
      "properties": {
        "automation": {
          "type": "object"
        },
        "cheats": {
          "type": "object"
        },
        "job": {
          "anyOf": [
            {
              "type": "object"
            },
            {
              "type": "null"
            }
          ]
        },
        "playbooks": {
          "additionalProperties": {
            "minimum": 1,
            "type": "integer"
          },
          "type": "object"
        },
        "sources": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "warnings": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "automation",
        "cheats",
        "job",
        "playbooks",
        "sources",
        "warnings"
      ],
      "title": "Kb8ProjectQaInfoResult",
      "type": "object"
    },
    "Kb8ProjectSetupSetParams": {
      "additionalProperties": false,
      "description": "project.setup.set (사람 전용, B7 마법사 2·8단계): kookabug.json의 record·retention 블록과 게임 설정 키(game.title·game.client_size)를 한 번에 바꾼다. 지금 sha가 다르면 revision_conflict",
      "properties": {
        "base_sha256": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        },
        "record": {
          "type": "object"
        },
        "retention": {
          "type": "object"
        },
        "settings": {
          "additionalProperties": false,
          "properties": {
            "game.client_size": {
              "$ref": "#/$defs/Size"
            },
            "game.title": {
              "minLength": 1,
              "type": "string"
            }
          },
          "type": "object"
        }
      },
      "required": [
        "base_sha256"
      ],
      "title": "Kb8ProjectSetupSetParams",
      "type": "object"
    },
    "Kb8ReportDecideParams": {
      "additionalProperties": false,
      "description": "report.decide (사람 전용, B5): 보고 묶음 결정 → working.accept/reject",
      "properties": {
        "decision": {
          "enum": [
            "accept",
            "reject"
          ]
        },
        "group": {
          "minLength": 1,
          "type": "string"
        },
        "job": {
          "pattern": "^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        }
      },
      "required": [
        "decision",
        "group",
        "job"
      ],
      "title": "Kb8ReportDecideParams",
      "type": "object"
    },
    "Kb8ReportDecideResult": {
      "additionalProperties": false,
      "properties": {
        "decision": {
          "enum": [
            "accept",
            "reject"
          ]
        },
        "group": {
          "type": "string"
        },
        "job": {
          "type": "string"
        },
        "result": {
          "type": "object"
        }
      },
      "required": [
        "decision",
        "group",
        "job",
        "result"
      ],
      "title": "Kb8ReportDecideResult",
      "type": "object"
    },
    "Kb8ReportGetResult": {
      "additionalProperties": false,
      "properties": {
        "report": {
          "type": "object"
        }
      },
      "required": [
        "report"
      ],
      "title": "Kb8ReportGetResult",
      "type": "object"
    },
    "Kb8ReportsListResult": {
      "additionalProperties": false,
      "properties": {
        "reports": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "reports"
      ],
      "title": "Kb8ReportsListResult",
      "type": "object"
    },
    "Kb8SourcesCheckResult": {
      "additionalProperties": false,
      "properties": {
        "sources": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "sources"
      ],
      "title": "Kb8SourcesCheckResult",
      "type": "object"
    },
    "Kb8UnknownsAnswerParams": {
      "additionalProperties": false,
      "description": "unknowns.answer (사람 전용): 미지수에 사람 답을 단다 (basis.type human으로 쓸 수 있다)",
      "properties": {
        "base_rev": {
          "minimum": 1,
          "type": "integer"
        },
        "id": {
          "pattern": "^u-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
          "type": "string"
        },
        "text": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "base_rev",
        "id",
        "text"
      ],
      "title": "Kb8UnknownsAnswerParams",
      "type": "object"
    },
    "Kb8UnknownsAnswerResult": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "rev": {
          "type": "integer"
        }
      },
      "required": [
        "id",
        "rev"
      ],
      "title": "Kb8UnknownsAnswerResult",
      "type": "object"
    },
    "Kb8WikiWriteParams": {
      "additionalProperties": false,
      "description": "wiki.write (kb_wiki_write): 산문 위키 페이지 하나 (wiki/**/*.md, index·log·reports 제외)",
      "properties": {
        "base_sha256": {
          "anyOf": [
            {
              "pattern": "^[0-9a-f]{64}$",
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "path": {
          "minLength": 1,
          "type": "string"
        },
        "text": {
          "type": "string"
        }
      },
      "required": [
        "base_sha256",
        "path",
        "text"
      ],
      "title": "Kb8WikiWriteParams",
      "type": "object"
    },
    "Kb8WikiWriteResult": {
      "additionalProperties": false,
      "properties": {
        "path": {
          "type": "string"
        },
        "rendered_claims": {
          "type": "boolean"
        },
        "sha256": {
          "type": "string"
        },
        "warnings": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "path",
        "rendered_claims",
        "sha256",
        "warnings"
      ],
      "title": "Kb8WikiWriteResult",
      "type": "object"
    },
    "Kb8WizardGetResult": {
      "additionalProperties": false,
      "description": "wizard.get (사람 전용, B7): 마법사 진행과 단계 판정에 쓰는 지금 설정. team_setup = 팀이 첫 설정을 마친 프로젝트(wiki/index.md 있음) — 짧은 마법사 자동 띄우기 조건",
      "properties": {
        "config_sha256": {
          "pattern": "^[0-9a-f]{64}$",
          "type": "string"
        },
        "game": {
          "additionalProperties": false,
          "description": "실효 게임 설정 (local.json이 kookabug.json보다 먼저)",
          "properties": {
            "args": {
              "anyOf": [
                {
                  "items": {
                    "type": "string"
                  },
                  "type": "array"
                },
                {
                  "type": "null"
                }
              ]
            },
            "client_size": {
              "anyOf": [
                {
                  "$ref": "#/$defs/Size"
                },
                {
                  "type": "null"
                }
              ]
            },
            "cwd": {
              "type": [
                "null",
                "string"
              ]
            },
            "executable": {
              "type": [
                "null",
                "string"
              ]
            },
            "title": {
              "type": [
                "null",
                "string"
              ]
            }
          },
          "required": [
            "args",
            "client_size",
            "cwd",
            "executable",
            "title"
          ],
          "type": "object"
        },
        "local_revision": {
          "anyOf": [
            {
              "pattern": "^[0-9a-f]{64}$",
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "description": ".kookabug/local.json revision (없으면 null) — local.settings.set base_revision에 쓴다"
        },
        "local_sources": {
          "additionalProperties": {
            "type": "string"
          },
          "description": "이 PC 원본 경로 (local.json sources.<id>.path, 6단계). 경로만 — 비밀값 없음",
          "type": "object"
        },
        "record": {
          "type": "object"
        },
        "retention": {
          "type": "object"
        },
        "sources": {
          "description": "팀 원본 정의 (kookabug.json sources, config_sha256과 같은 읽기)",
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "team_setup": {
          "type": "boolean"
        },
        "wizard": {
          "anyOf": [
            {
              "$ref": "#/$defs/Kb8WizardState"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "config_sha256",
        "game",
        "local_revision",
        "local_sources",
        "record",
        "retention",
        "sources",
        "team_setup",
        "wizard"
      ],
      "title": "Kb8WizardGetResult",
      "type": "object"
    },
    "Kb8WizardSetParams": {
      "additionalProperties": false,
      "description": "wizard.set (사람 전용, B7): 마법사 진행을 .kookabug/wizard.json에 원자 쓰기",
      "properties": {
        "wizard": {
          "$ref": "#/$defs/Kb8WizardState"
        }
      },
      "required": [
        "wizard"
      ],
      "title": "Kb8WizardSetParams",
      "type": "object"
    },
    "Kb8WizardSetResult": {
      "additionalProperties": false,
      "properties": {
        "wizard": {
          "$ref": "#/$defs/Kb8WizardState"
        }
      },
      "required": [
        "wizard"
      ],
      "title": "Kb8WizardSetResult",
      "type": "object"
    },
    "Kb8WizardState": {
      "additionalProperties": false,
      "description": "마법사 진행 (.kookabug/wizard.json, kookabug.wizard/0, 이 PC). 단계 상태만 둔다 — 입력 값·비밀값·경로를 두지 않는다 (M8 3.17)",
      "properties": {
        "done": {
          "items": {
            "maximum": 9,
            "minimum": 0,
            "type": "integer"
          },
          "type": "array"
        },
        "format": {
          "const": "kookabug.wizard/0"
        },
        "skipped": {
          "items": {
            "maximum": 9,
            "minimum": 0,
            "type": "integer"
          },
          "type": "array"
        },
        "step": {
          "maximum": 9,
          "minimum": 0,
          "type": "integer"
        },
        "warnings": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "code": {
                "pattern": "^[a-z][a-z0-9_]{0,47}(:[A-Za-z0-9_.-]{1,64})?$",
                "type": "string"
              },
              "step": {
                "maximum": 9,
                "minimum": 0,
                "type": "integer"
              }
            },
            "required": [
              "code",
              "step"
            ],
            "type": "object"
          },
          "maxItems": 50,
          "type": "array"
        }
      },
      "required": [
        "done",
        "format",
        "skipped",
        "step",
        "warnings"
      ],
      "title": "Kb8WizardState",
      "type": "object"
    },
    "Kb8WorkingDecideParams": {
      "additionalProperties": false,
      "description": "working.accept·working.reject: 작업 기준 변경(파일)과 작업 주장 rev를 한 거래로 수락하거나 덧씌움에서 뺀다 (사람 전용). claims의 rev는 보고가 가리킨 작업 rev — 지금과 다르면 revision_conflict",
      "properties": {
        "changes": {
          "items": {
            "pattern": "^w-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
            "type": "string"
          },
          "maxItems": 200,
          "type": "array"
        },
        "claims": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "id": {
                "pattern": "^[a-z][a-z0-9_.]{0,127}$",
                "type": "string"
              },
              "rev": {
                "minimum": 1,
                "type": "integer"
              }
            },
            "required": [
              "id",
              "rev"
            ],
            "type": "object"
          },
          "maxItems": 200,
          "type": "array"
        }
      },
      "required": [],
      "title": "Kb8WorkingDecideParams",
      "type": "object"
    },
    "Kb8WorkingDecideResult": {
      "additionalProperties": false,
      "properties": {
        "adoption": {
          "type": [
            "string",
            "null"
          ]
        },
        "changes": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "claims": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "conflicts": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "files": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "adoption",
        "changes",
        "claims",
        "conflicts",
        "files"
      ],
      "title": "Kb8WorkingDecideResult",
      "type": "object"
    },
    "Kb8WorkingListResult": {
      "additionalProperties": false,
      "properties": {
        "changes": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "claims": {
          "items": {
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "changes",
        "claims"
      ],
      "title": "Kb8WorkingListResult",
      "type": "object"
    },
    "LeaseChangedParams": {
      "additionalProperties": false,
      "description": "입력 임대권 소유자 (없으면 null). 녹화 세션이면 kind recorder (상태 바 '입력: 녹화')",
      "properties": {
        "owner": {
          "anyOf": [
            {
              "$ref": "#/$defs/LeaseOwner"
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
    "LeaseDevice": {
      "additionalProperties": false,
      "description": "소유자가 입력을 보내는 장치. 다음 획득자가 앞 소유자의 키를 이 장치로 뗀다. none은 입력 장치가 없는 소유자(녹화) — 뗄 것이 없다",
      "properties": {
        "input_log": {
          "description": "fake 장치의 입력 기록 파일 (절대 경로)",
          "minLength": 1,
          "type": "string"
        },
        "kind": {
          "enum": [
            "fake",
            "none",
            "windows"
          ]
        }
      },
      "required": [
        "kind"
      ],
      "title": "LeaseDevice",
      "type": "object"
    },
    "LeaseFile": {
      "additionalProperties": false,
      "description": "입력 임대권 옆 파일 (%LOCALAPPDATA%\\Kookabug\\input-lease.json, kookabug_core.inputs.lease). 쥔 동안 {owner, clean: false}, 깨끗하게 놓으면 {owner: null, clean: true, last_owner}",
      "properties": {
        "clean": {
          "type": "boolean"
        },
        "last_owner": {
          "$ref": "#/$defs/LeaseOwner"
        },
        "owner": {
          "anyOf": [
            {
              "$ref": "#/$defs/LeaseOwner"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "clean",
        "owner"
      ],
      "title": "LeaseFile",
      "type": "object"
    },
    "LeaseOwner": {
      "additionalProperties": false,
      "description": "입력 임대권 소유자 (옆 파일 input-lease.json의 owner, lease.changed 알림, input_lease_busy 오류). 예전 옆 파일(M0b: kind 둘·device 없음)도 맞는다. created는 FILETIME이라 옆 파일은 정수, 알림·오류는 10진 문자열. 녹화 소유자(recorder)는 실행이 없어 run_id·run_dir이 null(또는 없음)이고 장치는 none",
      "if": {
        "properties": {
          "kind": {
            "const": "recorder"
          }
        },
        "required": [
          "kind"
        ]
      },
      "properties": {
        "created": {
          "anyOf": [
            {
              "minimum": 0,
              "type": "integer"
            },
            {
              "pattern": "^[0-9]+$",
              "type": "string"
            }
          ],
          "description": "프로세스 생성 시각 (Windows FILETIME, 100ns 단위)"
        },
        "device": {
          "anyOf": [
            {
              "$ref": "#/$defs/LeaseDevice"
            },
            {
              "type": "null"
            }
          ]
        },
        "kind": {
          "$ref": "urn:kookabug:events:0#/$defs/LeaseOwnerKind"
        },
        "pid": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "run_dir": {
          "type": [
            "null",
            "string"
          ]
        },
        "run_id": {
          "type": [
            "null",
            "string"
          ]
        },
        "workspace": {
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "created",
        "kind",
        "pid"
      ],
      "then": {
        "properties": {
          "device": {
            "anyOf": [
              {
                "properties": {
                  "kind": {
                    "const": "none"
                  }
                },
                "type": "object"
              },
              {
                "type": "null"
              }
            ]
          },
          "run_dir": {
            "type": "null"
          },
          "run_id": {
            "type": "null"
          }
        }
      },
      "title": "LeaseOwner",
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
        "adopt.request": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8AdoptRequestParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8AdoptRequestResult"
            },
            "tool": {
              "const": "kb_adopt_request"
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
        "adopt.revert": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8AdoptRevertParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8AdoptRevertResult"
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
        "adoptions.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8AdoptionsListResult"
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
        "agent.connections": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/AgentConnectionsResult"
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
        "agent.toolsets.enable": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/AgentToolsetsEnableParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/AgentToolsetsEnableResult"
            },
            "tool": {
              "const": "kb_toolset_enable"
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
        "agent.toolsets.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/AgentToolsetsResult"
            },
            "tool": {
              "const": "kb_toolset_enable"
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
        "agents.detect": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/AgentsDetectResult"
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
        "agents.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/AgentsGetResult"
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
        "agents.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/AgentsSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/AgentsSetResult"
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
        "app.launch": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/AppLaunchParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/AppLaunchResult"
            },
            "tool": {
              "const": "kb_app_launch"
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
        "approval.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ApprovalListResult"
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
        "approval.preview": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ApprovalIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ApprovalPreviewResult"
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
        "approval.respond": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ApprovalRespondParams"
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
        "cases.close": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CasesCloseParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8CaseRevisionResult"
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
        "cases.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CaseIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8CaseGetResult"
            },
            "tool": {
              "const": "kb_case_get"
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
        "cases.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CasesListParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8CasesListResult"
            },
            "tool": {
              "const": "kb_case_list"
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
        "cases.open": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CasesOpenParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8CasesOpenResult"
            },
            "tool": {
              "const": "kb_case_open"
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
        "cases.signals": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CaseIdParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8CaseSignalsResult"
            },
            "tool": {
              "const": "kb_triage_signals"
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
        "cases.update": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CasesUpdateParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8CaseRevisionResult"
            },
            "tool": {
              "const": "kb_case_update"
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
        "cheats.adopt": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CheatsAdoptParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8CheatsAdoptResult"
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
        "cheats.categories.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CheatCategoriesSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8CheatCategoriesSetResult"
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
        "cheats.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8CheatsListResult"
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
        "cheats.unadopt": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8CheatsUnadoptParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8CheatsAdoptResult"
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
        "control.click": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ControlClickParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ControlResult"
            },
            "tool": {
              "const": "kb_input_click"
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
        "control.key": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ControlKeyParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ControlResult"
            },
            "tool": {
              "const": "kb_input_key"
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
        "control.type": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ControlTypeParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ControlResult"
            },
            "tool": {
              "const": "kb_input_type"
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
        "debug.breakpoints.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/BreakpointsResult"
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
        "debug.breakpoints.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/BreakpointsSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/BreakpointsResult"
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
        "evidence.pin": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8EvidencePinParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8EvidencePinResult"
            },
            "tool": {
              "const": "kb_evidence_pin"
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
        "explore.end": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ExploreEndParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ExploreEndResult"
            },
            "tool": {
              "const": "kb_explore_end"
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
        "explore.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ExploreListParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ExploreListResult"
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
        "explore.start": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ExploreStartParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ExploreStartResult"
            },
            "tool": {
              "const": "kb_explore_start"
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
        "graph.check": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphCheckParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/GraphCheckResult"
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
        "graph.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphListParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/GraphListResult"
            },
            "tool": {
              "const": "kb_graph_list"
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
        "graph.patch": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/GraphPatchParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/GraphPatchResult"
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
        "job.begin": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobBeginParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8JobBeginResult"
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
        "job.end": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobEndParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8JobEndResult"
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
        "job.finish": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobFinishParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8JobEndResult"
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
        "job.heartbeat": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobIdParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8JobHeartbeatResult"
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
        "job.note": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobNoteParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8JobNoteResult"
            },
            "tool": {
              "const": "kb_report_note"
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
        "jobs.activity": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobsActivityParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8JobsActivityResult"
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
        "jobs.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8JobsListResult"
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
        "knowledge.apply": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8KnowledgeApplyParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8KnowledgeApplyResult"
            },
            "tool": {
              "const": "kb_knowledge_apply"
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
        "knowledge.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8KnowledgeGetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8KnowledgeGetResult"
            },
            "tool": {
              "const": "kb_knowledge_get"
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
        "knowledge.search": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8KnowledgeSearchParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8KnowledgeSearchResult"
            },
            "tool": {
              "const": "kb_knowledge_search"
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
        "local.settings.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8LocalSettingsSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8LocalSettingsSetResult"
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
        "permissions.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PermissionsGetResult"
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
        "permissions.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PermissionsSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PermissionsSetResult"
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
        "plugins.cancel": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsOpIdParams"
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
        "plugins.gc": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsGcParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsOpResult"
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
        "plugins.install": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsOpIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsOpResult"
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
        "plugins.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsListResult"
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
        "plugins.preview": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsPreviewParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsPreviewResult"
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
        "plugins.relock": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsRelockParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsOpResult"
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
        "plugins.remove": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsRemoveParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsOpResult"
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
        "plugins.sync": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsSyncParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsOpResult"
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
        "plugins.upgrade": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsUpgradeParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/PluginsPreviewResult"
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
        "project.automation.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8ConfigBlockParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ConfigBlockResult"
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
        "project.qa_info": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ProjectQaInfoResult"
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
        "project.setup.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8ProjectSetupSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ConfigBlockResult"
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
        "project.sources.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8ConfigBlockParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ConfigBlockResult"
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
        "recorder.commit_abort": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderCommitTokenParams"
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
        "recorder.commit_finish": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderCommitFinishParams"
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
        "recorder.commit_prepare": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderCommitPrepareParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderCommitPrepareResult"
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
        "recorder.discard": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStateResult"
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
        "recorder.frame": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderFrameParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderFrameResult"
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
        "recorder.insert_check": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderInsertCheckParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStepResult"
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
        "recorder.pause": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStateResult"
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
        "recorder.resume": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStateResult"
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
        "recorder.start": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderStartParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStateResult"
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
        "recorder.state": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStateResult"
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
        "recorder.step.update": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderStepUpdateParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStepResult"
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
        "recorder.steps": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderStepsParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStepsResult"
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
        "recorder.stop": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderStateResult"
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
        "recorder.target.materialize": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderMaterializeParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RecorderWrittenTarget"
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
        "report.decide": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8ReportDecideParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ReportDecideResult"
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
        "reports.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ReportGetResult"
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
        "reports.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8ReportsListResult"
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
        "run.artifact": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunArtifactParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/RunArtifactResult"
            },
            "tool": {
              "const": "kb_run_artifact_get"
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
        "run.children": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunChildrenParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunChildrenResult"
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
        "run.compare": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunCompareParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunCompareResult"
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
        "run.diff": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunDiffParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/RunDiffResult"
            },
            "tool": {
              "const": "kb_run_compare"
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
        "run.events": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunEventsParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/RunEventsResult"
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
        "run.export": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunExportParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/RunExportResult"
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
        "run.failure": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/RunFailureResult"
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
        "run.file": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunFileParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunFileResult"
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
        "run.index": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunIndexResult"
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
        "run.pause": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunControlResult"
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
        "run.restart": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunStartResult"
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
        "run.resume": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunResumeIdParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunControlResult"
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
        "run.search": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunSearchParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/RunSearchResult"
            },
            "tool": {
              "const": "kb_log_search"
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
              "$ref": "#/$defs/RunStatusResult"
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
        "run.step": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RunStepParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/RunStepResult"
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
        "screen.read_text": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreenReadTextParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/TargetReadTextResult"
            },
            "tool": {
              "const": "kb_ocr_read"
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
        "screens.check": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensCheckParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ScreensCheckResult"
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
        "screens.discard": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensDiscardParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ScreensDiscardResult"
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
        "screens.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensGetParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ScreensGetResult"
            },
            "tool": {
              "const": "kb_screen_get"
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
        "screens.identify": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensIdentifyParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ScreensIdentifyResult"
            },
            "tool": {
              "const": "kb_screen_identify"
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
        "screens.layout_get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ScreensLayout"
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
        "screens.layout_set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensLayoutSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ScreensLayout"
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
        "screens.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensListParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ScreensListResult"
            },
            "tool": {
              "const": "kb_screen_list"
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
        "screens.map": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ScreensMapResult"
            },
            "tool": {
              "const": "kb_screen_list"
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
        "screens.promote": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensPromoteParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/ScreensPromoteResult"
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
        "screens.save": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensSaveParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/ScreensSaveResult"
            },
            "tool": {
              "const": "kb_screen_save"
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
        "secrets.create": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/SecretsCreateParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/SecretKeyInfo"
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
        "secrets.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/SecretsListResult"
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
        "setting.propose": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Ux2SettingProposeParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Ux2SettingProposeResult"
            },
            "tool": {
              "const": "kb_setting_propose"
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
        "sources.check": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8SourcesCheckResult"
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
        "sources.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Ux2SourcesListParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Ux2SourcesListResult"
            },
            "tool": {
              "const": "kb_source_list"
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
        "sources.read": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Ux2SourcesReadParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Ux2SourcesReadResult"
            },
            "tool": {
              "const": "kb_source_read"
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
        "target.read_text": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/TargetReadTextParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/TargetReadTextResult"
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
        "unknowns.answer": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8UnknownsAnswerParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8UnknownsAnswerResult"
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
        "wiki.write": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8WikiWriteParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8WikiWriteResult"
            },
            "tool": {
              "const": "kb_wiki_write"
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
        "wizard.get": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8WizardGetResult"
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
        "wizard.set": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8WizardSetParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/Kb8WizardSetResult"
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
        "working.accept": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8WorkingDecideParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8WorkingDecideResult"
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
        "working.list": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8WorkingListResult"
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
        "working.reject": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8WorkingDecideParams"
            },
            "renderer": {
              "const": false
            },
            "result": {
              "$ref": "#/$defs/Kb8WorkingDecideResult"
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
        "workspace.read": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/WorkspaceReadParams"
            },
            "renderer": {
              "const": true
            },
            "result": {
              "$ref": "#/$defs/WorkspaceReadResult"
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
        "agent.connections",
        "agent.toolsets.enable",
        "agent.toolsets.get",
        "agents.detect",
        "agents.get",
        "agents.set",
        "app.launch",
        "approval.list",
        "approval.preview",
        "approval.respond",
        "control.click",
        "control.key",
        "control.type",
        "daemon.shutdown",
        "debug.breakpoints.get",
        "debug.breakpoints.set",
        "graph.check",
        "graph.close",
        "graph.create",
        "graph.list",
        "graph.open",
        "graph.patch",
        "graph.save",
        "graph.validate",
        "nodes.list",
        "permissions.get",
        "permissions.set",
        "plugins.cancel",
        "plugins.gc",
        "plugins.install",
        "plugins.list",
        "plugins.preview",
        "plugins.relock",
        "plugins.remove",
        "plugins.sync",
        "plugins.upgrade",
        "recorder.commit_abort",
        "recorder.commit_finish",
        "recorder.commit_prepare",
        "recorder.discard",
        "recorder.frame",
        "recorder.insert_check",
        "recorder.pause",
        "recorder.resume",
        "recorder.start",
        "recorder.state",
        "recorder.step.update",
        "recorder.steps",
        "recorder.stop",
        "recorder.target.materialize",
        "run.artifact",
        "run.cancel",
        "run.children",
        "run.compare",
        "run.diff",
        "run.events",
        "run.export",
        "run.failure",
        "run.file",
        "run.index",
        "run.list",
        "run.pause",
        "run.restart",
        "run.resume",
        "run.search",
        "run.start",
        "run.status",
        "run.step",
        "run.subscribe",
        "run.unsubscribe",
        "screen.read_text",
        "screens.get",
        "screens.list",
        "screens.identify",
        "screens.save",
        "explore.start",
        "explore.end",
        "explore.list",
        "screens.map",
        "screens.check",
        "screens.promote",
        "screens.discard",
        "screens.layout_get",
        "screens.layout_set",
        "secrets.create",
        "secrets.list",
        "session.hello",
        "target.capture",
        "target.load_image",
        "target.open",
        "target.preview",
        "target.read_text",
        "target.save",
        "windows.list",
        "workspace.info",
        "workspace.read",
        "workspace.tree",
        "cheats.adopt",
        "cheats.categories.set",
        "cheats.list",
        "cheats.unadopt",
        "adopt.request",
        "adopt.revert",
        "adoptions.list",
        "evidence.pin",
        "working.accept",
        "working.list",
        "working.reject",
        "knowledge.search",
        "knowledge.get",
        "knowledge.apply",
        "wiki.write",
        "cases.list",
        "cases.get",
        "cases.signals",
        "cases.open",
        "cases.update",
        "cases.close",
        "job.note",
        "job.begin",
        "job.end",
        "job.finish",
        "jobs.list",
        "jobs.activity",
        "reports.list",
        "reports.get",
        "report.decide",
        "unknowns.answer",
        "project.automation.set",
        "project.sources.set",
        "sources.check",
        "wizard.get",
        "wizard.set",
        "job.heartbeat",
        "project.qa_info",
        "project.setup.set",
        "local.settings.set",
        "sources.list",
        "sources.read",
        "setting.propose"
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
      "description": "팔레트: 레지스트리의 플러그인마다 노드 스키마 문서 하나 (kookabug_core.palette.export). M6: plugins = 설치 플러그인 요약 (잠금이 없거나 깨졌으면 빈 목록)",
      "properties": {
        "plugins": {
          "items": {
            "$ref": "#/$defs/PluginInstalled"
          },
          "type": "array"
        },
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
        "agent.connections.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/AgentConnectionsChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "agent.protect_corrupt": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/AgentProtectCorruptParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "approval.requested": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ApprovalRequest"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "approval.resolved": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ApprovalResolvedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "debug.breakpoints.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/BreakpointsResult"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "explore.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ExploreChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
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
        "job.budget": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobBudgetParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "job.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8JobChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "knowledge.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/Kb8KnowledgeChangedParams"
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
        "plugins.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "plugins.done": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsDoneParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "plugins.progress": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/PluginsProgressParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "recorder.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/RecorderChangedParams"
            }
          },
          "required": [
            "params"
          ],
          "type": "object"
        },
        "reports.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/EmptyParams"
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
        "screens.changed": {
          "additionalProperties": false,
          "properties": {
            "params": {
              "$ref": "#/$defs/ScreensChangedParams"
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
        "agent.connections.changed",
        "agent.protect_corrupt",
        "explore.changed",
        "screens.changed",
        "approval.requested",
        "approval.resolved",
        "debug.breakpoints.changed",
        "graph.changed",
        "lease.changed",
        "plugins.changed",
        "plugins.done",
        "plugins.progress",
        "recorder.changed",
        "run.ended",
        "run.event",
        "run.lagged",
        "workspace.changed",
        "knowledge.changed",
        "reports.changed",
        "job.changed",
        "job.budget"
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
    "PermissionVerdict": {
      "description": "권한 판정 값",
      "enum": [
        "allow",
        "ask",
        "deny"
      ],
      "title": "PermissionVerdict"
    },
    "PermissionsGetResult": {
      "additionalProperties": false,
      "properties": {
        "layers": {
          "description": "계층별 파일 값 (ui 연결만. agent 연결에는 자기 판정 요약 tools만)",
          "items": {
            "$ref": "#/$defs/PermissionsLayer"
          },
          "type": "array"
        },
        "principal": {
          "$ref": "#/$defs/Principal"
        },
        "tools": {
          "description": "도구별 실효 판정. agent 연결은 자기 주체, ui 연결은 사람이 지켜보는 에이전트(attended) 기준",
          "items": {
            "$ref": "#/$defs/PermissionsToolDecision"
          },
          "type": "array"
        }
      },
      "required": [
        "principal",
        "tools"
      ],
      "title": "PermissionsGetResult",
      "type": "object"
    },
    "PermissionsLayer": {
      "additionalProperties": false,
      "properties": {
        "diagnostics": {
          "items": {
            "$ref": "#/$defs/Diagnostic"
          },
          "type": "array"
        },
        "editable": {
          "description": "permissions.set으로 고칠 수 있는 계층 (team은 false — kookabug.json에서 편집)",
          "type": "boolean"
        },
        "layer": {
          "enum": [
            "project",
            "team",
            "user"
          ]
        },
        "permissions": {
          "description": "그 파일의 permissions 값 그대로 (없으면 null)",
          "type": [
            "null",
            "object"
          ]
        },
        "revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "그 파일 바이트의 sha256 (파일이 없으면 null). permissions.set의 base_revision"
        },
        "source": {
          "description": "파일 경로 (표시용, 정할 수 없으면 null)",
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "diagnostics",
        "editable",
        "layer",
        "permissions",
        "revision",
        "source"
      ],
      "title": "PermissionsLayer",
      "type": "object"
    },
    "PermissionsSetParams": {
      "additionalProperties": false,
      "description": "권한 계층 하나의 permissions만 바꾼다. 다른 키·순서는 보존, 같은 폴더 임시 파일 → 교체. 형식이 틀린 파일은 고치지 않고 settings_invalid",
      "properties": {
        "base_revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "읽은 때의 파일 revision (파일이 없었으면 null). 다르면 revision_conflict"
        },
        "layer": {
          "enum": [
            "project",
            "user"
          ]
        },
        "permissions": {
          "description": "새 permissions 값 (메타스키마 Permissions)",
          "type": "object"
        }
      },
      "required": [
        "base_revision",
        "layer",
        "permissions"
      ],
      "title": "PermissionsSetParams",
      "type": "object"
    },
    "PermissionsSetResult": {
      "additionalProperties": false,
      "properties": {
        "revision": {
          "$ref": "#/$defs/Revision"
        }
      },
      "required": [
        "revision"
      ],
      "title": "PermissionsSetResult",
      "type": "object"
    },
    "PermissionsToolDecision": {
      "additionalProperties": false,
      "properties": {
        "final": {
          "$ref": "#/$defs/PermissionVerdict"
        },
        "layer": {
          "anyOf": [
            {
              "enum": [
                "default",
                "project",
                "team",
                "user"
              ]
            },
            {
              "type": "null"
            }
          ]
        },
        "mutating": {
          "type": "boolean"
        },
        "reason": {
          "type": "string"
        },
        "source": {
          "type": "string"
        },
        "tool": {
          "description": "권한 표 도구 이름 (M7 kb_screen_save 포함)",
          "type": "string"
        },
        "toolset": {
          "$ref": "#/$defs/Toolset"
        },
        "verdict": {
          "$ref": "#/$defs/PermissionVerdict"
        }
      },
      "required": [
        "final",
        "layer",
        "mutating",
        "reason",
        "source",
        "tool",
        "toolset",
        "verdict"
      ],
      "title": "PermissionsToolDecision",
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
    "PluginEnvInfo": {
      "additionalProperties": false,
      "description": "잠금의 환경 하나의 상태 (M6 3.8). folder = runner가 고를 폴더 이름 (검증 없이 찾은 것)",
      "properties": {
        "fingerprint": {
          "description": "잠금의 환경 지문 (위젯 호스트 <id>-<지문 12자>)",
          "type": "string"
        },
        "folder": {
          "type": [
            "null",
            "string"
          ]
        },
        "plugins": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "status": {
          "$ref": "#/$defs/PluginEnvStatus"
        }
      },
      "required": [
        "folder",
        "plugins",
        "status"
      ],
      "title": "PluginEnvInfo",
      "type": "object"
    },
    "PluginEnvStatus": {
      "description": "ready 준비됨 · missing 환경 없음([준비…]) · stale 조건(Python·SDK)이 앱과 다름([다시 잠그기…]) · broken 환경이 깨짐([준비…]로 새로)",
      "enum": [
        "ready",
        "missing",
        "stale",
        "broken"
      ],
      "title": "PluginEnvStatus",
      "type": "string"
    },
    "PluginErrorInfo": {
      "description": "플러그인 작업 오류 요약 (kookabug_core.plugins.PluginError.to_json — 인증 정보를 가린 값). code는 설치 거래 오류 코드(M6 3.5)·plugin_busy·internal_error, 원문은 작업 로그(.kookabug/plugins/logs/<op_id>.log)",
      "properties": {
        "code": {
          "type": "string"
        },
        "conflicts": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "env": {
          "type": "string"
        },
        "message": {
          "type": "string"
        },
        "op_id": {
          "$ref": "#/$defs/PluginOpId"
        },
        "packages": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "plugin": {
          "type": "string"
        },
        "stage": {
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "code",
        "message",
        "stage"
      ],
      "title": "PluginErrorInfo",
      "type": "object"
    },
    "PluginGcCandidates": {
      "additionalProperties": false,
      "description": "gc가 지울 후보 이름 (확인 카드용 — 실제 gc는 검증한 선택으로 다시 판정하고, plugins.gc candidates로 받은 것 안에서만 지운다)",
      "properties": {
        "envs": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "staging": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "wheels": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "envs",
        "staging",
        "wheels"
      ],
      "title": "PluginGcCandidates",
      "type": "object"
    },
    "PluginInstalled": {
      "additionalProperties": false,
      "description": "nodes.list의 설치 플러그인 요약 (kb_node_search가 노드마다 보인다)",
      "properties": {
        "env": {
          "type": "string"
        },
        "env_status": {
          "$ref": "#/$defs/PluginEnvStatus"
        },
        "id": {
          "type": "string"
        },
        "permissions": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "title": {
          "type": "string"
        },
        "version": {
          "type": "string"
        }
      },
      "required": [
        "env",
        "env_status",
        "id",
        "permissions",
        "version"
      ],
      "title": "PluginInstalled",
      "type": "object"
    },
    "PluginIsolation": {
      "enum": [
        "auto",
        "shared",
        "isolated"
      ],
      "title": "PluginIsolation",
      "type": "string"
    },
    "PluginJob": {
      "additionalProperties": false,
      "description": "이 daemon에서 진행 중인 플러그인 작업 (waiting = 미리보기가 승인을 기다림). 승인을 기다리는 미리보기의 op_id는 그 미리보기를 연 연결에만 보이고 다른 연결에는 null (승인·취소는 연 연결만)",
      "properties": {
        "kind": {
          "$ref": "#/$defs/PluginOpKind"
        },
        "op_id": {
          "anyOf": [
            {
              "$ref": "#/$defs/PluginOpId"
            },
            {
              "type": "null"
            }
          ]
        },
        "stage": {
          "type": [
            "null",
            "string"
          ]
        },
        "waiting": {
          "type": "boolean"
        }
      },
      "required": [
        "kind",
        "op_id",
        "stage",
        "waiting"
      ],
      "title": "PluginJob",
      "type": "object"
    },
    "PluginListEntry": {
      "additionalProperties": false,
      "description": "잠금의 플러그인 항목(plugin-lock LockPlugin) + 환경 상태 + 노드 (커밋된 wheel의 스키마)",
      "properties": {
        "conflicts": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "dist": {
          "type": "string"
        },
        "env": {
          "type": "string"
        },
        "env_status": {
          "$ref": "#/$defs/PluginEnvStatus"
        },
        "id": {
          "type": "string"
        },
        "isolated_because": {
          "type": [
            "null",
            "string"
          ]
        },
        "manifest": {
          "description": "잠금의 manifest (title·modules·permissions·min_core·isolation·ui)",
          "type": "object"
        },
        "nodes": {
          "items": {
            "$ref": "#/$defs/PluginNodeInfo"
          },
          "type": "array"
        },
        "requires": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "schema_sha256": {
          "type": "string"
        },
        "source": {
          "description": "원천 출처 (git·wheel·path — 인증 정보 없음)",
          "type": "object"
        },
        "ui": {
          "$ref": "#/$defs/PluginWidgetHost"
        },
        "version": {
          "type": "string"
        },
        "wheel": {
          "type": "string"
        },
        "wheel_sha256": {
          "type": "string"
        }
      },
      "required": [
        "env",
        "env_status",
        "id",
        "manifest",
        "nodes",
        "source",
        "version"
      ],
      "title": "PluginListEntry",
      "type": "object"
    },
    "PluginNodeInfo": {
      "additionalProperties": false,
      "properties": {
        "effects": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "title": {
          "type": "string"
        },
        "type": {
          "type": "string"
        },
        "ui": {
          "additionalProperties": {
            "type": "string"
          },
          "description": "config 이름 → 위젯 ID (<플러그인>.<이름>, M6 3.10)",
          "type": "object"
        }
      },
      "required": [
        "effects",
        "type"
      ],
      "title": "PluginNodeInfo",
      "type": "object"
    },
    "PluginOpId": {
      "description": "플러그인 작업 ID (= 설치 거래 ID, 작업 로그 이름)",
      "pattern": "^[0-9a-f]{32}$",
      "title": "PluginOpId",
      "type": "string"
    },
    "PluginOpKind": {
      "enum": [
        "install",
        "upgrade",
        "remove",
        "sync",
        "relock",
        "gc"
      ],
      "title": "PluginOpKind",
      "type": "string"
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
    "PluginWidgetHost": {
      "additionalProperties": false,
      "description": "위젯 호스트 (M6 3.10): 머리에 ui가 있고 환경이 준비된 플러그인만. kbplugin://<host>/가 path(워크스페이스 기준, 환경 안 ui 폴더) 아래 파일만 준다",
      "properties": {
        "host": {
          "description": "<플러그인 ID('_'는 '-')>-<환경 지문 12자> (CSP 호스트 문법에 '_'가 없다)",
          "pattern": "^[a-z][a-z0-9-]*-[0-9a-f]{12}$",
          "type": "string"
        },
        "path": {
          "description": "워크스페이스 기준 '/' 경로 (.kookabug/plugins/envs/<폴더>/Lib/site-packages/<패키지>/<ui>)",
          "type": "string"
        },
        "widgets": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "host",
        "path",
        "widgets"
      ],
      "title": "PluginWidgetHost",
      "type": "object"
    },
    "PluginsChangedParams": {
      "additionalProperties": false,
      "description": "kookabug.lock이 바뀌었다 (daemon 작업이든 밖에서든). daemon은 레지스트리를 다시 만들었다 — nodes.list·검증을 다시 부른다",
      "properties": {
        "revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "잠금 파일 바이트 sha256 (없어졌으면 null)"
        }
      },
      "required": [
        "revision"
      ],
      "title": "PluginsChangedParams",
      "type": "object"
    },
    "PluginsDoneParams": {
      "additionalProperties": false,
      "description": "플러그인 작업이 끝났다 (ui 연결에만). ok가 거짓이면 error, 참이면 result (작업별 결과)",
      "properties": {
        "error": {
          "$ref": "#/$defs/PluginErrorInfo"
        },
        "kind": {
          "$ref": "#/$defs/PluginOpKind"
        },
        "ok": {
          "type": "boolean"
        },
        "op_id": {
          "$ref": "#/$defs/PluginOpId"
        },
        "result": {
          "type": "object"
        }
      },
      "required": [
        "kind",
        "ok",
        "op_id"
      ],
      "title": "PluginsDoneParams",
      "type": "object"
    },
    "PluginsGcParams": {
      "additionalProperties": false,
      "properties": {
        "candidates": {
          "$ref": "#/$defs/PluginGcCandidates",
          "description": "사람이 확인 카드에서 본 후보 (plugins.list gc_candidates). 그 안의 것만 지운다 — 그 사이 생긴 후보는 남는다"
        }
      },
      "required": [
        "candidates"
      ],
      "title": "PluginsGcParams",
      "type": "object"
    },
    "PluginsListResult": {
      "additionalProperties": false,
      "description": "플러그인 목록 (M6 3.8, 읽기만). lock_sha256 = 정규 잠금 해시 — 준비(plugins.sync)에 그대로 넘긴다. trusted = 이 PC에서 신뢰 확인한 잠금",
      "properties": {
        "busy": {
          "anyOf": [
            {
              "$ref": "#/$defs/PluginJob"
            },
            {
              "type": "null"
            }
          ]
        },
        "environments": {
          "additionalProperties": {
            "$ref": "#/$defs/PluginEnvInfo"
          },
          "type": "object"
        },
        "gc_candidates": {
          "$ref": "#/$defs/PluginGcCandidates"
        },
        "lock_sha256": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ]
        },
        "plugins": {
          "items": {
            "$ref": "#/$defs/PluginListEntry"
          },
          "type": "array"
        },
        "revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "잠금 파일 revision (plugins.remove의 base_revision)"
        },
        "stale_reason": {
          "type": [
            "null",
            "string"
          ]
        },
        "trusted": {
          "type": "boolean"
        }
      },
      "required": [
        "busy",
        "environments",
        "gc_candidates",
        "lock_sha256",
        "plugins",
        "revision",
        "stale_reason",
        "trusted"
      ],
      "title": "PluginsListResult",
      "type": "object"
    },
    "PluginsOpIdParams": {
      "additionalProperties": false,
      "properties": {
        "op_id": {
          "$ref": "#/$defs/PluginOpId"
        }
      },
      "required": [
        "op_id"
      ],
      "title": "PluginsOpIdParams",
      "type": "object"
    },
    "PluginsOpResult": {
      "additionalProperties": false,
      "description": "작업을 시작했다. 진행은 plugins.progress, 끝은 plugins.done",
      "properties": {
        "op_id": {
          "$ref": "#/$defs/PluginOpId"
        }
      },
      "required": [
        "op_id"
      ],
      "title": "PluginsOpResult",
      "type": "object"
    },
    "PluginsPreviewParams": {
      "additionalProperties": false,
      "description": "원천: git+<url>[@ref] · *.whl 경로·https URL(sha256 필수) · 폴더. 받고 정적으로 읽기만 한다 (코드 실행 없음)",
      "properties": {
        "isolation": {
          "$ref": "#/$defs/PluginIsolation"
        },
        "ref": {
          "minLength": 1,
          "type": "string"
        },
        "sha256": {
          "pattern": "^[0-9a-fA-F]{64}$",
          "type": "string"
        },
        "source": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "source"
      ],
      "title": "PluginsPreviewParams",
      "type": "object"
    },
    "PluginsPreviewResult": {
      "additionalProperties": false,
      "description": "신뢰 확인 재료 (설치 거래 ①②). expires_in_s 안에 plugins.install {op_id}로 승인, plugins.cancel로 취소. untrusted = 이 PC에서 신뢰 확인하지 않은 잠금이면 함께 신뢰할 기존 플러그인 ID 전체",
      "properties": {
        "dependencies": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "dist": {
          "type": "string"
        },
        "expires_in_s": {
          "minimum": 0,
          "type": "number"
        },
        "id": {
          "type": "string"
        },
        "isolation": {
          "$ref": "#/$defs/PluginIsolation"
        },
        "op_id": {
          "$ref": "#/$defs/PluginOpId"
        },
        "permissions": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "replaces": {
          "description": "upgrade면 바꾸는 판",
          "type": [
            "null",
            "string"
          ]
        },
        "source": {
          "description": "원천 출처 (인증 정보 없음)",
          "type": "object"
        },
        "title": {
          "type": [
            "null",
            "string"
          ]
        },
        "untrusted": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "version": {
          "type": "string"
        }
      },
      "required": [
        "dependencies",
        "dist",
        "expires_in_s",
        "id",
        "isolation",
        "op_id",
        "permissions",
        "replaces",
        "source",
        "title",
        "untrusted",
        "version"
      ],
      "title": "PluginsPreviewResult",
      "type": "object"
    },
    "PluginsProgressParams": {
      "additionalProperties": false,
      "description": "플러그인 작업 진행 (ui 연결에만). stage = 거래 단계 (kookabug_core.plugins.STAGES)",
      "properties": {
        "message": {
          "type": "string"
        },
        "op_id": {
          "$ref": "#/$defs/PluginOpId"
        },
        "stage": {
          "type": "string"
        }
      },
      "required": [
        "message",
        "op_id",
        "stage"
      ],
      "title": "PluginsProgressParams",
      "type": "object"
    },
    "PluginsRelockParams": {
      "additionalProperties": false,
      "properties": {
        "lock_sha256": {
          "$ref": "#/$defs/Revision",
          "description": "사람이 확인 카드에서 본 잠금의 정규 해시 (plugins.list lock_sha256). 거래 안에서 읽은 잠금과 다르면 revision_conflict (카드에 없던 플러그인을 확인 실행하지 않는다)"
        }
      },
      "required": [
        "lock_sha256"
      ],
      "title": "PluginsRelockParams",
      "type": "object"
    },
    "PluginsRemoveParams": {
      "additionalProperties": false,
      "properties": {
        "base_revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ],
          "description": "확인할 때 본 잠금 revision (plugins.list). null = 확인할 때 잠금이 없었다 (비교 생략이 아님). 거래 안에서 읽은 잠금과 null까지 비교해 다르면 revision_conflict"
        },
        "id": {
          "type": "string"
        }
      },
      "required": [
        "base_revision",
        "id"
      ],
      "title": "PluginsRemoveParams",
      "type": "object"
    },
    "PluginsSyncParams": {
      "additionalProperties": false,
      "properties": {
        "lock_sha256": {
          "$ref": "#/$defs/Revision",
          "description": "사람이 확인한 잠금의 정규 해시 (plugins.list lock_sha256). 그 사이 바뀌면 revision_conflict"
        }
      },
      "required": [
        "lock_sha256"
      ],
      "title": "PluginsSyncParams",
      "type": "object"
    },
    "PluginsUpgradeParams": {
      "additionalProperties": false,
      "description": "잠금의 원천을 다시 받아 미리보기 (plugins.preview와 같은 흐름 — plugins.install {op_id}로 승인)",
      "properties": {
        "id": {
          "type": "string"
        },
        "isolation": {
          "$ref": "#/$defs/PluginIsolation"
        },
        "ref": {
          "minLength": 1,
          "type": "string"
        },
        "sha256": {
          "pattern": "^[0-9a-fA-F]{64}$",
          "type": "string"
        }
      },
      "required": [
        "id"
      ],
      "title": "PluginsUpgradeParams",
      "type": "object"
    },
    "PreviewPeak": {
      "additionalProperties": false,
      "description": "같은 사양으로 찾은 자리 하나 (target.preview peaks)",
      "properties": {
        "rect": {
          "$ref": "#/$defs/Rect"
        },
        "scale": {
          "minimum": 0,
          "type": "number"
        },
        "score": {
          "maximum": 1,
          "minimum": -1,
          "type": "number"
        }
      },
      "required": [
        "rect",
        "scale",
        "score"
      ],
      "title": "PreviewPeak",
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
        "peaks": {
          "description": "임계값 이상이고 서로 겹치지 않는 자리 (점수 높은 차례, 최대 8 — '같은 모양 N곳', M4). 없으면 아직 세지 않음",
          "items": {
            "$ref": "#/$defs/PreviewPeak"
          },
          "maxItems": 8,
          "type": "array"
        },
        "scale_scores": {
          "description": "params.scales 차례대로 그 배율로 바꾼 정지 화면에서 찾은 결과 (scales를 보냈을 때만)",
          "items": {
            "$ref": "#/$defs/PreviewScaleScore"
          },
          "maxItems": 6,
          "type": "array"
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
    "PreviewScaleScore": {
      "additionalProperties": false,
      "description": "다른 배율 점수 한 줄: factor = 정지 화면을 바꾼 배율, found = 그 화면에서 찾음, score = 받아들인(없으면 최고) 점수 (시도한 것이 없으면 null), scale = 그 후보의 배율",
      "properties": {
        "factor": {
          "type": "number"
        },
        "found": {
          "type": "boolean"
        },
        "scale": {
          "anyOf": [
            {
              "minimum": 0,
              "type": "number"
            },
            {
              "type": "null"
            }
          ]
        },
        "score": {
          "anyOf": [
            {
              "maximum": 1,
              "minimum": -1,
              "type": "number"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "factor",
        "found",
        "scale",
        "score"
      ],
      "title": "PreviewScaleScore",
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
        "job": {
          "description": "M8: 작업 토큰으로 묶인 연결이면 그 작업 ID (없으면 키 없음)",
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
    "RecorderBadge": {
      "additionalProperties": false,
      "description": "스텝 메모 (시안 '녹화된 스텝'의 메모 줄). severity review는 확인 필요(노랑·주황). 글자 원문을 담지 않는다",
      "properties": {
        "code": {
          "pattern": "^[a-z][a-z0-9_]*$",
          "type": "string"
        },
        "message": {
          "type": "string"
        },
        "severity": {
          "enum": [
            "info",
            "review",
            "warning"
          ]
        }
      },
      "required": [
        "code",
        "severity"
      ],
      "title": "RecorderBadge",
      "type": "object"
    },
    "RecorderChangedParams": {
      "additionalProperties": false,
      "description": "recorder.changed: 녹화 상태·스텝이 바뀜. 소유 연결에는 rev·counts·warnings도 (스텝 목록은 rev로 recorder.steps를 다시 부른다), 다른 연결에는 state만. 글자는 싣지 않는다. session은 그 알림의 녹화 세션(idle이면 없음) — 받는 쪽은 아는 지금 세션과 다른 알림으로 상태를 바꾸지 않는다 (M5 SECFIX)",
      "properties": {
        "counts": {
          "$ref": "#/$defs/RecorderCounts"
        },
        "rev": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "session": {
          "$ref": "#/$defs/RecorderSessionId"
        },
        "state": {
          "$ref": "#/$defs/RecorderState"
        },
        "warnings": {
          "items": {
            "$ref": "#/$defs/RecorderWarning"
          },
          "type": "array"
        }
      },
      "required": [
        "state"
      ],
      "title": "RecorderChangedParams",
      "type": "object"
    },
    "RecorderCommitFinishParams": {
      "additionalProperties": false,
      "description": "recorder.commit_finish: 렌더러가 조각을 넣은 그래프를 저장했다 → 세션 committed, 정리",
      "properties": {
        "graph_path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "token": {
          "$ref": "#/$defs/RecorderCommitToken"
        }
      },
      "required": [
        "graph_path",
        "token"
      ],
      "title": "RecorderCommitFinishParams",
      "type": "object"
    },
    "RecorderCommitPrepareParams": {
      "additionalProperties": false,
      "description": "recorder.commit_prepare: 녹화를 멈추고(아직이면) 검사(classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap) → target 파일 쓰기(멱등: 이미 쓴 초안은 다시 쓰지 않음) → 조각. graph_path는 새 테스트면 만들 파일, 삽입이면 열린 그래프 파일 (target 폴더 이름 targets/rec/<줄기>/). options는 이 커밋에 적용할 변환 옵션(녹화 뒤 사이드바에서 바꾼 값). 빼면 세션 옵션(recorder.start의 options, recorder.state가 보임). 옵션이 다르면 다른 조각이다(같은 옵션으로 다시 부를 때만 같은 조각)",
      "properties": {
        "base_revision": {
          "anyOf": [
            {
              "$ref": "#/$defs/Revision"
            },
            {
              "type": "null"
            }
          ]
        },
        "graph_path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "mode": {
          "enum": [
            "insert",
            "new_test"
          ]
        },
        "options": {
          "$ref": "#/$defs/RecorderOptions"
        }
      },
      "required": [
        "graph_path",
        "mode"
      ],
      "title": "RecorderCommitPrepareParams",
      "type": "object"
    },
    "RecorderCommitPrepareResult": {
      "additionalProperties": false,
      "description": "조각과 토큰 (세션 committing). 같은 요청을 다시 부르면 같은 조각(같은 로컬 ID·경로)",
      "properties": {
        "fragment": {
          "$ref": "urn:kookabug:recorder-fragment:0"
        },
        "targets": {
          "items": {
            "$ref": "#/$defs/RecorderWrittenTarget"
          },
          "type": "array"
        },
        "token": {
          "$ref": "#/$defs/RecorderCommitToken"
        }
      },
      "required": [
        "fragment",
        "targets",
        "token"
      ],
      "title": "RecorderCommitPrepareResult",
      "type": "object"
    },
    "RecorderCommitToken": {
      "description": "커밋 토큰 (commit_prepare가 주고 commit_finish·commit_abort가 받는다)",
      "pattern": "^[A-Za-z0-9_-]{16,64}$",
      "title": "RecorderCommitToken",
      "type": "string"
    },
    "RecorderCommitTokenParams": {
      "additionalProperties": false,
      "description": "recorder.commit_abort: 그래프 단계가 실패 → stopped로 돌아가 다른 이름·위치로 다시 commit_prepare (써진 target 재사용)",
      "properties": {
        "token": {
          "$ref": "#/$defs/RecorderCommitToken"
        }
      },
      "required": [
        "token"
      ],
      "title": "RecorderCommitTokenParams",
      "type": "object"
    },
    "RecorderCounts": {
      "additionalProperties": false,
      "description": "스텝·만든 target 수와 녹화하지 않은 입력 수 (다른 프로그램이 보낸 입력, 게임 창 밖, 게임의 팝업 창)",
      "properties": {
        "ignored_injected": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "ignored_outside": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "ignored_popup": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "steps": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "targets": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "ignored_injected",
        "ignored_outside",
        "ignored_popup",
        "steps",
        "targets"
      ],
      "title": "RecorderCounts",
      "type": "object"
    },
    "RecorderFrameParams": {
      "additionalProperties": false,
      "description": "recorder.frame: 그 스텝이 붙잡은 프레임(pre_click 클릭 직전·pre_hover 커서 들어오기 전·pre_next 다음 동작 직전) 또는 live(링의 지금 프레임, step 없음, stopped에서는 no_frame)를 편집기 프레임 캐시에 올린다",
      "else": {
        "required": [
          "step"
        ]
      },
      "if": {
        "properties": {
          "which": {
            "const": "live"
          }
        },
        "required": [
          "which"
        ]
      },
      "properties": {
        "step": {
          "$ref": "#/$defs/RecorderStepId"
        },
        "which": {
          "$ref": "#/$defs/RecorderFrameWhich"
        }
      },
      "required": [
        "which"
      ],
      "then": {
        "not": {
          "required": [
            "step"
          ]
        }
      },
      "title": "RecorderFrameParams",
      "type": "object"
    },
    "RecorderFrameResult": {
      "additionalProperties": false,
      "description": "정지 화면과 그 프레임에서 유효한 보호 영역(비밀값·판정 대기·확인 필요 입력 칸 상자, 클라이언트 물리 픽셀 — 편집기가 빗금으로 보이고 그 영역과 겹치는 저장은 secret_region_overlap)",
      "properties": {
        "frame": {
          "$ref": "#/$defs/Frame"
        },
        "protected": {
          "items": {
            "$ref": "#/$defs/Rect"
          },
          "type": "array"
        },
        "which": {
          "$ref": "#/$defs/RecorderFrameWhich"
        }
      },
      "required": [
        "frame",
        "protected",
        "which"
      ],
      "title": "RecorderFrameResult",
      "type": "object"
    },
    "RecorderFrameWhich": {
      "enum": [
        "live",
        "pre_click",
        "pre_hover",
        "pre_next"
      ],
      "title": "RecorderFrameWhich",
      "type": "string"
    },
    "RecorderHotkey": {
      "additionalProperties": false,
      "description": "Electron 주 프로세스가 녹화 중에만 등록한 단축키. 변환기가 이 조합의 키 이벤트와 그 조합 때문에만 눌린 수정 키를 지운다",
      "properties": {
        "keys": {
          "description": "키 이름 조합 (입력 노드 keys와 같은 이름, 예: ctrl+shift+r)",
          "pattern": "^[a-z0-9_]+(\\+[a-z0-9_]+)*$",
          "type": "string"
        },
        "role": {
          "enum": [
            "mark_secret",
            "stop"
          ]
        }
      },
      "required": [
        "keys",
        "role"
      ],
      "title": "RecorderHotkey",
      "type": "object"
    },
    "RecorderInsertCheckParams": {
      "additionalProperties": false,
      "description": "recorder.insert_check: 녹화 중 '화면 확인 삽입'(visible → core.assert.visible) · '값 확인 삽입'(text → core.assert.text, 영역 OCR 글자를 기댓값으로 제안). rect는 그 frame_id 정지 화면의 클라이언트 물리 픽셀 영역 (보호 영역과 겹치면 secret_region_overlap)",
      "properties": {
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "kind": {
          "enum": [
            "text",
            "visible"
          ]
        },
        "rect": {
          "$ref": "#/$defs/Rect"
        }
      },
      "required": [
        "frame_id",
        "kind",
        "rect"
      ],
      "title": "RecorderInsertCheckParams",
      "type": "object"
    },
    "RecorderMaterializeParams": {
      "additionalProperties": false,
      "description": "recorder.target.materialize: REC 탭 '찾기 대상 탭으로 열기' — 그 스텝의 녹화 초안만 지금 target 파일로 쓴다(최신 보호 영역 재검사 뒤, targets/rec/<세션 ID>/). 그 스텝은 이후 그 파일을 가리키고 커밋은 다시 쓰지 않는다. 초안이 없는 스텝이면 target_missing",
      "properties": {
        "step": {
          "$ref": "#/$defs/RecorderStepId"
        }
      },
      "required": [
        "step"
      ],
      "type": "object"
    },
    "RecorderNeedsReviewReason": {
      "description": "스텝을 사람이 확인해야 하는 이유 (커밋 전 남기거나 지움). geometry_unresolved 클릭과 프레임의 기하 세대가 확정적으로 같지 않음, no_frame 클릭 직전 프레임이 없음, window_undetermined 어느 창에 들어간 입력인지 판정 불가, ime_unknown 입력기 상태 판정 불가, cursor_moved_in_field 칸 안에서 커서를 옮김, field_box_unknown 칸 상자를 못 정함, no_evidence 비밀 근거도 일반 근거도 없음, cut_by_stop 정지·끊김 순간의 입력, secret_overlap 비밀번호 칸과 겹쳐 대상을 못 만듦, wait_target_unknown 기다릴 화면을 못 정함",
      "enum": [
        "cursor_moved_in_field",
        "cut_by_stop",
        "field_box_unknown",
        "geometry_unresolved",
        "ime_unknown",
        "no_evidence",
        "no_frame",
        "secret_overlap",
        "wait_target_unknown",
        "window_undetermined"
      ],
      "title": "RecorderNeedsReviewReason",
      "type": "string"
    },
    "RecorderOptions": {
      "additionalProperties": false,
      "description": "변환 옵션 (시안 체크). 커밋 때 적용하므로 녹화 뒤에 바꿔도 된다. 없는 값은 켬. 'Kookabug가 보낸 입력은 녹화하지 않기'는 항상 켬이라 옵션이 아니다",
      "properties": {
        "crop_targets": {
          "description": "클릭 직전 화면에서 클릭 지점 주변을 잘라 찾기 대상 만들기 (끄면 core.input.click 픽셀 좌표)",
          "type": "boolean"
        },
        "wait_as_appear": {
          "description": "기다린 시간을 '나타날 때까지 대기'로 바꾸기 (끄면 core.flow.delay)",
          "type": "boolean"
        }
      },
      "title": "RecorderOptions",
      "type": "object"
    },
    "RecorderSessionId": {
      "description": "녹화 세션 ID: 소문자·숫자 8자",
      "pattern": "^[a-z0-9]{8}$",
      "title": "RecorderSessionId",
      "type": "string"
    },
    "RecorderStartParams": {
      "additionalProperties": false,
      "description": "recorder.start: 떠 있는 창(window 핸들)에 붙어 녹화하거나, 워크스페이스 game.* 설정으로 게임을 띄워 녹화(launch, profile은 설정 계층). hotkeys는 주 프로세스가 등록에 성공한 단축키. 오류: input_lease_busy·recording_active·window_gone·capture_unsupported·hook_failed",
      "oneOf": [
        {
          "required": [
            "window"
          ]
        },
        {
          "required": [
            "launch"
          ]
        }
      ],
      "properties": {
        "hotkeys": {
          "items": {
            "$ref": "#/$defs/RecorderHotkey"
          },
          "type": "array"
        },
        "launch": {
          "additionalProperties": false,
          "properties": {
            "profile": {
              "type": [
                "null",
                "string"
              ]
            }
          },
          "type": "object"
        },
        "options": {
          "$ref": "#/$defs/RecorderOptions"
        },
        "window": {
          "description": "창 handle",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "hotkeys"
      ],
      "title": "RecorderStartParams",
      "type": "object"
    },
    "RecorderState": {
      "description": "녹화 세션 상태: idle → starting → recording ⇄ paused → stopped → committing → committed | stopped, 또는 discarded. 오류로 멈춤(hook_lost·input_overflow·window_gone·storage_full)도 stopped (stop_reason)",
      "enum": [
        "committed",
        "committing",
        "discarded",
        "idle",
        "paused",
        "recording",
        "starting",
        "stopped"
      ],
      "title": "RecorderState",
      "type": "string"
    },
    "RecorderStateResult": {
      "additionalProperties": false,
      "description": "녹화 상태. owned = 부른 연결이 세션을 연 연결인가. 다른 연결(owned false)에는 상태·시작 시각·경과만 준다 (스텝·창 제목 없음 — '다른 창에서 녹화 중'). options = 세션 변환 옵션(recorder.start에서 받은 값, 없는 값은 켬) — 커밋 때 바꾸려면 commit_prepare의 options",
      "if": {
        "properties": {
          "owned": {
            "const": false
          }
        },
        "required": [
          "owned"
        ]
      },
      "properties": {
        "counts": {
          "$ref": "#/$defs/RecorderCounts"
        },
        "elapsed_ms": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "foreground": {
          "description": "대상 창이 앞에 있는가 (false면 '게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중')",
          "type": "boolean"
        },
        "launched": {
          "description": "게임을 띄워서 녹화 (그래프가 core.app.launch로 시작)",
          "type": "boolean"
        },
        "options": {
          "$ref": "#/$defs/RecorderOptions"
        },
        "owned": {
          "type": "boolean"
        },
        "session": {
          "$ref": "#/$defs/RecorderSessionId"
        },
        "started_at": {
          "$ref": "#/$defs/Timestamp"
        },
        "state": {
          "$ref": "#/$defs/RecorderState"
        },
        "stop_reason": {
          "$ref": "#/$defs/RecorderStopReason"
        },
        "warnings": {
          "items": {
            "$ref": "#/$defs/RecorderWarning"
          },
          "type": "array"
        },
        "window": {
          "$ref": "#/$defs/RecorderWindow"
        }
      },
      "required": [
        "owned",
        "state"
      ],
      "then": {
        "not": {
          "anyOf": [
            {
              "required": [
                "counts"
              ]
            },
            {
              "required": [
                "foreground"
              ]
            },
            {
              "required": [
                "launched"
              ]
            },
            {
              "required": [
                "options"
              ]
            },
            {
              "required": [
                "session"
              ]
            },
            {
              "required": [
                "stop_reason"
              ]
            },
            {
              "required": [
                "warnings"
              ]
            },
            {
              "required": [
                "window"
              ]
            }
          ]
        }
      },
      "title": "RecorderStateResult",
      "type": "object"
    },
    "RecorderStep": {
      "additionalProperties": false,
      "description": "녹화된 스텝 하나 = 재생 동작 하나 (노드는 하나 이상). 글자 규칙(M4 계획 2.8): text는 text_state가 ordinary일 때만(근거로 일반 글자로 판정됐거나 사람이 확인 — 그때 reveal_confirmed) 있다. pending·secret·needs_review는 text_len만. secret_key는 secret에만. node.title·badges에는 비밀값·판정 대기·확인 필요 원문을 넣지 않는다",
      "not": {
        "anyOf": [
          {
            "not": {
              "properties": {
                "text_state": {
                  "const": "ordinary"
                }
              },
              "required": [
                "text_state"
              ]
            },
            "required": [
              "text"
            ]
          },
          {
            "not": {
              "properties": {
                "text_state": {
                  "const": "ordinary"
                }
              },
              "required": [
                "text_state"
              ]
            },
            "required": [
              "reveal_confirmed"
            ]
          },
          {
            "not": {
              "properties": {
                "text_state": {
                  "const": "secret"
                }
              },
              "required": [
                "text_state"
              ]
            },
            "required": [
              "secret_key"
            ]
          },
          {
            "not": {
              "properties": {
                "kind": {
                  "const": "text"
                }
              }
            },
            "required": [
              "text_state"
            ]
          },
          {
            "not": {
              "required": [
                "text_state"
              ]
            },
            "properties": {
              "kind": {
                "const": "text"
              }
            }
          },
          {
            "not": {
              "required": [
                "text_state"
              ]
            },
            "required": [
              "text_len"
            ]
          }
        ]
      },
      "properties": {
        "badges": {
          "items": {
            "$ref": "#/$defs/RecorderBadge"
          },
          "type": "array"
        },
        "equals": {
          "description": "값 확인(check_text) 스텝의 기댓값 (영역 OCR 제안 또는 사람이 고친 값). 비밀값 원문과 겹치면 daemon이 비운다",
          "type": "string"
        },
        "frames": {
          "description": "recorder.frame으로 열 수 있는 이 스텝의 프레임",
          "items": {
            "$ref": "#/$defs/RecorderFrameWhich"
          },
          "type": "array"
        },
        "input": {
          "$ref": "#/$defs/RecorderStepInput"
        },
        "kind": {
          "enum": [
            "check_text",
            "check_visible",
            "click",
            "delay",
            "drag",
            "key",
            "scroll",
            "text",
            "wait"
          ]
        },
        "needs_review": {
          "items": {
            "$ref": "#/$defs/RecorderNeedsReviewReason"
          },
          "type": "array"
        },
        "node": {
          "additionalProperties": false,
          "description": "노드 초안 요약 (시안 '이미지 클릭 \"강화\"')",
          "properties": {
            "title": {
              "type": "string"
            },
            "type": {
              "pattern": "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$",
              "type": "string"
            }
          },
          "required": [
            "title",
            "type"
          ],
          "type": "object"
        },
        "reveal_confirmed": {
          "const": true,
          "description": "사람이 '글자를 보이고 일반 글자로'를 확인했다"
        },
        "secret_key": {
          "anyOf": [
            {
              "$ref": "#/$defs/SecretKey"
            },
            {
              "type": "null"
            }
          ],
          "description": "고른 비밀값 키 (아직 안 골랐으면 null → 커밋 secret_unresolved)"
        },
        "step": {
          "$ref": "#/$defs/RecorderStepId"
        },
        "t_ms": {
          "description": "녹화 시작부터 그 입력까지 (일시정지 시간 포함)",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "target": {
          "$ref": "#/$defs/RecorderTargetDraft"
        },
        "text": {
          "type": "string"
        },
        "text_len": {
          "description": "글자 수 (UI는 비밀값이면 이 길이만큼 ●)",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "text_state": {
          "$ref": "#/$defs/RecorderTextState"
        }
      },
      "required": [
        "badges",
        "kind",
        "needs_review",
        "node",
        "step",
        "t_ms"
      ],
      "title": "RecorderStep",
      "type": "object"
    },
    "RecorderStepId": {
      "description": "녹화 스텝 ID (세션 안에서 바뀌지 않음)",
      "pattern": "^rs[1-9][0-9]{0,8}$",
      "title": "RecorderStepId",
      "type": "string"
    },
    "RecorderStepInput": {
      "additionalProperties": false,
      "description": "원래 입력 요약 (시안 'click (858, 562) · 00:09.4'). 좌표는 클라이언트 물리 픽셀. 글자는 싣지 않는다",
      "properties": {
        "amount": {
          "maximum": 9007199254740991,
          "minimum": -9007199254740991,
          "type": "integer"
        },
        "button": {
          "enum": [
            "left",
            "middle",
            "right",
            "x1",
            "x2"
          ]
        },
        "count": {
          "maximum": 2,
          "minimum": 1,
          "type": "integer"
        },
        "duration_ms": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "end": {
          "items": {
            "maximum": 9007199254740991,
            "minimum": -9007199254740991,
            "type": "integer"
          },
          "maxItems": 2,
          "minItems": 2,
          "type": "array"
        },
        "gap_ms": {
          "description": "앞 동작부터 이 입력까지 (대기·지연 스텝)",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "hold_ms": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "keys": {
          "pattern": "^[a-z0-9_]+(\\+[a-z0-9_]+)*$",
          "type": "string"
        },
        "point": {
          "items": {
            "maximum": 9007199254740991,
            "minimum": -9007199254740991,
            "type": "integer"
          },
          "maxItems": 2,
          "minItems": 2,
          "type": "array"
        }
      },
      "title": "RecorderStepInput",
      "type": "object"
    },
    "RecorderStepPatch": {
      "additionalProperties": false,
      "description": "스텝 고치기 (비어 있으면 아무것도 바꾸지 않음). text_state를 ordinary로 바꾸려면 confirm_reveal이 있어야 한다 (원문을 처음 보이는 순간). text(일반 글자 고치기)는 ordinary 스텝만, target은 REC 탭의 초안 사양 고치기(RecorderTargetDraft.spec과 같은 모양 — 준 필드만 바꾼다, 보호 영역과 겹치면 secret_region_overlap), keep은 확인 필요 입력을 그대로 남기기. 자를 프레임은 둘 중 하나로 고른다: frame(이 스텝이 붙잡은 프레임 종류) 또는 frame_id(이 세션이 recorder.frame으로 편집기 캐시에 올린 프레임 — live도 조회한 그 순간의 프레임이 고정된다. 다른 세션·다른 연결이 올린 프레임이면 not_owner, 캐시에서 사라졌으면 frame_expired, 그 프레임의 보호 영역 검사를 거친다)",
      "if": {
        "properties": {
          "text_state": {
            "const": "ordinary"
          }
        },
        "required": [
          "text_state"
        ]
      },
      "not": {
        "required": [
          "frame",
          "frame_id"
        ]
      },
      "properties": {
        "confirm_reveal": {
          "const": true
        },
        "delete": {
          "const": true
        },
        "equals": {
          "description": "값 확인(check_text) 스텝의 기댓값 고치기 (사람 수정·글자 읽기 결과). 세션의 비밀값·판정 대기·확인 필요 원문을 담으면 secret_region_overlap",
          "type": "string"
        },
        "frame": {
          "enum": [
            "pre_click",
            "pre_hover",
            "pre_next"
          ]
        },
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "keep": {
          "const": true
        },
        "node_type": {
          "description": "노드 종류 바꾸기 (이미지 클릭 ↔ 좌표 클릭, 대기 종류)",
          "pattern": "^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)+$",
          "type": "string"
        },
        "secret_key": {
          "anyOf": [
            {
              "$ref": "#/$defs/SecretKey"
            },
            {
              "type": "null"
            }
          ]
        },
        "target": {
          "$ref": "#/$defs/RecorderTargetSpec"
        },
        "text": {
          "type": "string"
        },
        "text_state": {
          "enum": [
            "ordinary",
            "secret"
          ]
        },
        "timeout_ms": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        }
      },
      "then": {
        "required": [
          "confirm_reveal"
        ]
      },
      "title": "RecorderStepPatch",
      "type": "object"
    },
    "RecorderStepResult": {
      "additionalProperties": false,
      "description": "바뀐(또는 새) 스텝과 스텝 목록 판. 지운 스텝이면 step은 null",
      "properties": {
        "rev": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "step": {
          "anyOf": [
            {
              "$ref": "#/$defs/RecorderStep"
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "rev",
        "step"
      ],
      "title": "RecorderStepResult",
      "type": "object"
    },
    "RecorderStepUpdateParams": {
      "additionalProperties": false,
      "properties": {
        "patch": {
          "$ref": "#/$defs/RecorderStepPatch"
        },
        "step": {
          "$ref": "#/$defs/RecorderStepId"
        }
      },
      "required": [
        "patch",
        "step"
      ],
      "title": "RecorderStepUpdateParams",
      "type": "object"
    },
    "RecorderStepsParams": {
      "additionalProperties": false,
      "description": "recorder.steps: 스텝 목록. after_rev는 마지막으로 받은 판 (같으면 steps가 그대로)",
      "properties": {
        "after_rev": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        }
      },
      "title": "RecorderStepsParams",
      "type": "object"
    },
    "RecorderStepsResult": {
      "additionalProperties": false,
      "description": "스텝 목록 (녹화 차례). 원문 글자를 주는 유일한 곳 — ordinary 스텝의 text만",
      "properties": {
        "rev": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "steps": {
          "items": {
            "$ref": "#/$defs/RecorderStep"
          },
          "type": "array"
        }
      },
      "required": [
        "rev",
        "steps"
      ],
      "title": "RecorderStepsResult",
      "type": "object"
    },
    "RecorderStopReason": {
      "description": "녹화가 멈춘 까닭: user(정지 단추·단축키·커밋), hook_lost(훅 끊김), input_overflow(중요 입력 유실), window_gone(대상 창 닫힘), storage_full(세션 저장소 상한)",
      "enum": [
        "hook_lost",
        "input_overflow",
        "storage_full",
        "user",
        "window_gone"
      ],
      "title": "RecorderStopReason",
      "type": "string"
    },
    "RecorderTargetDraft": {
      "additionalProperties": false,
      "description": "스텝의 찾기 대상: draft(이 세션 초안, 커밋 때 파일로) · file(기존 또는 이미 쓴 target 파일 재사용) · none(아직 없음 — 커밋 target_missing). draft는 spec(daemon이 든 초안 사양 전체 — REC 편집기가 이것으로 상태를 만들고, 고친 값은 recorder.step.update patch.target으로 같은 모양을 보낸다)이 있다. frame은 자른 프레임: 스텝이 붙잡은 프레임 종류, 또는 live(편집기에서 고른 지금 프레임 — 그때 고정된 frame_id가 함께 온다)",
      "not": {
        "anyOf": [
          {
            "not": {
              "required": [
                "spec"
              ]
            },
            "properties": {
              "source": {
                "const": "draft"
              }
            }
          },
          {
            "not": {
              "required": [
                "frame_id"
              ]
            },
            "properties": {
              "frame": {
                "const": "live"
              }
            },
            "required": [
              "frame"
            ]
          }
        ]
      },
      "properties": {
        "frame": {
          "enum": [
            "live",
            "pre_click",
            "pre_hover",
            "pre_next"
          ]
        },
        "frame_id": {
          "description": "자른 프레임의 편집기 캐시 ID (recorder.frame·patch.frame_id로 고른 프레임)",
          "minLength": 1,
          "type": "string"
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "peaks": {
          "description": "같은 프레임에서 임계값 이상인 자리 수 (자기 자리 포함, '같은 모양 N곳')",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "reused": {
          "type": "boolean"
        },
        "source": {
          "enum": [
            "draft",
            "file",
            "none"
          ]
        },
        "spec": {
          "$ref": "#/$defs/RecorderTargetSpec"
        }
      },
      "required": [
        "source"
      ],
      "title": "RecorderTargetDraft",
      "type": "object"
    },
    "RecorderTargetSpec": {
      "additionalProperties": false,
      "description": "target 초안 사양 (읽기 RecorderTargetDraft.spec = 전체, 쓰기 RecorderStepPatch.target = 바꿀 필드만 — 같은 모양). rect·search는 자른 프레임의 클라이언트 물리 픽셀(search null = 검색 범위 없음). 나머지는 target 파일 필드와 같다: click.anchor·click.offset, match.threshold·rgb(색까지 확인)·methods·color_tolerance, sensitive",
      "properties": {
        "anchor": {
          "enum": [
            "bottom",
            "bottom_left",
            "bottom_right",
            "center",
            "left",
            "right",
            "top",
            "top_left",
            "top_right"
          ]
        },
        "color_tolerance": {
          "maximum": 255,
          "minimum": 0,
          "type": "number"
        },
        "methods": {
          "items": {
            "enum": [
              "template",
              "template_multiscale"
            ]
          },
          "maxItems": 2,
          "minItems": 1,
          "type": "array"
        },
        "offset": {
          "items": {
            "type": "number"
          },
          "maxItems": 2,
          "minItems": 2,
          "type": "array"
        },
        "rect": {
          "$ref": "#/$defs/Rect"
        },
        "rgb": {
          "type": "boolean"
        },
        "search": {
          "anyOf": [
            {
              "$ref": "#/$defs/Rect"
            },
            {
              "type": "null"
            }
          ]
        },
        "sensitive": {
          "type": "boolean"
        },
        "threshold": {
          "maximum": 1,
          "minimum": 0,
          "type": "number"
        }
      },
      "title": "RecorderTargetSpec",
      "type": "object"
    },
    "RecorderTextState": {
      "description": "입력 칸 구간의 글자 판정: pending(판정 중) → ordinary(일반 글자 — 긍정 근거 또는 사람 확인) | secret(비밀값, 끈적) | needs_review(근거 없음 — 사람이 고를 때까지 커밋 거부)",
      "enum": [
        "needs_review",
        "ordinary",
        "pending",
        "secret"
      ],
      "title": "RecorderTextState",
      "type": "string"
    },
    "RecorderWarning": {
      "additionalProperties": false,
      "description": "녹화 알림 (예: injected_ignored '다른 프로그램이 보낸 입력 N개는 녹화하지 않았어요', popup_ignored, not_foreground, no_assertion)",
      "properties": {
        "code": {
          "pattern": "^[a-z][a-z0-9_]*$",
          "type": "string"
        },
        "count": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "message": {
          "type": "string"
        }
      },
      "required": [
        "code"
      ],
      "title": "RecorderWarning",
      "type": "object"
    },
    "RecorderWindow": {
      "additionalProperties": false,
      "description": "녹화 대상 창 (시작 때의 값)",
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
        "process",
        "title"
      ],
      "title": "RecorderWindow",
      "type": "object"
    },
    "RecorderWrittenTarget": {
      "additionalProperties": false,
      "description": "커밋이 쓴(또는 재사용한) target 파일",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "reused": {
          "type": "boolean"
        },
        "revision": {
          "$ref": "#/$defs/TargetRevision"
        }
      },
      "required": [
        "path",
        "revision",
        "reused"
      ],
      "title": "RecorderWrittenTarget",
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
      "description": "-32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로. M3: read_only(스냅샷 그래프 저장), not_paused(멈추지 않은 실행에 Step), run_not_debuggable(이 daemon이 띄운 UI 실행이 아님). M4 녹화: recording_active(이 daemon이 녹화 중이라 실행 거부 — starting 포함), input_lease_busy(입력 임대권을 다른 주체가 쥠), not_owner(녹화 세션을 연 연결이 아님), recorder_state_invalid(지금 녹화 상태에 맞지 않는 조작·없는 커밋 토큰), hook_failed(훅 프로세스를 띄우지 못함), hook_lost·input_overflow(훅이 끊김·중요 입력 유실로 녹화가 멈춤), no_frame(고를 프레임이 없음), 커밋 거부 classification_pending(비밀 판정 중)·text_review_required(확인 필요 입력)·secret_unresolved(키 없는 비밀값)·target_missing(대상 없는 클릭)·secret_region_overlap(비밀번호 칸과 겹치는 영역). M5: toolset_disabled(agent 연결이 켜지 않은 툴셋의 메서드 — 판정 전), force_not_allowed(agent 연결의 graph.save force), patch_invalid(graph.patch 연산이 틀림), agent_use_safe_api(agent 연결의 기록 원문 경로 — run.index·children·step·file·compare·subscribe, runs/ 이미지의 target.load_image·preview), secret_step(비밀값 스텝·agent_withhold 증거), unclassified_run(비밀값 분류 없는 옛 기록의 파일), not_evidence(그 실행의 증거 파일이 아님), video_not_served(영상 조각), recorder_frame(녹화 세션 프레임), sensitive_region(sensitive target이 보이는 화면의 OCR), frame_not_owned(agent 연결이 다른 연결이 만든 정지 화면을 씀). M5 B3: approval_required(사람 확인 필요 — data.reason no_approver면 확인할 사람 연결 없음), approval_denied(사람이 거부), approval_timeout(120초 안에 답 없음), always_not_allowed(control 도구에 항상 허용), settings_invalid(형식이 틀린 설정 파일 — 고치지 않음). M5 SECFIX: recorder_store_unclean(녹화 임시 파일을 정리하지 못함 — 메모리 스텝은 바뀌었고 daemon이 다시 정리한다). M6: plugin_failed(플러그인 작업 오류 — data.plugin_error의 code·stage·message, plugin_busy 포함), op_not_found(승인·취소할 플러그인 작업·미리보기가 없음 — 5분 지남·끝남). M7: frame_protected(보호 판정을 통과하지 못한 정지 화면 — data.reason 사유·message 안내, 민감 target 사유는 sensitive_region 그대로), protect_record_failed(비밀값 입력 전 보호 기록을 쓰지 못함 — 입력을 보내지 않았다). M7 탐색: agent_only(에이전트 연결 전용 메서드), explore_active(이 연결에 탐색 세션이 이미 있음), explore_not_active(탐색 세션 없음), explore_budget_exhausted(스텝 예산 다 씀 — 판정 전), screen_exists(확정 화면과 같은 키), detect_not_matching(판정 조건이 그 정지 화면에서 맞지 않음), secret_in_text(글자 필드에 비밀값 — data.field), secret_unchecked(비밀값 검사 불가 — 키를 못 읽음·보호 기록 손상), screens_busy(화면 지도 잠금) M8 B4: job_token_invalid(작업 토큰이 틀림·만료·폐기 — 연결 거부), job_only(작업 토큰 연결 전용 메서드), forbidden_visible(금지 문구·target·화면이 보여 입력하지 않음 — data.kind·value), forbidden_unverifiable(화면·OCR·target 확인 실패로 입력하지 않음), stalled_repeat(같은 작업에서 같은 실패 3번 — 그 테스트를 다시 돌리지 않음), case_resolution_reserved(사건 resolved·closed는 Kookabug·사람만), case_closed(닫힌 사건), verification_active(자동 채택 검증 실행 중이라 게임 입력을 받지 않음), 지식 연산 거부(duplicate_id·basis_required·basis_unknown·basis_hash_mismatch·basis_derived·human_basis_reserved·adoption_reserved·answer_reserved·too_large·path_alias) UX2: source_unavailable(원본을 읽을 수 없음 — data.reason missing·unreadable·unchecked_url·duplicate_id), unsupported_format(텍스트·docx·xlsx·pptx가 아님·너무 큼·깨짐 — data.reason), setting_not_allowed(허용 목록 밖 설정 키 제안)",
      "enum": [
        "approval_required",
        "classification_pending",
        "hook_failed",
        "hook_lost",
        "input_lease_busy",
        "input_overflow",
        "no_frame",
        "not_owner",
        "recorder_state_invalid",
        "recording_active",
        "secret_region_overlap",
        "secret_unresolved",
        "target_missing",
        "text_review_required",
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
        "not_paused",
        "ocr_model_corrupt",
        "ocr_model_missing",
        "path_outside_workspace",
        "permission_denied",
        "platform_unavailable",
        "point_obscured",
        "private_path",
        "protocol_mismatch",
        "read_only",
        "revision_conflict",
        "run_active",
        "run_busy",
        "run_not_debuggable",
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
        "window_not_found",
        "toolset_disabled",
        "force_not_allowed",
        "patch_invalid",
        "agent_use_safe_api",
        "secret_step",
        "unclassified_run",
        "not_evidence",
        "video_not_served",
        "recorder_frame",
        "sensitive_region",
        "frame_not_owned",
        "approval_denied",
        "approval_timeout",
        "always_not_allowed",
        "settings_invalid",
        "recorder_store_unclean",
        "plugin_failed",
        "op_not_found",
        "frame_protected",
        "protect_record_failed",
        "agent_only",
        "explore_active",
        "explore_not_active",
        "explore_budget_exhausted",
        "screen_exists",
        "detect_not_matching",
        "secret_in_text",
        "secret_unchecked",
        "screens_busy",
        "session_not_allowed",
        "approval_cancelled",
        "recovery_pending",
        "basis_denied",
        "policy_path",
        "knowledge_busy",
        "already_reverted",
        "change_not_active",
        "nothing_to_revert",
        "evidence_missing",
        "job_token_invalid",
        "job_only",
        "forbidden_visible",
        "forbidden_unverifiable",
        "stalled_repeat",
        "case_resolution_reserved",
        "verification_active",
        "duplicate_id",
        "basis_required",
        "basis_unknown",
        "basis_hash_mismatch",
        "basis_derived",
        "human_basis_reserved",
        "adoption_reserved",
        "answer_reserved",
        "too_large",
        "path_alias",
        "case_closed",
        "job_budget_exhausted",
        "job_ended",
        "job_active",
        "source_unavailable",
        "unsupported_format",
        "setting_not_allowed"
      ],
      "title": "RequestFailedCode",
      "type": "string"
    },
    "RequestFailedData": {
      "additionalProperties": false,
      "description": "error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found·run_not_debuggable·not_paused → run_id, read_only → path, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message. M4: input_lease_busy → owner(살아 있음이 확인된 소유자, 모르면 null), recording_active·not_owner·recorder_state_invalid → state, classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap → steps(걸린 스텝). M5: toolset_disabled → toolset, patch_invalid → index·message. M5 B3: approval_required → decision·reason. M6: plugin_failed → plugin_error, op_not_found → op_id. M7: frame_protected·sensitive_region → reason·message(안내), secret_in_text → field, secret_unchecked → reason(못 읽은 키 이름). M8: forbidden_visible·forbidden_unverifiable → kind·value·reason(고정 사유), job_token_invalid → message 없음, permission_denied → reason job_scope(작업 허용 범위 밖)",
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
        "field": {
          "description": "M7 secret_in_text: 비밀값이 든 글자 필드 이름 (값 없음)",
          "type": "string"
        },
        "index": {
          "description": "patch_invalid: 틀린 연산의 순번 (0부터)",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "journals": {
          "description": "M7 B4 recovery_pending: 남은 승격 거래 저널 ID",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "kind": {
          "description": "M8 forbidden_visible·forbidden_unverifiable: 걸린 금지 항목 종류 (text·target·screen, 모르면 null)",
          "type": [
            "string",
            "null"
          ]
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
        "op_id": {
          "type": "string"
        },
        "owner": {
          "anyOf": [
            {
              "$ref": "#/$defs/LeaseOwner"
            },
            {
              "type": "null"
            }
          ]
        },
        "path": {
          "type": "string"
        },
        "paths": {
          "description": "M7 B4 revision_conflict·recovery_pending: 걸린 화면 지도 파일들 (워크스페이스 기준)",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "plugin_error": {
          "$ref": "#/$defs/PluginErrorInfo"
        },
        "protocol": {
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
        "reason": {
          "description": "approval_required: no_approver(사람 연결 없음). M6: permission_denied: dev_modules_agent(개발 모듈 daemon의 에이전트 실행)",
          "type": "string"
        },
        "revision": {
          "type": [
            "string",
            "null"
          ]
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "state": {
          "$ref": "#/$defs/RecorderState"
        },
        "steps": {
          "items": {
            "$ref": "#/$defs/RecorderStepId"
          },
          "type": "array"
        },
        "toolset": {
          "$ref": "#/$defs/Toolset"
        },
        "value": {
          "description": "M8 forbidden_*: 걸린 금지 항목 값 (정책의 문구·target 경로·화면 ID — 화면 글자가 아니다, 모르면 null)",
          "type": [
            "string",
            "null"
          ]
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
    "RunArtifactParams": {
      "additionalProperties": false,
      "description": "run.artifact (kb_run_artifact_get, M5 3.8): 실행 폴더의 증거 파일 하나 (steps/·thumbs/ 아래 그 스텝의 증거, video/index.json). 비밀값 스텝(안쪽 포함)·agent_withhold 증거는 secret_step, 분류 없는 기록은 unclassified_run, 영상 조각은 video_not_served. max_side는 이미지 긴 변 상한(≤1568), as_frame이면 정지 화면으로",
      "properties": {
        "as_frame": {
          "type": "boolean"
        },
        "max_side": {
          "maximum": 1568,
          "minimum": 1,
          "type": "integer"
        },
        "path": {
          "minLength": 1,
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "path",
        "run_id"
      ],
      "title": "RunArtifactParams",
      "type": "object"
    },
    "RunArtifactResult": {
      "additionalProperties": false,
      "description": "kind image: 줄인 PNG를 .kookabug/cache/agent/<cache>에 썼다 (긴 변 ≤1568, ≤1 MiB — 읽은 쪽이 지운다). kind text: 글자 (256 KiB에서 자름). kind frame: 정지 화면 frame_id",
      "properties": {
        "bytes": {
          "minimum": 0,
          "type": "integer"
        },
        "cache": {
          "pattern": "^c\\d+/[0-9a-f]{16}\\.png$",
          "type": "string"
        },
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "height": {
          "minimum": 1,
          "type": "integer"
        },
        "kind": {
          "enum": [
            "frame",
            "image",
            "text"
          ]
        },
        "path": {
          "type": "string"
        },
        "text": {
          "type": "string"
        },
        "truncated": {
          "type": "boolean"
        },
        "width": {
          "minimum": 1,
          "type": "integer"
        }
      },
      "required": [
        "kind",
        "path"
      ],
      "title": "RunArtifactResult",
      "type": "object"
    },
    "RunChildrenParams": {
      "additionalProperties": false,
      "description": "그 스텝 바로 아래 스텝을 쪽으로 읽는다. 반복 스텝이면 iteration으로 회차를 고른다",
      "properties": {
        "iteration": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "limit": {
          "maximum": 500,
          "minimum": 1,
          "type": "integer"
        },
        "offset": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "parent": {
          "$ref": "#/$defs/StepId"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "limit",
        "offset",
        "parent",
        "run_id"
      ],
      "title": "RunChildrenParams",
      "type": "object"
    },
    "RunChildrenResult": {
      "additionalProperties": false,
      "properties": {
        "offset": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "steps": {
          "items": {
            "$ref": "urn:kookabug:run-index:0#/$defs/StepNode"
          },
          "type": "array"
        },
        "total": {
          "description": "그 부모(·회차) 아래 스텝 수",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        }
      },
      "required": [
        "offset",
        "steps",
        "total"
      ],
      "title": "RunChildrenResult",
      "type": "object"
    },
    "RunCompareParams": {
      "additionalProperties": false,
      "description": "baseline을 빼면 기준 실행을 고른다 (같은 테스트·같은 프로필·pass·디버거 개입 아님 중 이 실행보다 먼저 시작한 가장 최근). step은 화면을 비교할 스텝 (빼면 실패 스텝)",
      "properties": {
        "baseline": {
          "$ref": "#/$defs/RunId"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        }
      },
      "required": [
        "run_id"
      ],
      "title": "RunCompareParams",
      "type": "object"
    },
    "RunCompareResult": {
      "$ref": "urn:kookabug:run-index:0#/$defs/CompareResult",
      "description": "run.compare 결과 (run-index.schema.json CompareResult)",
      "title": "RunCompareResult"
    },
    "RunControlResult": {
      "additionalProperties": false,
      "description": "run.pause·run.resume 결과: runner가 답한 상태 (running·pausing·paused·cancelling)",
      "properties": {
        "state": {
          "enum": [
            "cancelling",
            "paused",
            "pausing",
            "running"
          ]
        }
      },
      "required": [
        "state"
      ],
      "title": "RunControlResult",
      "type": "object"
    },
    "RunCropRef": {
      "additionalProperties": false,
      "description": "실행 증거 이미지에서 자른 영역 (kb_target_create의 {run, file} 출처, M5). 에이전트용 비밀값 분류를 지난 이미지만 (아니면 secret_step·unclassified_run·not_evidence)",
      "properties": {
        "file": {
          "description": "실행 폴더 기준 경로 ('/')",
          "minLength": 1,
          "type": "string"
        },
        "rect": {
          "$ref": "#/$defs/Rect"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "file",
        "rect",
        "run_id"
      ],
      "title": "RunCropRef",
      "type": "object"
    },
    "RunDiffParams": {
      "additionalProperties": false,
      "description": "run.diff (kb_run_compare, M5): run.compare와 같은 비교를 두 실행에 3.8(비밀값 분류)을 적용해 준다. baseline을 빼면 지난 성공",
      "properties": {
        "baseline": {
          "$ref": "#/$defs/RunId"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "run_id"
      ],
      "title": "RunDiffParams",
      "type": "object"
    },
    "RunDiffResult": {
      "description": "run.compare 결과(CompareResult)와 같은 모양 + classified. 비밀값 스텝·분류 없는 기록의 화면 파일은 null이고 reason이 secret_step·agent_withheld",
      "title": "RunDiffResult",
      "type": "object"
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
    "RunEventsParams": {
      "additionalProperties": false,
      "description": "run.events (kb_run_events, M5 3.8): after_seq 뒤 이벤트 (secret_paths 자리는 ***, 분류 없는 기록은 안전 필드만). step·kinds로 거른다",
      "properties": {
        "after_seq": {
          "minimum": 0,
          "type": "integer"
        },
        "kinds": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "limit": {
          "maximum": 500,
          "minimum": 1,
          "type": "integer"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        }
      },
      "required": [
        "run_id"
      ],
      "title": "RunEventsParams",
      "type": "object"
    },
    "RunEventsResult": {
      "additionalProperties": false,
      "properties": {
        "classified": {
          "type": "boolean"
        },
        "events": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "next_seq": {
          "minimum": 0,
          "type": "integer"
        },
        "truncated": {
          "type": "boolean"
        }
      },
      "required": [
        "classified",
        "events",
        "next_seq",
        "truncated"
      ],
      "title": "RunEventsResult",
      "type": "object"
    },
    "RunExportParams": {
      "additionalProperties": false,
      "description": "실행 폴더를 zip으로 내보낸다 (Electron 주 프로세스 내부용: dest는 저장 대화 상자가 고른 절대 경로). dest 옆 임시 파일에 쓰고 끝나면 replace. 진행 중 실행은 run_active",
      "properties": {
        "dest": {
          "minLength": 1,
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "dest",
        "run_id"
      ],
      "title": "RunExportParams",
      "type": "object"
    },
    "RunExportResult": {
      "additionalProperties": false,
      "properties": {
        "bytes": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "path": {
          "type": "string"
        }
      },
      "required": [
        "bytes",
        "path"
      ],
      "title": "RunExportResult",
      "type": "object"
    },
    "RunFailureResult": {
      "additionalProperties": false,
      "description": "run.failure (kb_run_status, M5): 실패 요약 — 판정·실패 위치(스텝·노드·출구·오류)·증거 파일(에이전트에게 줄 수 있는 것만)·영상 요약·지난 성공. 사유·메시지는 3.8대로 가린다",
      "properties": {
        "chain": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "classified": {
          "type": "boolean"
        },
        "code": {
          "type": [
            "null",
            "string"
          ]
        },
        "evidence": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "failure": {
          "type": [
            "null",
            "object"
          ]
        },
        "failure_path": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "type": "array"
            },
            {
              "type": "null"
            }
          ]
        },
        "failure_step": {
          "type": [
            "null",
            "string"
          ]
        },
        "last_success": {
          "anyOf": [
            {
              "$ref": "#/$defs/RunId"
            },
            {
              "type": "null"
            }
          ]
        },
        "reason": {
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "state": {
          "enum": [
            "ended",
            "running"
          ]
        },
        "verdict": {
          "type": [
            "null",
            "string"
          ]
        },
        "video": {
          "type": [
            "null",
            "object"
          ]
        }
      },
      "required": [
        "chain",
        "classified",
        "evidence",
        "failure",
        "last_success",
        "run_id",
        "state"
      ],
      "title": "RunFailureResult",
      "type": "object"
    },
    "RunFileParams": {
      "additionalProperties": false,
      "description": "run.json 원문, 또는 events.jsonl 끝부분 (1 MiB까지)",
      "properties": {
        "name": {
          "enum": [
            "events_tail",
            "run.json"
          ]
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "name",
        "run_id"
      ],
      "title": "RunFileParams",
      "type": "object"
    },
    "RunFileResult": {
      "additionalProperties": false,
      "properties": {
        "bytes": {
          "description": "파일 전체 크기",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "text": {
          "type": "string"
        },
        "truncated": {
          "description": "1 MiB를 넘어 앞(events_tail은 뒤만 남김)을 잘랐다",
          "type": "boolean"
        }
      },
      "required": [
        "bytes",
        "text",
        "truncated"
      ],
      "title": "RunFileResult",
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
    "RunIndexResult": {
      "$ref": "urn:kookabug:run-index:0",
      "description": "run.index 결과: 실행 색인 (run-index.schema.json)",
      "title": "RunIndexResult"
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
      "description": "최신순. before는 앞 쪽 결과의 next (그보다 먼저 시작한 실행부터). graph(이 테스트 그래프의 실행만)·verdict(이 판정의 끝난 실행만)는 거르기 (M3)",
      "properties": {
        "before": {
          "description": "쪽 커서 (앞 결과의 next 그대로, 뜻은 daemon만 안다)",
          "minLength": 1,
          "type": "string"
        },
        "graph": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "limit": {
          "maximum": 1000,
          "minimum": 1,
          "type": "integer"
        },
        "verdict": {
          "$ref": "#/$defs/Verdict"
        }
      },
      "title": "RunListParams",
      "type": "object"
    },
    "RunListResult": {
      "additionalProperties": false,
      "description": "최근 실행부터. next가 null이면 마지막 쪽",
      "properties": {
        "next": {
          "type": [
            "null",
            "string"
          ]
        },
        "runs": {
          "items": {
            "$ref": "#/$defs/RunSummary"
          },
          "type": "array"
        },
        "runs_bytes": {
          "description": "runs/ 폴더 합계 크기 (캐시, 1분마다 다시 잼). 모르면 없음",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
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
    "RunResumeIdParams": {
      "additionalProperties": false,
      "description": "run.resume params. mode를 빼면 continue. 멈추지 않은 실행에 Step(step_*)이면 not_paused",
      "properties": {
        "mode": {
          "$ref": "urn:kookabug:events:0#/$defs/ResumeMode"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        }
      },
      "required": [
        "run_id"
      ],
      "title": "RunResumeIdParams",
      "type": "object"
    },
    "RunSearchParams": {
      "additionalProperties": false,
      "description": "run.search (kb_log_search, M5): 가린 뒤의 메시지·오류·사유에서 글자 찾기 (대소문자 무시). runs를 빼면 최근 20개, 분류 없는 기록은 건너뛴다(skipped)",
      "properties": {
        "limit": {
          "maximum": 500,
          "minimum": 1,
          "type": "integer"
        },
        "query": {
          "minLength": 1,
          "type": "string"
        },
        "runs": {
          "items": {
            "$ref": "#/$defs/RunId"
          },
          "type": "array"
        }
      },
      "required": [
        "query"
      ],
      "title": "RunSearchParams",
      "type": "object"
    },
    "RunSearchResult": {
      "additionalProperties": false,
      "properties": {
        "matches": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "kind": {
                "type": [
                  "null",
                  "string"
                ]
              },
              "run": {
                "$ref": "#/$defs/RunId"
              },
              "seq": {
                "type": [
                  "integer",
                  "null"
                ]
              },
              "step": {
                "type": [
                  "null",
                  "string"
                ]
              },
              "text": {
                "type": "string"
              }
            },
            "required": [
              "kind",
              "run",
              "seq",
              "step",
              "text"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "skipped": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "truncated": {
          "type": "boolean"
        }
      },
      "required": [
        "matches",
        "skipped",
        "truncated"
      ],
      "title": "RunSearchResult",
      "type": "object"
    },
    "RunStartParams": {
      "additionalProperties": false,
      "description": "디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy. 이 daemon의 녹화 세션이 starting·recording·paused면 runner를 띄우기 전에 recording_active (M4, 같은 시작 잠금 안에서 판정)",
      "properties": {
        "basis": {
          "description": "M8 3.6 실행 기준: team(팀 파일만) | working(시작 때 작업 기준 덧씌움 고정). 생략하면 작업 연결은 working, 그 밖은 team",
          "enum": [
            "team",
            "working"
          ]
        },
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
    "RunStatusResult": {
      "additionalProperties": false,
      "description": "실행 요약 + 실행 스냅샷의 호출 관계 (화면이 실행 중 강조를 실행한 그래프 파일에 붙인다. 편집 버퍼가 아니라 스냅샷 기준)",
      "properties": {
        "calls": {
          "additionalProperties": {
            "additionalProperties": {
              "$ref": "#/$defs/WorkspacePath"
            },
            "description": "호출 노드 ID → 부르는 서브그래프 (config.graph)",
            "type": "object"
          },
          "description": "스냅샷 그래프 파일(워크스페이스 기준) → 그 그래프의 호출 노드. 스냅샷을 아직 만들지 않았으면 빈 객체",
          "type": "object"
        },
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
        "calls",
        "graph",
        "last_seq",
        "outcome",
        "run_dir",
        "run_id",
        "started_at",
        "state"
      ],
      "title": "RunStatusResult",
      "type": "object"
    },
    "RunStepParams": {
      "additionalProperties": false,
      "properties": {
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        }
      },
      "required": [
        "run_id",
        "step"
      ],
      "title": "RunStepParams",
      "type": "object"
    },
    "RunStepResult": {
      "additionalProperties": false,
      "description": "스텝 하나의 자세한 기록. 파일 경로는 실행 폴더 기준 ('/' 구분, kbimg://ws/<run_dir>/<경로>로 연다)",
      "properties": {
        "events": {
          "description": "그 스텝의 step.start·attempt.end·step.end·log 이벤트 (seq 순)",
          "items": {
            "$ref": "urn:kookabug:events:0"
          },
          "type": "array"
        },
        "ocr_text": {
          "description": "steps/<스텝>_ocr.txt 내용 (없으면 null)",
          "type": [
            "null",
            "string"
          ]
        },
        "run_dir": {
          "description": "실행 폴더 (워크스페이스 기준)",
          "type": "string"
        },
        "step": {
          "$ref": "urn:kookabug:run-index:0#/$defs/StepNode"
        },
        "thumbnail": {
          "description": "썸네일 파일 (thumbs/<스텝>.jpg, 없으면 null)",
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "events",
        "ocr_text",
        "run_dir",
        "step",
        "thumbnail"
      ],
      "title": "RunStepResult",
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
      "description": "실행 요약 (record.reader.read_run). outcome은 끝난 실행만. code부터 아래 필드는 M3 run.list가 채운다(run.json에서 읽고, 없으면 뺀다)",
      "properties": {
        "code": {
          "type": "string"
        },
        "debug_intervened": {
          "description": "배지 \"디버거 개입\"",
          "type": "boolean"
        },
        "duration_ms": {
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "failure_path": {
          "anyOf": [
            {
              "items": {
                "type": "string"
              },
              "minItems": 1,
              "type": "array"
            },
            {
              "type": "null"
            }
          ],
          "description": "실패 위치 호출 경로 (노드 ID)"
        },
        "failure_title": {
          "description": "실패 위치를 노드 제목으로 이은 것 (예: 월드 접속 > 타이틀 대기)",
          "type": "string"
        },
        "flaky": {
          "description": "배지 \"불안정\": 재시도 끝에 성공한 스텝이 있는 pass (run.json retried_steps)",
          "type": "boolean"
        },
        "game_build": {
          "type": [
            "null",
            "string"
          ]
        },
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
        "profile": {
          "type": [
            "null",
            "string"
          ]
        },
        "reason": {
          "type": "string"
        },
        "run_dir": {
          "type": "string"
        },
        "run_id": {
          "$ref": "#/$defs/RunId"
        },
        "source": {
          "description": "배지 \"에이전트 제어\": source agent_control 실행 (M5 3.9, run.json에서)",
          "enum": [
            "agent_control"
          ]
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
    "ScreenMapCard": {
      "additionalProperties": false,
      "description": "화면 지도 카드: 확정 화면(node = ID) 또는 탐색 후보(node = x:<세션>/<키>)",
      "properties": {
        "counts": {
          "additionalProperties": false,
          "properties": {
            "elements": {
              "minimum": 0,
              "type": "integer"
            },
            "moves": {
              "minimum": 0,
              "type": "integer"
            }
          },
          "required": [
            "elements",
            "moves"
          ],
          "type": "object"
        },
        "description": {
          "description": "M7 B5: 화면 설명 (사이드바 선택 섹션)",
          "type": "string"
        },
        "detect_text": {
          "description": "판정 조건 한 줄 (image(\"이름\") && !image(\"이름\") && text(\"글자\"))",
          "type": "string"
        },
        "elements": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "kind": {
                "type": "string"
              },
              "name": {
                "type": "string"
              },
              "rect": {
                "items": {
                  "type": "number"
                },
                "maxItems": 4,
                "minItems": 4,
                "type": "array"
              }
            },
            "required": [
              "kind",
              "name",
              "rect"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "explored_adds": {
          "description": "확정 카드: 이 화면에 합칠 탐색 후보(of) 수 — \"탐색 추가 N\" 배지",
          "minimum": 0,
          "type": "integer"
        },
        "id": {
          "type": "string"
        },
        "incomplete": {
          "description": "후보: 판정 조건도 합칠 화면도 없음 (승격 불가, 사람이 채운다)",
          "type": "boolean"
        },
        "key": {
          "type": "string"
        },
        "kind": {
          "enum": [
            "popup",
            "screen"
          ]
        },
        "node": {
          "type": "string"
        },
        "of": {
          "type": [
            "null",
            "string"
          ]
        },
        "origin": {
          "type": [
            "null",
            "object"
          ]
        },
        "path": {
          "type": "string"
        },
        "problem": {
          "type": [
            "null",
            "string"
          ]
        },
        "promotable": {
          "type": "boolean"
        },
        "session": {
          "type": "string"
        },
        "state": {
          "enum": [
            "confirmed",
            "explored"
          ]
        },
        "thumb": {
          "description": "대표 스크린샷 썸네일 캐시 이름 (사람 연결만 — 에이전트는 늘 null)",
          "type": [
            "null",
            "string"
          ]
        },
        "title": {
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "counts",
        "detect_text",
        "elements",
        "kind",
        "node",
        "origin",
        "path",
        "problem",
        "state",
        "thumb",
        "title"
      ],
      "title": "ScreenMapCard",
      "type": "object"
    },
    "ScreenMapEdge": {
      "additionalProperties": false,
      "properties": {
        "from": {
          "type": "string"
        },
        "label": {
          "type": "string"
        },
        "note": {
          "type": "string"
        },
        "pending": {
          "description": "확인 전 간선 (of 후보의 이동)",
          "type": "boolean"
        },
        "sources": {
          "items": {
            "type": "object"
          },
          "type": "array"
        },
        "status": {
          "enum": [
            "tried",
            "untried"
          ]
        },
        "to": {
          "type": [
            "null",
            "string"
          ]
        },
        "unresolved": {
          "description": "to를 찾지 못한 이름 (to는 null)",
          "type": "string"
        },
        "via": {
          "type": "object"
        }
      },
      "required": [
        "from",
        "label",
        "sources",
        "status",
        "to",
        "via"
      ],
      "title": "ScreenMapEdge",
      "type": "object"
    },
    "ScreenReadTextParams": {
      "additionalProperties": false,
      "description": "screen.read_text (kb_ocr_read, M5): 정지 화면(창 캡처) 영역의 글자. rect를 빼면 전체. 녹화 세션 프레임은 recorder_frame, sensitive target이 보이는 영역과 겹치면 sensitive_region",
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
        "frame_id"
      ],
      "title": "ScreenReadTextParams",
      "type": "object"
    },
    "ScreensChangedParams": {
      "additionalProperties": false,
      "description": "M7: screens/ 아래 화면 지도 파일이 바뀜 (ui 연결에만). 화면 지도 탭은 screens.map을 다시 부른다",
      "properties": {
        "revision": {
          "type": "string"
        }
      },
      "required": [
        "revision"
      ],
      "title": "ScreensChangedParams",
      "type": "object"
    },
    "ScreensCheckParams": {
      "additionalProperties": false,
      "description": "screens.check (사람만, M7 3.7): 후보 하나를 승격하기 전에 확인 (쓰지 않음). 승격과 같은 mode·id·folder·replace_*를 주면 그 승격이 고칠 파일의 revision을 준다",
      "properties": {
        "folder": {
          "type": "string"
        },
        "id": {
          "type": "string"
        },
        "key": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "mode": {
          "enum": [
            "merge",
            "new"
          ]
        },
        "replace_detect": {
          "type": "boolean"
        },
        "replace_shot": {
          "type": "boolean"
        },
        "session": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "key",
        "session"
      ],
      "title": "ScreensCheckParams",
      "type": "object"
    },
    "ScreensCheckResult": {
      "additionalProperties": false,
      "properties": {
        "code": {
          "description": "승격할 수 없을 때 그 이유의 오류 코드 (screen_exists·validation_failed·not_found·exists)",
          "type": "string"
        },
        "id": {
          "description": "승격될 화면 ID (new는 새 ID, merge는 합칠 화면)",
          "type": "string"
        },
        "ok": {
          "description": "후보 판정 조건이 자기 스크린샷에서 맞고 승격을 막는 것이 없다",
          "type": "boolean"
        },
        "path": {
          "description": "승격 뒤 화면 파일 (워크스페이스 기준)",
          "type": "string"
        },
        "problems": {
          "description": "승격을 막는 것 (있으면 ok는 false)",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "revisions": {
          "additionalProperties": {
            "type": [
              "null",
              "string"
            ]
          },
          "description": "승격이 고칠 파일 → 지금 revision (없는 파일은 null). screens.promote의 base_revisions로 그대로 넘긴다",
          "type": "object"
        },
        "shot": {
          "description": "후보 판정 조건을 그 대표 스크린샷에서 평가한 결과 (matched·not_matched·unknown·none = 스크린샷 없음)",
          "enum": [
            "matched",
            "none",
            "not_matched",
            "unknown"
          ]
        },
        "warnings": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "ok",
        "problems",
        "revisions",
        "warnings"
      ],
      "title": "ScreensCheckResult",
      "type": "object"
    },
    "ScreensDiscardParams": {
      "additionalProperties": false,
      "description": "screens.discard (사람만, M7 3.7): 끝난 탐색 세션의 후보 하나(key) 또는 세션 전체를 지운다. 처리기는 B4",
      "properties": {
        "key": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "session": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "session"
      ],
      "title": "ScreensDiscardParams",
      "type": "object"
    },
    "ScreensDiscardResult": {
      "additionalProperties": false,
      "properties": {
        "removed": {
          "description": "지운 파일 (워크스페이스 기준)",
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "removed"
      ],
      "title": "ScreensDiscardResult",
      "type": "object"
    },
    "ScreensGetParams": {
      "additionalProperties": false,
      "description": "screens.get (kb_screen_get, M5): screens/ 아래 *.screen.json 하나",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        }
      },
      "required": [
        "path"
      ],
      "title": "ScreensGetParams",
      "type": "object"
    },
    "ScreensGetResult": {
      "additionalProperties": false,
      "description": "읽을 수 없거나 형식이 틀리면 problem",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "problem": {
          "type": "string"
        },
        "value": {}
      },
      "required": [
        "path"
      ],
      "title": "ScreensGetResult",
      "type": "object"
    },
    "ScreensIdentifyMatch": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "key": {
          "type": "string"
        },
        "node": {
          "type": "string"
        },
        "state": {
          "enum": [
            "confirmed",
            "explored"
          ]
        },
        "title": {
          "type": [
            "string",
            "null"
          ]
        }
      },
      "required": [
        "node",
        "state",
        "title"
      ],
      "title": "ScreensIdentifyMatch",
      "type": "object"
    },
    "ScreensIdentifyParams": {
      "additionalProperties": false,
      "description": "screens.identify (kb_screen_identify, M7 3.6): 정지 화면이 어느 화면인지 (확정 화면 + 자기 탐색 세션 후보)",
      "properties": {
        "frame_id": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "frame_id"
      ],
      "title": "ScreensIdentifyParams",
      "type": "object"
    },
    "ScreensIdentifyResult": {
      "additionalProperties": false,
      "description": "matches 맞는 화면, unknown 확인하지 못한 조건이 남은 화면(보호 프레임의 OCR 조건 등). 읽은 글자는 넣지 않는다",
      "properties": {
        "checked": {
          "minimum": 0,
          "type": "integer"
        },
        "matches": {
          "items": {
            "$ref": "#/$defs/ScreensIdentifyMatch"
          },
          "type": "array"
        },
        "problems": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "node": {
                "type": "string"
              },
              "problem": {
                "type": "string"
              }
            },
            "required": [
              "node",
              "problem"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "unknown": {
          "items": {
            "$ref": "#/$defs/ScreensIdentifyMatch"
          },
          "type": "array"
        }
      },
      "required": [
        "checked",
        "matches",
        "problems",
        "unknown"
      ],
      "title": "ScreensIdentifyResult",
      "type": "object"
    },
    "ScreensLayout": {
      "additionalProperties": false,
      "description": "screens.layout_get/set (사람만, M7 3.8): 화면 지도 카드 배치 .kookabug/screen-map.json. 처리기는 B5",
      "properties": {
        "layout": {
          "description": "화면 ID·후보 → 카드 자리",
          "type": "object"
        },
        "revision": {
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "layout",
        "revision"
      ],
      "title": "ScreensLayout",
      "type": "object"
    },
    "ScreensLayoutSetParams": {
      "additionalProperties": false,
      "properties": {
        "base_revision": {
          "type": [
            "null",
            "string"
          ]
        },
        "layout": {
          "type": "object"
        }
      },
      "required": [
        "base_revision",
        "layout"
      ],
      "title": "ScreensLayoutSetParams",
      "type": "object"
    },
    "ScreensListParams": {
      "additionalProperties": false,
      "description": "screens.list (kb_screen_list, M5): under(screens/ 기준 또는 워크스페이스 기준 폴더) 아래 화면 지도",
      "properties": {
        "under": {
          "type": "string"
        }
      },
      "title": "ScreensListParams",
      "type": "object"
    },
    "ScreensListResult": {
      "additionalProperties": false,
      "properties": {
        "screens": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "explored": {
                "const": true
              },
              "id": {
                "type": "string"
              },
              "path": {
                "$ref": "#/$defs/WorkspacePath"
              },
              "problem": {
                "type": "string"
              },
              "title": {
                "type": "string"
              }
            },
            "required": [
              "id",
              "path"
            ],
            "type": "object"
          },
          "type": "array"
        }
      },
      "required": [
        "screens"
      ],
      "title": "ScreensListResult",
      "type": "object"
    },
    "ScreensMapResult": {
      "additionalProperties": false,
      "description": "screens.map (kb_screen_list, M7 3.3): 화면 지도 카드·이동 그래프·탐색 세션",
      "properties": {
        "edges": {
          "items": {
            "$ref": "#/$defs/ScreenMapEdge"
          },
          "type": "array"
        },
        "merges": {
          "description": "M7 B5: 카드로 그리지 않는 합치기 후보(of) — 확정 카드의 \"탐색 추가 N\"과 \"확인 전\" 묶음",
          "items": {
            "additionalProperties": false,
            "properties": {
              "counts": {
                "additionalProperties": false,
                "properties": {
                  "elements": {
                    "minimum": 0,
                    "type": "integer"
                  },
                  "moves": {
                    "minimum": 0,
                    "type": "integer"
                  }
                },
                "required": [
                  "elements",
                  "moves"
                ],
                "type": "object"
              },
              "key": {
                "type": "string"
              },
              "node": {
                "type": "string"
              },
              "of": {
                "type": "string"
              },
              "path": {
                "type": "string"
              },
              "session": {
                "type": "string"
              },
              "title": {
                "type": [
                  "null",
                  "string"
                ]
              }
            },
            "required": [
              "counts",
              "key",
              "node",
              "of",
              "path",
              "session",
              "title"
            ],
            "title": "ScreenMapMerge",
            "type": "object"
          },
          "type": "array"
        },
        "revision": {
          "type": "string"
        },
        "screens": {
          "items": {
            "$ref": "#/$defs/ScreenMapCard"
          },
          "type": "array"
        },
        "sessions": {
          "items": {
            "$ref": "#/$defs/ExploreSessionInfo"
          },
          "type": "array"
        },
        "start": {
          "description": "배치 시작 화면 (들어오는 tried 간선이 없는 확정 화면 중 첫째)",
          "type": [
            "null",
            "string"
          ]
        }
      },
      "required": [
        "edges",
        "revision",
        "screens",
        "sessions",
        "start"
      ],
      "title": "ScreensMapResult",
      "type": "object"
    },
    "ScreensPromoteParams": {
      "additionalProperties": false,
      "description": "screens.promote (사람만, M7 3.7): 후보를 확정 화면으로 옮기거나(new) 기존 화면에 합친다(merge). screens.lock 안 저널 거래. 처리기는 B4",
      "properties": {
        "base_revisions": {
          "additionalProperties": {
            "type": [
              "null",
              "string"
            ]
          },
          "description": "screens.check가 준 revisions 그대로. 하나라도 다르면 revision_conflict",
          "type": "object"
        },
        "description": {
          "type": "string"
        },
        "folder": {
          "type": "string"
        },
        "id": {
          "type": "string"
        },
        "key": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "mode": {
          "enum": [
            "merge",
            "new"
          ]
        },
        "replace_detect": {
          "type": "boolean"
        },
        "replace_shot": {
          "type": "boolean"
        },
        "session": {
          "minLength": 1,
          "type": "string"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "base_revisions",
        "key",
        "mode",
        "session"
      ],
      "title": "ScreensPromoteParams",
      "type": "object"
    },
    "ScreensPromoteResult": {
      "additionalProperties": false,
      "properties": {
        "cleanup_pending": {
          "description": "커밋은 됐고 마무리(후보 지우기·explore.json)가 남았다 — 다음 잠금 때 끝낸다",
          "type": "boolean"
        },
        "id": {
          "type": "string"
        },
        "path": {
          "description": "승격된 화면 파일 (워크스페이스 기준)",
          "type": "string"
        },
        "warnings": {
          "items": {
            "type": "string"
          },
          "type": "array"
        }
      },
      "required": [
        "cleanup_pending",
        "id",
        "path",
        "warnings"
      ],
      "title": "ScreensPromoteResult",
      "type": "object"
    },
    "ScreensSaveCondition": {
      "description": "image = 이 영역을 잘라 이미지 조건으로, ocr = 이 영역에 text가 있어야 (프레임 물리 픽셀)",
      "oneOf": [
        {
          "additionalProperties": false,
          "properties": {
            "image": {
              "$ref": "#/$defs/Rect"
            }
          },
          "required": [
            "image"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "ocr": {
              "$ref": "#/$defs/Rect"
            },
            "text": {
              "minLength": 1,
              "type": "string"
            }
          },
          "required": [
            "ocr",
            "text"
          ],
          "type": "object"
        }
      ],
      "title": "ScreensSaveCondition"
    },
    "ScreensSaveParams": {
      "additionalProperties": false,
      "description": "screens.save (kb_screen_save, M7 3.5): 자기 탐색 세션 폴더의 후보 카드 하나를 저장·갱신. 글자 필드는 비밀값 검사(3.5b)를 지난다",
      "properties": {
        "description": {
          "type": "string"
        },
        "detect": {
          "additionalProperties": false,
          "properties": {
            "all": {
              "items": {
                "$ref": "#/$defs/ScreensSaveCondition"
              },
              "type": "array"
            },
            "none": {
              "items": {
                "$ref": "#/$defs/ScreensSaveCondition"
              },
              "type": "array"
            }
          },
          "type": "object"
        },
        "elements": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "kind": {
                "enum": [
                  "button",
                  "field",
                  "list",
                  "text"
                ]
              },
              "name": {
                "minLength": 1,
                "type": "string"
              },
              "rect": {
                "$ref": "#/$defs/Rect"
              }
            },
            "required": [
              "kind",
              "name",
              "rect"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "frame_id": {
          "minLength": 1,
          "type": "string"
        },
        "key": {
          "pattern": "^[a-z][a-z0-9_]{0,63}$",
          "type": "string"
        },
        "kind": {
          "enum": [
            "popup",
            "screen"
          ]
        },
        "moves": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "note": {
                "type": "string"
              },
              "status": {
                "enum": [
                  "tried",
                  "untried"
                ]
              },
              "to": {
                "type": [
                  "string",
                  "null"
                ]
              },
              "via": {
                "$ref": "#/$defs/ScreensSaveVia"
              }
            },
            "required": [
              "status",
              "via"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "of": {
          "type": "string"
        },
        "title": {
          "type": "string"
        }
      },
      "required": [
        "frame_id",
        "key"
      ],
      "title": "ScreensSaveParams",
      "type": "object"
    },
    "ScreensSaveResult": {
      "additionalProperties": false,
      "properties": {
        "also_matches": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "node": {
                "type": "string"
              },
              "title": {
                "type": [
                  "string",
                  "null"
                ]
              }
            },
            "required": [
              "node",
              "title"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "incomplete": {
          "const": true
        },
        "key": {
          "type": "string"
        },
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        },
        "reason": {
          "description": "shot omitted의 보호 사유",
          "type": "string"
        },
        "revision": {
          "type": "string"
        },
        "shot": {
          "enum": [
            "omitted",
            "saved"
          ]
        }
      },
      "required": [
        "also_matches",
        "key",
        "path",
        "revision",
        "shot"
      ],
      "title": "ScreensSaveResult",
      "type": "object"
    },
    "ScreensSaveVia": {
      "description": "이동 입력: 요소 클릭·점 클릭(프레임 물리 픽셀)·키",
      "oneOf": [
        {
          "additionalProperties": false,
          "properties": {
            "click": {
              "additionalProperties": false,
              "properties": {
                "element": {
                  "minLength": 1,
                  "type": "string"
                }
              },
              "required": [
                "element"
              ],
              "type": "object"
            }
          },
          "required": [
            "click"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "click": {
              "additionalProperties": false,
              "properties": {
                "point": {
                  "items": {
                    "maximum": 9007199254740991,
                    "minimum": 0,
                    "type": "integer"
                  },
                  "maxItems": 2,
                  "minItems": 2,
                  "type": "array"
                }
              },
              "required": [
                "point"
              ],
              "type": "object"
            }
          },
          "required": [
            "click"
          ],
          "type": "object"
        },
        {
          "additionalProperties": false,
          "properties": {
            "key": {
              "minLength": 1,
              "type": "string"
            }
          },
          "required": [
            "key"
          ],
          "type": "object"
        }
      ],
      "title": "ScreensSaveVia"
    },
    "SecretKey": {
      "description": "비밀값 키 (그래프 $secret 키와 같은 규칙)",
      "pattern": "^[A-Za-z0-9_]+(\\.[A-Za-z0-9_]+)*$",
      "title": "SecretKey",
      "type": "string"
    },
    "SecretKeyInfo": {
      "additionalProperties": false,
      "description": "비밀값 키 하나 (값 없음). source credential = 자격 증명 관리자 kookabug:<워크스페이스 ID>:<키>",
      "properties": {
        "key": {
          "$ref": "#/$defs/SecretKey"
        },
        "source": {
          "const": "credential"
        }
      },
      "required": [
        "key",
        "source"
      ],
      "title": "SecretKeyInfo",
      "type": "object"
    },
    "SecretsCreateParams": {
      "additionalProperties": false,
      "description": "secrets.create: 녹화 스텝(from_step, 비밀값·확인 필요 글자 구간)의 메모리 원문을 자격 증명 관리자에 그 키로 쓴다. 값을 RPC로 받지 않는다. 키가 이미 있으면 exists",
      "properties": {
        "from_step": {
          "$ref": "#/$defs/RecorderStepId"
        },
        "key": {
          "$ref": "#/$defs/SecretKey"
        }
      },
      "required": [
        "from_step",
        "key"
      ],
      "title": "SecretsCreateParams",
      "type": "object"
    },
    "SecretsListResult": {
      "additionalProperties": false,
      "description": "secrets.list: 자격 증명 관리자의 이 워크스페이스 키 (값 없음). 환경 변수(KOOKABUG_SECRET_<키>)는 원래 키 이름을 되살릴 수 없어 목록에 없고 env_note로 안내한다",
      "properties": {
        "env_note": {
          "type": "string"
        },
        "keys": {
          "items": {
            "$ref": "#/$defs/SecretKeyInfo"
          },
          "type": "array"
        }
      },
      "required": [
        "env_note",
        "keys"
      ],
      "title": "SecretsListResult",
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
    "StepId": {
      "pattern": "^s[1-9][0-9]*$",
      "title": "StepId",
      "type": "string"
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
        "scales": {
          "description": "다른 배율 점수 (M4 T11): 정지 화면을 이 배율로 바꿔 같은 사양으로 찾는다. 결과 scale_scores (편집기 접힌 줄 '다른 배율에서'를 펼쳤을 때만 보낸다)",
          "items": {
            "maximum": 4,
            "minimum": 0.25,
            "type": "number"
          },
          "maxItems": 6,
          "type": "array"
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
    "TargetReadTextParams": {
      "additionalProperties": false,
      "description": "target.read_text: 편집기 정지 화면 영역의 글자 (OCR). 녹화 프레임의 보호 영역과 겹치면 secret_region_overlap",
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
      "title": "TargetReadTextParams",
      "type": "object"
    },
    "TargetReadTextResult": {
      "additionalProperties": false,
      "properties": {
        "lines": {
          "items": {
            "additionalProperties": false,
            "properties": {
              "rect": {
                "$ref": "#/$defs/Rect"
              },
              "score": {
                "maximum": 1,
                "minimum": 0,
                "type": "number"
              },
              "text": {
                "type": "string"
              }
            },
            "required": [
              "rect",
              "score",
              "text"
            ],
            "type": "object"
          },
          "type": "array"
        },
        "text": {
          "type": "string"
        }
      },
      "required": [
        "lines",
        "text"
      ],
      "title": "TargetReadTextResult",
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
          "anyOf": [
            {
              "$ref": "#/$defs/CropRef"
            },
            {
              "$ref": "#/$defs/RunCropRef"
            }
          ]
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
        "basis": {
          "description": "M8 E3: 작업 기준으로 썼으면 working (팀 파일은 그대로)",
          "enum": [
            "working"
          ]
        },
        "change": {
          "description": "M8 E3: 쓴 작업 기준 변경 ID",
          "type": "string"
        },
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
      "description": "권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon의 AGENT_DENIED 목록 — daemon.shutdown, M3 디버그 메서드 debug.breakpoints.get·set·run.pause·run.resume·run.restart, run.export, M4 녹화·비밀값 메서드 recorder.*·secrets.*·target.read_text — 를 판정 전에 거부)",
      "enum": [
        "kb_adopt_request",
        "kb_app_launch",
        "kb_case_get",
        "kb_case_list",
        "kb_case_open",
        "kb_case_update",
        "kb_evidence_pin",
        "kb_explore_end",
        "kb_explore_start",
        "kb_graph_create",
        "kb_graph_get",
        "kb_graph_list",
        "kb_graph_patch",
        "kb_graph_validate",
        "kb_image_find",
        "kb_input_click",
        "kb_input_key",
        "kb_input_type",
        "kb_knowledge_apply",
        "kb_knowledge_get",
        "kb_knowledge_search",
        "kb_log_search",
        "kb_node_search",
        "kb_ocr_read",
        "kb_project_info",
        "kb_report_note",
        "kb_run_artifact_get",
        "kb_run_cancel",
        "kb_run_compare",
        "kb_run_events",
        "kb_run_start",
        "kb_run_status",
        "kb_screen_capture",
        "kb_screen_get",
        "kb_screen_identify",
        "kb_screen_list",
        "kb_screen_save",
        "kb_setting_propose",
        "kb_source_list",
        "kb_source_read",
        "kb_target_create",
        "kb_toolset_enable",
        "kb_triage_signals",
        "kb_wiki_write",
        "ui_only"
      ],
      "title": "ToolName",
      "type": "string"
    },
    "Toolset": {
      "description": "MCP 툴셋 (구현 계획 7장). core는 늘 켜져 있다",
      "enum": [
        "cases",
        "control",
        "core",
        "graph_edit",
        "knowledge",
        "observe",
        "run",
        "screens"
      ],
      "title": "Toolset",
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
    "Ux2SettingProposeParams": {
      "additionalProperties": false,
      "description": "setting.propose (kb_setting_propose): 작업 토큰 연결 전용. 사람 답을 설정에 반영하자는 제안 (설정은 바꾸지 않는다 — 사람이 보고함에서 수락). key는 허용 목록뿐",
      "properties": {
        "key": {
          "description": "허용 목록: game.title·game.executable·game.args·game.cwd·sources.add·cheats.categories.add·automation.forbidden.add (밖이면 setting_not_allowed)",
          "minLength": 1,
          "type": "string"
        },
        "reason": {
          "minLength": 1,
          "type": "string"
        },
        "unknowns": {
          "items": {
            "pattern": "^u-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$",
            "type": "string"
          },
          "type": "array"
        },
        "value": {
          "description": "game.title·executable·cwd: 글, game.args: 글 목록, sources.add: {kind, location, title?}, cheats.categories.add: {id, title, description?, unattended}, automation.forbidden.add: {kind: text, value}·{kind: target, path}·{kind: screen, id}"
        }
      },
      "required": [
        "key",
        "reason",
        "value"
      ],
      "title": "Ux2SettingProposeParams",
      "type": "object"
    },
    "Ux2SettingProposeResult": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "job": {
          "type": "string"
        },
        "key": {
          "type": "string"
        }
      },
      "required": [
        "id",
        "job",
        "key"
      ],
      "title": "Ux2SettingProposeResult",
      "type": "object"
    },
    "Ux2SourceEntry": {
      "additionalProperties": false,
      "properties": {
        "bytes": {
          "minimum": 0,
          "type": "integer"
        },
        "name": {
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
        "name",
        "type"
      ],
      "title": "Ux2SourceEntry",
      "type": "object"
    },
    "Ux2SourceState": {
      "additionalProperties": false,
      "properties": {
        "id": {
          "type": "string"
        },
        "kind": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "state": {
          "enum": [
            "missing",
            "ok",
            "unchecked_url",
            "unreadable"
          ]
        },
        "title": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "type": {
          "anyOf": [
            {
              "enum": [
                "dir",
                "file"
              ]
            },
            {
              "type": "null"
            }
          ]
        }
      },
      "required": [
        "id",
        "kind",
        "state",
        "title",
        "type"
      ],
      "title": "Ux2SourceState",
      "type": "object"
    },
    "Ux2SourcesListParams": {
      "additionalProperties": false,
      "description": "sources.list (kb_source_list): source 없으면 등록된 원본 목록, 있으면 그 원본(폴더면 path 아래 한 단계 항목, 500개까지)",
      "properties": {
        "path": {
          "description": "원본 루트 기준 상대 경로 ('/'). 비면 루트",
          "type": "string"
        },
        "source": {
          "pattern": "^[A-Za-z0-9_.-]{1,64}$",
          "type": "string"
        }
      },
      "title": "Ux2SourcesListParams",
      "type": "object"
    },
    "Ux2SourcesListResult": {
      "additionalProperties": false,
      "properties": {
        "bytes": {
          "minimum": 0,
          "type": "integer"
        },
        "entries": {
          "items": {
            "$ref": "#/$defs/Ux2SourceEntry"
          },
          "type": "array"
        },
        "kind": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "path": {
          "type": "string"
        },
        "source": {
          "type": "string"
        },
        "sources": {
          "items": {
            "$ref": "#/$defs/Ux2SourceState"
          },
          "type": "array"
        },
        "title": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ]
        },
        "truncated": {
          "type": "boolean"
        },
        "type": {
          "enum": [
            "dir",
            "file"
          ]
        }
      },
      "title": "Ux2SourcesListResult",
      "type": "object"
    },
    "Ux2SourcesReadParams": {
      "additionalProperties": false,
      "description": "sources.read (kb_source_read): 등록된 원본 파일 하나의 글 (텍스트·docx·xlsx·pptx, 200 KB씩 — 나머지는 offset으로). 비밀값은 가린다",
      "properties": {
        "offset": {
          "description": "글자 단위 (앞 결과의 next_offset)",
          "minimum": 0,
          "type": "integer"
        },
        "path": {
          "description": "원본 루트 기준 상대 경로 ('/'). 비면 루트",
          "type": "string"
        },
        "source": {
          "pattern": "^[A-Za-z0-9_.-]{1,64}$",
          "type": "string"
        }
      },
      "required": [
        "source"
      ],
      "title": "Ux2SourcesReadParams",
      "type": "object"
    },
    "Ux2SourcesReadResult": {
      "additionalProperties": false,
      "properties": {
        "bytes": {
          "minimum": 0,
          "type": "integer"
        },
        "chars": {
          "minimum": 0,
          "type": "integer"
        },
        "format": {
          "enum": [
            "docx",
            "pptx",
            "text",
            "xlsx"
          ]
        },
        "hash": {
          "type": "string"
        },
        "next_offset": {
          "anyOf": [
            {
              "minimum": 0,
              "type": "integer"
            },
            {
              "type": "null"
            }
          ]
        },
        "offset": {
          "minimum": 0,
          "type": "integer"
        },
        "path": {
          "type": "string"
        },
        "ref": {
          "description": "source 근거 ref (sources:<원본 ID>#<경로>)",
          "type": "string"
        },
        "source": {
          "type": "string"
        },
        "text": {
          "type": "string"
        }
      },
      "required": [
        "bytes",
        "chars",
        "format",
        "hash",
        "next_offset",
        "offset",
        "path",
        "ref",
        "source",
        "text"
      ],
      "title": "Ux2SourcesReadResult",
      "type": "object"
    },
    "Verdict": {
      "enum": [
        "error",
        "fail",
        "pass",
        "skipped"
      ],
      "title": "Verdict",
      "type": "string"
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
        "agents_md": {
          "description": "AGENTS.md의 Kookabug 관리 구간 (없으면 null, M5 3.12)",
          "type": [
            "null",
            "string"
          ]
        },
        "deadline_ms": {
          "description": "run.start에 deadline_ms를 주지 않았을 때의 실행 전체 기한 (kookabug.json run.deadline_ms, 없으면 30분). 실행 툴바의 기한 고르기가 \"기본\"에 보인다",
          "maximum": 9007199254740991,
          "minimum": 1,
          "type": "integer"
        },
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
        "retention": {
          "additionalProperties": false,
          "description": "실행 기록 보관 정책 (kookabug.json retention, 없는 값은 기본값: 통과 14일·실패 60일·최근 50개). 기록 뷰어 상태 바 문구용 (M3 T11). 정리는 보류 H1",
          "properties": {
            "failed_days": {
              "minimum": 0,
              "type": "integer"
            },
            "keep_last": {
              "minimum": 0,
              "type": "integer"
            },
            "passed_days": {
              "minimum": 0,
              "type": "integer"
            }
          },
          "required": [
            "failed_days",
            "keep_last",
            "passed_days"
          ],
          "type": "object"
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
    "WorkspaceReadParams": {
      "additionalProperties": false,
      "description": "탐색기에 보이는 파일 하나의 내용 (보기 탭, 읽기 전용). 범위는 workspace.tree와 같다: tests·subgraphs·targets·screens 아래와 루트의 kookabug.json·kookabug.lock·AGENTS.md",
      "properties": {
        "path": {
          "$ref": "#/$defs/WorkspacePath"
        }
      },
      "required": [
        "path"
      ],
      "title": "WorkspaceReadParams",
      "type": "object"
    },
    "WorkspaceReadResult": {
      "additionalProperties": false,
      "properties": {
        "binary": {
          "description": "글자 파일이 아니다 (앞부분에 NUL 바이트가 있다). text는 빈 문자열",
          "type": "boolean"
        },
        "bytes": {
          "description": "파일 전체 크기",
          "maximum": 9007199254740991,
          "minimum": 0,
          "type": "integer"
        },
        "text": {
          "description": "UTF-8로 읽은 앞부분 (1 MiB까지, 깨진 바이트는 U+FFFD)",
          "type": "string"
        },
        "truncated": {
          "description": "1 MiB를 넘어 뒤를 잘랐다",
          "type": "boolean"
        }
      },
      "required": [
        "binary",
        "bytes",
        "text",
        "truncated"
      ],
      "title": "WorkspaceReadResult",
      "type": "object"
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
