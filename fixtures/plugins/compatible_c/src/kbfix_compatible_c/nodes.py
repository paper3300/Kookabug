"""공유 환경에 붙는 픽스처 C: kbfix-dep 1~2 (공유의 1.x 고정에 맞춘다)."""

from kookabug_sdk import Context, node


@node(
    type="compatible_c.dep.version",
    version=1,
    title="의존성 판",
    pure=True,
    outputs={"version": str},
)
def dep_version(ctx: Context) -> dict[str, str]:
    import kbfix_dep  # pyright: ignore[reportMissingImports]  # 플러그인 환경에만 있다

    return {"version": str(kbfix_dep.__version__)}  # pyright: ignore[reportUnknownMemberType]
