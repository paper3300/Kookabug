"""충돌 검사 픽스처 A: kbfix-dep 1.x."""

from kookabug_sdk import Context, node


@node(
    type="conflict_a.dep.version",
    version=1,
    title="의존성 판",
    pure=True,
    outputs={"version": str},
)
def dep_version(ctx: Context) -> dict[str, str]:
    import kbfix_dep  # pyright: ignore[reportMissingImports]  # 플러그인 환경에만 있다

    return {"version": str(kbfix_dep.__version__)}  # pyright: ignore[reportUnknownMemberType]
