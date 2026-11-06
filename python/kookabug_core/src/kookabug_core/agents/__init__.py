"""에이전트 연결 (M5): 판단 노드가 쓰는 ACP 클라이언트·모델 API 호출·지시문과 답 읽기.

- `acp`: 에이전트 CLI를 도구 없이 띄워 한 번 묻는다 (`core.agent.cli_judge`)
- `model_api`: 모델 API를 HTTP로 직접 부른다 (`core.agent.api_judge`)
- `judge`: 두 노드의 공용 흐름 — 지시문, 답 읽기, 사용자 설정의 에이전트 목록, 기록
"""
