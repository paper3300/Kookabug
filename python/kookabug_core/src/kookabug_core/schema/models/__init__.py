"""메타스키마에서 생성한 pydantic v2 모델 (tools/gen_schema.py). 직접 고치지 않는다.

형식 검사는 `kookabug_core.schema.check_shape`가 한다. 모델은 검사를 통과한 값을 타입 있게
읽을 때 쓴다. 저장은 원래 dict를 `canonical_dumps`로 쓴다 (모델은 숫자를 float로 바꿀 수 있다).
"""
