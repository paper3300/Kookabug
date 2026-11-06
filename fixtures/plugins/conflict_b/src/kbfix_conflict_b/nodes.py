"""충돌 검사 픽스처 B: kbfix-dep 2 이상 (A와 공유 환경에 함께 둘 수 없다)."""

from kookabug_sdk import Context, node


@node(
    type="conflict_b.dep.version",
    version=1,
    title="의존성 판",
    pure=True,
    outputs={"version": str},
)
def dep_version(ctx: Context) -> dict[str, str]:
    import kbfix_dep  # pyright: ignore[reportMissingImports]  # 플러그인 환경에만 있다

    return {"version": str(kbfix_dep.__version__)}  # pyright: ignore[reportUnknownMemberType]
