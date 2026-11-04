"""녹화 계약의 순수 코드 (M4 계획 2.1·2.9): 훅 스트림 연속성 검사, 관측 짝짓기, 커밋 조각 검사.

훅 프로세스 검사(T3)·daemon 녹화 세션(T8)·변환기(T5·T6)가 같은 규칙을 쓰도록 한 곳에 둔다.
메시지 모양은 `recorder-hook`·`recorder-script`·`recorder-fragment` 메타스키마가 단일 출처다.
"""
