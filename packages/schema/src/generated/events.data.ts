/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

export const eventsSchema: unknown = {
  "$defs": {
    "AttemptEndEvent": {
      "additionalProperties": false,
      "description": "재시도할 중간 시도의 실패. 판정에는 들어가지 않는다",
      "properties": {
        "attempt": {
          "minimum": 1,
          "type": "integer"
        },
        "duration_ms": {
          "minimum": 0,
          "type": "integer"
        },
        "event": {
          "const": "attempt.end"
        },
        "exit": {
          "type": [
            "null",
            "string"
          ]
        },
        "iteration": {
          "description": "반복 안 스텝의 회차 (0부터)",
          "minimum": 0,
          "type": "integer"
        },
        "message": {
          "type": "string"
        },
        "outputs": {
          "type": "object"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "secret_paths": {
          "$ref": "#/$defs/SecretPaths"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "status": {
          "const": "fail"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "attempt",
        "duration_ms",
        "event",
        "exit",
        "outputs",
        "run",
        "seq",
        "status",
        "step",
        "t"
      ],
      "title": "AttemptEndEvent",
      "type": "object"
    },
    "CallPath": {
      "description": "호출 경로: 테스트부터의 호출 노드들 + 노드",
      "items": {
        "type": "string"
      },
      "minItems": 1,
      "title": "CallPath",
      "type": "array"
    },
    "CancelReason": {
      "description": "취소 사유: 외부 취소, 테스트 전체 기한 초과, 감독자 사망",
      "enum": [
        "cancelled",
        "deadline_exceeded",
        "supervisor_lost"
      ],
      "title": "CancelReason",
      "type": "string"
    },
    "CancelRequestedEvent": {
      "additionalProperties": false,
      "description": "runner가 취소 순서를 시작했다",
      "properties": {
        "event": {
          "const": "cancel.requested"
        },
        "reason": {
          "$ref": "#/$defs/CancelReason"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "reason",
        "run",
        "seq",
        "t"
      ],
      "title": "CancelRequestedEvent",
      "type": "object"
    },
    "ControlLostEvent": {
      "additionalProperties": false,
      "description": "제어 채널이 끊겼다. 감독자는 살아 있으므로 취소가 아니다",
      "properties": {
        "error": {
          "type": "string"
        },
        "event": {
          "const": "control.lost"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "run",
        "seq",
        "t"
      ],
      "title": "ControlLostEvent",
      "type": "object"
    },
    "DebugPauseEvent": {
      "additionalProperties": false,
      "description": "멈춤 확정. step은 경계 멈춤이면 다음에 시작할 스텝(아직 step.start 전), 폴링 멈춤이면 기다리던 스텝. node·graph·path·reason·where는 M3부터 (M0b 기록에는 없다)",
      "properties": {
        "event": {
          "const": "debug.pause"
        },
        "graph": {
          "description": "멈춘 노드가 든 그래프 (워크스페이스 기준, 브레이크포인트 열쇠와 같은 경로)",
          "type": "string"
        },
        "node": {
          "type": "string"
        },
        "path": {
          "$ref": "#/$defs/CallPath"
        },
        "reason": {
          "description": "breakpoint: 브레이크포인트 적중, step: Step 목표 경계, request: 일시정지 요청",
          "enum": [
            "breakpoint",
            "request",
            "step"
          ]
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        },
        "where": {
          "description": "boundary: 스텝 시작 직전, poll: 코어 노드의 멈출 수 있는 기다림 안 (일시정지 요청만)",
          "enum": [
            "boundary",
            "poll"
          ]
        }
      },
      "required": [
        "event",
        "run",
        "seq",
        "t"
      ],
      "title": "DebugPauseEvent",
      "type": "object"
    },
    "DebugResumeEvent": {
      "additionalProperties": false,
      "description": "재개. mode·epoch·paused_ms는 M3부터 (M0b 기록에는 없다)",
      "properties": {
        "epoch": {
          "description": "재개 뒤의 관측 세대 (재개마다 1 오른다. 이보다 오래된 관측값으로는 입력·분기하지 않는다)",
          "minimum": 1,
          "type": "integer"
        },
        "event": {
          "const": "debug.resume"
        },
        "mode": {
          "$ref": "#/$defs/ResumeMode"
        },
        "paused_ms": {
          "description": "이번 멈춤의 길이 (멈춤 확정부터 재개까지, 기한에서 뺀 시간)",
          "minimum": 0,
          "type": "integer"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "run",
        "seq",
        "t"
      ],
      "title": "DebugResumeEvent",
      "type": "object"
    },
    "EvidenceCandidate": {
      "additionalProperties": false,
      "description": "매칭 후보 하나. rect는 찾은 이미지 좌표(코어 노드는 창 전체 캡처라 _fail과 같다). 후보끼리는 서로 다른 자리다(점수 지도 봉우리에서 고르면 겹치지 않는다. 프레임 저장소가 없거나 봉우리 다시 고르기를 못 한 경우의 대체 경로는 크게 겹치는 것(IoU 0.3 초과)만 하나로 줄여 조금 겹칠 수 있다)",
      "properties": {
        "rect": {
          "description": "[x, y, w, h] 픽셀",
          "items": {
            "type": "integer"
          },
          "maxItems": 4,
          "minItems": 4,
          "type": "array"
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
      "title": "EvidenceCandidate",
      "type": "object"
    },
    "FinalizedBy": {
      "description": "실행을 마무리한 쪽: runner 자신, 또는 runner가 죽은 뒤 감독자",
      "enum": [
        "runner",
        "supervisor"
      ],
      "title": "FinalizedBy",
      "type": "string"
    },
    "InputDownEvent": {
      "additionalProperties": false,
      "description": "입력 액터가 백엔드에 누르기를 보내기 전에 쓴다",
      "else": {
        "not": {
          "required": [
            "key"
          ]
        },
        "required": [
          "button"
        ]
      },
      "if": {
        "properties": {
          "device": {
            "const": "keyboard"
          }
        }
      },
      "properties": {
        "button": {
          "minLength": 1,
          "type": "string"
        },
        "device": {
          "enum": [
            "keyboard",
            "mouse"
          ]
        },
        "event": {
          "const": "input.down"
        },
        "key": {
          "minLength": 1,
          "type": "string"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "device",
        "event",
        "run",
        "seq",
        "t"
      ],
      "then": {
        "not": {
          "required": [
            "button"
          ]
        },
        "required": [
          "key"
        ]
      },
      "title": "InputDownEvent",
      "type": "object"
    },
    "InputRecoveredEvent": {
      "additionalProperties": false,
      "description": "앞 실행(from_run)에서 눌렸을 수 있는 키·버튼을 뗐다",
      "properties": {
        "by": {
          "additionalProperties": false,
          "properties": {
            "kind": {
              "$ref": "#/$defs/LeaseOwnerKind"
            },
            "run": {
              "$ref": "#/$defs/RunId"
            }
          },
          "required": [
            "kind"
          ],
          "type": "object"
        },
        "event": {
          "const": "input.recovered"
        },
        "from_run": {
          "$ref": "#/$defs/RunId"
        },
        "inputs": {
          "items": {
            "$ref": "#/$defs/InputRef"
          },
          "type": "array"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "by",
        "event",
        "from_run",
        "inputs",
        "run",
        "seq",
        "t"
      ],
      "title": "InputRecoveredEvent",
      "type": "object"
    },
    "InputRecovery": {
      "description": "눌렸을 수 있는 키 복구 결과: 복구함, 다른 쪽이 이미 복구함(복구 표시 파일), 복구할 키 없음, 임대권을 얻지 못함, 복구 수단 없음",
      "enum": [
        "already_recovered",
        "lease_busy",
        "not_needed",
        "recovered",
        "unavailable"
      ],
      "title": "InputRecovery",
      "type": "string"
    },
    "InputRef": {
      "additionalProperties": false,
      "description": "키보드 키 또는 마우스 버튼",
      "else": {
        "not": {
          "required": [
            "key"
          ]
        },
        "required": [
          "button"
        ]
      },
      "if": {
        "properties": {
          "device": {
            "const": "keyboard"
          }
        }
      },
      "properties": {
        "button": {
          "minLength": 1,
          "type": "string"
        },
        "device": {
          "enum": [
            "keyboard",
            "mouse"
          ]
        },
        "key": {
          "minLength": 1,
          "type": "string"
        }
      },
      "required": [
        "device"
      ],
      "then": {
        "not": {
          "required": [
            "button"
          ]
        },
        "required": [
          "key"
        ]
      },
      "title": "InputRef",
      "type": "object"
    },
    "InputUpEvent": {
      "additionalProperties": false,
      "description": "입력 액터가 백엔드에 떼기를 보낸 뒤에 쓴다",
      "else": {
        "not": {
          "required": [
            "key"
          ]
        },
        "required": [
          "button"
        ]
      },
      "if": {
        "properties": {
          "device": {
            "const": "keyboard"
          }
        }
      },
      "properties": {
        "button": {
          "minLength": 1,
          "type": "string"
        },
        "device": {
          "enum": [
            "keyboard",
            "mouse"
          ]
        },
        "event": {
          "const": "input.up"
        },
        "key": {
          "minLength": 1,
          "type": "string"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "device",
        "event",
        "run",
        "seq",
        "t"
      ],
      "then": {
        "not": {
          "required": [
            "button"
          ]
        },
        "required": [
          "key"
        ]
      },
      "title": "InputUpEvent",
      "type": "object"
    },
    "LeaseOwnerKind": {
      "description": "입력 임대권 소유자 종류: 실행(runner), 감독자 복구(supervisor), 녹화 세션을 연 daemon(recorder, M4)",
      "enum": [
        "recorder",
        "runner",
        "supervisor"
      ],
      "title": "LeaseOwnerKind",
      "type": "string"
    },
    "LogEvent": {
      "additionalProperties": false,
      "description": "노드·runner 로그",
      "properties": {
        "event": {
          "const": "log"
        },
        "level": {
          "enum": [
            "debug",
            "error",
            "info",
            "warn"
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
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "secret_paths": {
          "$ref": "#/$defs/SecretPaths"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "step": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ]
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "level",
        "message",
        "node",
        "run",
        "seq",
        "step",
        "t"
      ],
      "title": "LogEvent",
      "type": "object"
    },
    "Omitted": {
      "additionalProperties": false,
      "description": "정책으로 남기지 않은 증거와 그 이유",
      "properties": {
        "kind": {
          "description": "증거 종류: screenshot(스크린샷·실패 증거), text(OCR 글자), thumbnail(스텝 썸네일, M3)",
          "enum": [
            "screenshot",
            "text",
            "thumbnail"
          ]
        },
        "name": {
          "type": "string"
        },
        "reason": {
          "description": "sensitive_target = sensitive target 영역에서 읽은 OCR 글자",
          "enum": [
            "capture_policy",
            "policy_off",
            "secret_input",
            "sensitive_target"
          ]
        },
        "source": {
          "description": "정책을 끈 곳",
          "type": "string"
        }
      },
      "required": [
        "kind",
        "reason"
      ],
      "title": "Omitted",
      "type": "object"
    },
    "ProcessInfo": {
      "additionalProperties": false,
      "properties": {
        "created": {
          "description": "프로세스 생성 시각 (Unix 기준 UTC 마이크로초). PID 재사용을 가린다",
          "minimum": 0,
          "type": "integer"
        },
        "pid": {
          "minimum": 0,
          "type": "integer"
        },
        "version": {
          "type": "string"
        }
      },
      "required": [
        "created",
        "pid",
        "version"
      ],
      "title": "ProcessInfo",
      "type": "object"
    },
    "ResumeMode": {
      "description": "재개 방식: continue 다음 브레이크포인트·일시정지 요청까지, step_over 호출 깊이가 같거나 얕은 다음 경계, step_into 다음 경계, step_out 더 얕은 다음 경계",
      "enum": [
        "continue",
        "step_into",
        "step_out",
        "step_over"
      ],
      "title": "ResumeMode",
      "type": "string"
    },
    "RunEndEvent": {
      "additionalProperties": false,
      "description": "실행 결과. runner가 쓰거나, runner가 죽으면 감독자가 쓴다 (runner_died). active_duration_ms·paused_ms·debug_intervened·omitted는 M3부터",
      "properties": {
        "active_duration_ms": {
          "description": "멈춘 시간을 뺀 경과 (duration_ms는 실제 경과)",
          "minimum": 0,
          "type": "integer"
        },
        "cancel_reason": {
          "$ref": "#/$defs/CancelReason"
        },
        "code": {
          "type": "string"
        },
        "debug_intervened": {
          "description": "디버거로 한 번이라도 멈췄다 (브레이크포인트 적중·일시정지 모두)",
          "type": "boolean"
        },
        "duration_ms": {
          "minimum": 0,
          "type": [
            "integer",
            "null"
          ]
        },
        "event": {
          "const": "run.end"
        },
        "failure_path": {
          "anyOf": [
            {
              "$ref": "#/$defs/CallPath"
            },
            {
              "type": "null"
            }
          ]
        },
        "failure_step": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ]
        },
        "finalized_by": {
          "$ref": "#/$defs/FinalizedBy"
        },
        "input_recovery": {
          "$ref": "#/$defs/InputRecovery"
        },
        "omitted": {
          "description": "실행 단위로 남기지 않은 기록",
          "items": {
            "$ref": "#/$defs/RunOmitted"
          },
          "minItems": 1,
          "type": "array"
        },
        "paused_ms": {
          "description": "멈춰 있던 시간 합",
          "minimum": 0,
          "type": "integer"
        },
        "reason": {
          "type": "string"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "runner_exit_code": {
          "type": "integer"
        },
        "secret_paths": {
          "$ref": "#/$defs/SecretPaths"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        },
        "truncated_bytes": {
          "description": "감독자가 마무리 전에 잘라 낸 저널 끝 바이트 수",
          "minimum": 0,
          "type": "integer"
        },
        "verdict": {
          "$ref": "#/$defs/Verdict"
        }
      },
      "required": [
        "code",
        "duration_ms",
        "event",
        "failure_path",
        "failure_step",
        "finalized_by",
        "reason",
        "run",
        "seq",
        "t",
        "verdict"
      ],
      "title": "RunEndEvent",
      "type": "object"
    },
    "RunId": {
      "description": "실행 ID: 소문자·숫자 8자",
      "pattern": "^[a-z0-9]{8}$",
      "title": "RunId",
      "type": "string"
    },
    "RunOmitted": {
      "additionalProperties": false,
      "description": "실행 단위로 남기지 않은 기록 (스텝 Omitted와 같은 모양). video/encoder_stuck: 녹화 스레드가 기다림 상한(3초, 마무리 유예가 짧으면 유예에서 기록 여유를 뺀 시간) 안에 끝나지 않아 runner가 영상 파일을 건드리지 않고 포기했다 — runner 종료를 확인한 감독자가 video/를 지운다",
      "properties": {
        "kind": {
          "enum": [
            "video"
          ]
        },
        "reason": {
          "enum": [
            "encoder_stuck"
          ]
        }
      },
      "required": [
        "kind",
        "reason"
      ],
      "title": "RunOmitted",
      "type": "object"
    },
    "RunStartEvent": {
      "additionalProperties": false,
      "description": "실행 시작. runner가 저널의 첫 줄로 쓴다",
      "properties": {
        "event": {
          "const": "run.start"
        },
        "graph": {
          "description": "실행한 테스트 그래프 (워크스페이스 기준)",
          "type": "string"
        },
        "protocol": {
          "minimum": 1,
          "type": "integer"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "runner": {
          "$ref": "#/$defs/ProcessInfo"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "graph",
        "protocol",
        "run",
        "runner",
        "seq",
        "t"
      ],
      "title": "RunStartEvent",
      "type": "object"
    },
    "SecretPaths": {
      "description": "이 이벤트 안에서 비밀값(Secret·SecretMessage)을 담았던 필드의 JSON pointer (이벤트 기준). record.redact_secrets가 꺼진 실행이면 그 자리에 원문이 있다 — daemon이 에이전트에게 줄 때 ***로 바꾼다 (M5 3.8)",
      "items": {
        "type": "string"
      },
      "minItems": 1,
      "title": "SecretPaths",
      "type": "array"
    },
    "Seq": {
      "description": "저널 안 순번. 1부터 빈틈 없이",
      "minimum": 1,
      "title": "Seq",
      "type": "integer"
    },
    "StepEndEvent": {
      "additionalProperties": false,
      "description": "스텝 결과. 이 줄이 없는 스텝은 중단된 것이다. active_duration_ms·evidence는 M3부터",
      "properties": {
        "active_duration_ms": {
          "description": "멈춘 시간을 뺀 경과. 그 스텝 구간에 멈춤이 있었을 때만 쓴다 (duration_ms는 실제 경과)",
          "minimum": 0,
          "type": "integer"
        },
        "agent_withhold": {
          "description": "record.redact_secrets가 켜져 있었다면 남기지 않았을 증거(스크린샷·썸네일·OCR 글자·비밀값이 든 텍스트 artifact)의 실행 폴더 기준 경로. 파일은 그대로 남고 에이전트에게만 주지 않는다 (M5 3.8)",
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "artifacts": {
          "items": {
            "type": "string"
          },
          "type": "array"
        },
        "attempt": {
          "minimum": 1,
          "type": "integer"
        },
        "duration_ms": {
          "minimum": 0,
          "type": "integer"
        },
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
            "code",
            "message"
          ],
          "type": "object"
        },
        "event": {
          "const": "step.end"
        },
        "evidence": {
          "$ref": "#/$defs/StepEvidence"
        },
        "exit": {
          "type": [
            "null",
            "string"
          ]
        },
        "graph": {
          "description": "서브그래프 호출이면 이번 실행에 쓴 스냅샷 파일",
          "type": "string"
        },
        "iteration": {
          "description": "반복 안 스텝의 회차 (0부터)",
          "minimum": 0,
          "type": "integer"
        },
        "message": {
          "type": "string"
        },
        "omitted": {
          "items": {
            "$ref": "#/$defs/Omitted"
          },
          "type": "array"
        },
        "outputs": {
          "type": "object"
        },
        "retried": {
          "const": true
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "secret": {
          "const": true,
          "description": "입력이나 출력에 비밀값이 있던 스텝 ($secret·$link·변수·호출 인자 모두, 값 형식으로 판정). 에이전트에게는 이 스텝과 안쪽 스텝의 이미지·OCR 글자를 주지 않는다 (M5 3.8)"
        },
        "secret_paths": {
          "$ref": "#/$defs/SecretPaths"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "status": {
          "enum": [
            "cancelled",
            "error",
            "fail",
            "success"
          ]
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "attempt",
        "duration_ms",
        "event",
        "exit",
        "outputs",
        "run",
        "seq",
        "status",
        "step",
        "t"
      ],
      "title": "StepEndEvent",
      "type": "object"
    },
    "StepEvidence": {
      "additionalProperties": false,
      "description": "fail·error·stale_observation으로 끝난 스텝의 증거 (스키마 v0 6장). 파일은 artifacts에도 있다. 시각(*_at_ms)은 스텝 시작 기준 벽시계 ms. mid는 표본 중 (시작 + 끝)/2에 가장 가까운 캡처이고 최선 노력이다: 편차가 경과의 1/4을 넘거나 첫·마지막 말고 표본이 없으면 null과 mid_missing. 매칭 후보(target·threshold·candidates)는 찾기·대기 노드가 fail 출구로 끝났을 때 그 스텝이 마지막으로 찾은 캡처의 서로 다른 자리 점수 상위 3개(그 캡처에서 여러 target을 찾았으면 최고점이 가장 높은 target)",
      "else": {
        "if": {
          "required": [
            "mid"
          ]
        },
        "not": {
          "required": [
            "mid_missing"
          ]
        },
        "then": {
          "required": [
            "mid_at_ms",
            "mid_offset_ms"
          ]
        }
      },
      "if": {
        "properties": {
          "mid": {
            "type": "null"
          }
        },
        "required": [
          "mid"
        ]
      },
      "properties": {
        "candidates": {
          "items": {
            "$ref": "#/$defs/EvidenceCandidate"
          },
          "maxItems": 3,
          "type": "array"
        },
        "first": {
          "description": "그 스텝의 첫 캡처 (steps/<스텝>_first.png)",
          "type": "string"
        },
        "first_at_ms": {
          "minimum": 0,
          "type": "integer"
        },
        "last": {
          "description": "그 스텝의 마지막 캡처 (steps/<스텝>_fail.png 또는 _error.png)",
          "type": "string"
        },
        "last_at_ms": {
          "minimum": 0,
          "type": "integer"
        },
        "mid": {
          "description": "중간 캡처 (steps/<스텝>_mid.png), 없으면 null",
          "type": [
            "null",
            "string"
          ]
        },
        "mid_at_ms": {
          "description": "고른 중간 캡처의 실제 캡처 시각",
          "minimum": 0,
          "type": "integer"
        },
        "mid_missing": {
          "description": "중간 장면이 없는 이유",
          "enum": [
            "no_sample_near_mid"
          ]
        },
        "mid_offset_ms": {
          "description": "고른 캡처와 (시작 + 끝)/2의 차이 (절댓값)",
          "minimum": 0,
          "type": "integer"
        },
        "target": {
          "description": "마지막으로 찾은 target (스냅샷 안 워크스페이스 기준 경로)",
          "type": "string"
        },
        "threshold": {
          "maximum": 1,
          "minimum": 0,
          "type": "number"
        }
      },
      "then": {
        "not": {
          "anyOf": [
            {
              "required": [
                "mid_at_ms"
              ]
            },
            {
              "required": [
                "mid_offset_ms"
              ]
            }
          ]
        },
        "required": [
          "mid_missing"
        ]
      },
      "title": "StepEvidence",
      "type": "object"
    },
    "StepId": {
      "pattern": "^s[1-9][0-9]*$",
      "title": "StepId",
      "type": "string"
    },
    "StepStartEvent": {
      "additionalProperties": false,
      "description": "스텝 시작. 재시도해도 스텝 하나에 한 번",
      "properties": {
        "attempt": {
          "minimum": 1,
          "type": "integer"
        },
        "event": {
          "const": "step.start"
        },
        "iteration": {
          "description": "반복 안 스텝의 회차 (0부터)",
          "minimum": 0,
          "type": "integer"
        },
        "node": {
          "type": "string"
        },
        "parent": {
          "anyOf": [
            {
              "$ref": "#/$defs/StepId"
            },
            {
              "type": "null"
            }
          ]
        },
        "path": {
          "$ref": "#/$defs/CallPath"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "step": {
          "$ref": "#/$defs/StepId"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "attempt",
        "event",
        "node",
        "parent",
        "path",
        "run",
        "seq",
        "step",
        "t"
      ],
      "title": "StepStartEvent",
      "type": "object"
    },
    "Timestamp": {
      "description": "UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)",
      "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$",
      "title": "Timestamp",
      "type": "string"
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
    "WorkerExitEvent": {
      "additionalProperties": false,
      "description": "워커 프로세스 종료",
      "properties": {
        "event": {
          "const": "worker.exit"
        },
        "exit_code": {
          "type": "integer"
        },
        "pid": {
          "minimum": 0,
          "type": "integer"
        },
        "reason": {
          "description": "shutdown: 마무리에서 정상 종료, killed_after_grace: 취소·shutdown 유예를 넘겨 끝냄, unexpected: 스스로 죽음(실행 중 kill·크래시, hello 전 종료 포함), start_timeout: hello 기한 초과로 끝냄, start_failed: hello 실패(import 오류·프로토콜 불일치)로 끝냄, cancelled: 시작 중 취소·전체 기한으로 끝냄",
          "enum": [
            "cancelled",
            "killed_after_grace",
            "shutdown",
            "start_failed",
            "start_timeout",
            "unexpected"
          ]
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "pid",
        "run",
        "seq",
        "t"
      ],
      "title": "WorkerExitEvent",
      "type": "object"
    },
    "WorkerStartEvent": {
      "additionalProperties": false,
      "description": "워커 프로세스 시작",
      "properties": {
        "event": {
          "const": "worker.start"
        },
        "pid": {
          "minimum": 0,
          "type": "integer"
        },
        "run": {
          "$ref": "#/$defs/RunId"
        },
        "seq": {
          "$ref": "#/$defs/Seq"
        },
        "t": {
          "$ref": "#/$defs/Timestamp"
        }
      },
      "required": [
        "event",
        "pid",
        "run",
        "seq",
        "t"
      ],
      "title": "WorkerStartEvent",
      "type": "object"
    }
  },
  "$id": "urn:kookabug:events:0",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "description": "events.jsonl 한 줄 (실행 이벤트 하나). event 값으로 종류를 고른다",
  "oneOf": [
    {
      "$ref": "#/$defs/RunStartEvent"
    },
    {
      "$ref": "#/$defs/StepStartEvent"
    },
    {
      "$ref": "#/$defs/AttemptEndEvent"
    },
    {
      "$ref": "#/$defs/StepEndEvent"
    },
    {
      "$ref": "#/$defs/LogEvent"
    },
    {
      "$ref": "#/$defs/InputDownEvent"
    },
    {
      "$ref": "#/$defs/InputUpEvent"
    },
    {
      "$ref": "#/$defs/InputRecoveredEvent"
    },
    {
      "$ref": "#/$defs/CancelRequestedEvent"
    },
    {
      "$ref": "#/$defs/ControlLostEvent"
    },
    {
      "$ref": "#/$defs/DebugPauseEvent"
    },
    {
      "$ref": "#/$defs/DebugResumeEvent"
    },
    {
      "$ref": "#/$defs/WorkerStartEvent"
    },
    {
      "$ref": "#/$defs/WorkerExitEvent"
    },
    {
      "$ref": "#/$defs/RunEndEvent"
    }
  ],
  "title": "Event"
};
