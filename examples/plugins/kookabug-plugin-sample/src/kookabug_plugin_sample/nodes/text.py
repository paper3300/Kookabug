"""글자 노드."""

from kookabug_sdk import Context, node


@node(
    type="sample.text.reverse",
    version=1,
    title="글자 뒤집기",
    category="sample",
    pure=True,
    outputs={"text": str},
)
def reverse(ctx: Context, text: str) -> dict[str, str]:
    """글자를 거꾸로 늘어놓는다."""
    return {"text": text[::-1]}
