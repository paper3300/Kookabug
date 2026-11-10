"""자동 채택 조건 2·3의 순수 함수 (M8 계획 3.8·E6·C4) — 엄격: 채택 조건 우회.

- **조건 2** `candidate_problem`: 변경 파일이 `*.target.json` 하나와 그 `image` PNG뿐(그래프·다른
  파일 diff 0). target diff의 바뀐 필드는 `image`·`search.region`(새 넓이 ≤ 원래 넓이, 원래 없으면
  새로도 없음, 지우기 금지)·`click.anchor/offset`·`recorded`뿐. `match.*`는 `threshold_changed`,
  `sensitive`·그 밖 필드는 `not_locator_only`, region 넓히기·지우기·더하기는 `search_widened`. 그
  target을 쓰는 곳(팀의 tests·subgraphs·screens detect 전부)이 조작 노드 허용 목록
  (`core.image.click`의 `target` 핀) 밖에 없어야 한다(`target_used_for_judgment`). 바꾸는 PNG를
  다른 target이 쓰면 그
  target의 판정이 함께 바뀌므로 거부한다(R1 폐포 — `shared_image`)
- **조건 3** `oracle_problem`: 사건의 원래 그래프 sha·주장 rev와 지금 팀이 같고, 판정 의존성(판정
  노드가 읽는 target·PNG·그 노드가 든 서브그래프)의 sha와 판정 입력이 해석하는 팀 설정 값이 원래
  실패 실행 때와 같아야 한다. 판정 입력의 출처를 끝까지 따라갈 수 없으면(`$secret`, `$link`가
  추적 가능 생산자 허용 목록 `TRACEABLE_PRODUCERS` 밖 노드로 이어짐) 자동 채택하지 않는다
  (`judgment_inputs`)
- 조건 2의 판정 사용은 원래 테스트 폐포만이 아니라 팀의 모든 tests·subgraphs 그래프에서 같은
  `$link` 추적으로 본다(`judged_use_problem`)

경로는 모두 `path_key`(구분자·`casefold`)로 비교한다 — Windows에서 철자만 다른 두 키는 같은
파일이다.
값을 읽지 않고 sha·필드 이름만 다룬다. 파일 읽기·실행은 daemon(`kookabug_daemon.adopt`)이 한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Final, cast

__all__ = [
    "CONTROL_NODES",
    "OPERATION_PINS",
    "TARGET_VALUE_SINKS",
    "TRACEABLE_PRODUCERS",
    "Judgment",
    "Problem",
    "Use",
    "candidate_problem",
    "changed_fields",
    "has_suffix",
    "image_rel",
    "is_graph",
    "is_png",
    "is_target",
    "judged_use_problem",
    "judgment_dependencies",
    "judgment_inputs",
    "oracle_problem",
    "path_key",
    "reaching_graphs",
    "target_flow_problem",
    "target_uses",
    "usage_problem",
]

TARGET_SUFFIX: Final = ".target.json"
GRAPH_SUFFIX: Final = ".graph.json"
PNG_SUFFIX: Final = ".png"
OPERATION_PINS: Final = frozenset({("core.image.click", "target")})
"""조작 전용으로 세는 (노드 타입, 핀). 여기 밖에서 쓰이는 target은 판정에 쓰인다고 본다."""
TRACEABLE_PRODUCERS: Final[Mapping[str, str]] = {
    # 순수: 출력이 노드의 `in`(과 그래프에 적힌 상수)만으로 정해진다 — `ctx`를 읽지 않는다
    "core.logic.compare": "pure",
    "core.math.calc": "pure",
    "core.text.format": "pure",
    # target 출처: 출력(`match`)이 `in`의 `$target`으로 찾은 위치다. 그 target·PNG를 판정 의존성으로
    # 잡는다 (변수·설정·OCR·외부를 읽지 않고 `ctx.vision.find`만)
    "core.image.click": "target",
    "core.image.wait": "target",
    "core.image.wait_any": "target",
    "core.assert.visible": "target",
}
"""판정 입력이 `$link`로 이어질 때 출처를 이 그래프 안에서 끝까지 따라갈 수 있는 생산자 (허용 목록).
여기 밖(변수 `core.var.*` 전부·그래프 경계 `core.graph.entry/call`·반복 index·OCR·화면 캡처·Agent·
플러그인·없는 노드)에 닿으면 판정 의존성을 추적할 수 없다(`oracle_untraceable`). 목록 노드가
`ctx.vars`·설정·외부를 읽지 않는다는 근거는 `test_adopt_rules`의 허용 목록 검사."""
CONTROL_NODES: Final = frozenset({"core.flow.branch", "core.flow.while"})
"""값으로 다음 길(예: `core.test.fail`)을 고르는 노드. 조건 2 팀 스캔에서 이 노드 입력이 `$link`로
후보 target을 거쳐 오면 판정 사용으로 본다 (판정 노드 입력과 같게)."""
TARGET_VALUE_SINKS: Final = frozenset(
    {("core.input.click", "match"), ("core.input.drag", "start"), ("core.input.drag", "end")}
)
"""후보 target에서 나온 값(그 target을 읽는 노드의 출력, 예: `match`)이 흘러가도 되는 (노드 타입,
핀) — 입력 장치로 보내는 조작 핀뿐 (허용 목록). 그 밖(변수 저장 `core.var.*`, 판정·비교·계산·문자열
조합, 흐름 분기·반복 조건, `core.graph.exit`·`core.graph.call` 경계, 플러그인·목록 밖 노드)으로
흘러가면 조건 2 `target_used_for_judgment`."""
_LOCATOR_FIELDS: Final = ("image", "click/anchor", "click/offset")
_MISSING: Final = object()
_EPS: Final = 1e-9


@dataclass(frozen=True, slots=True)
class Problem:
    condition: int
    code: str
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"condition": self.condition, "code": self.code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class Use:
    """target 참조 하나: 파일·JSON 위치·(그래프면) 노드와 그 타입·핀."""

    file: str
    pointer: str
    node: str | None
    type: str | None
    pin: str | None

    @property
    def operation_only(self) -> bool:
        return (self.type, self.pin) in OPERATION_PINS


def path_key(rel: str) -> str:
    """경로 비교 키 (구분자 `/`·빈 조각 제거·`casefold`). 후보·target·image·폐포 키를 모두 이것으로
    비교한다 — Windows에서 철자만 다른 두 경로는 같은 파일이다."""
    return "/".join(p for p in rel.replace("\\", "/").split("/") if p).casefold()


_key = path_key


def has_suffix(rel: str, suffix: str) -> bool:
    """파일 종류(확장자) 판별은 모두 이것으로 한다 — `path_key` 정규화 위에서 비교하므로
    `a.GRAPH.json`·`a.graph.JSON`도 그래프다(Windows에서 같은 종류의 파일)."""
    return path_key(rel).endswith(suffix.casefold())


def is_graph(rel: str) -> bool:
    return has_suffix(rel, GRAPH_SUFFIX)


def is_target(rel: str) -> bool:
    return has_suffix(rel, TARGET_SUFFIX)


def is_png(rel: str) -> bool:
    return has_suffix(rel, PNG_SUFFIX)


def image_rel(target_rel: str, value: Any) -> str | None:
    """target의 `image`(target 폴더 기준) → 워크스페이스 기준 경로. 형식이 틀리면 None."""
    image = value.get("image") if isinstance(value, Mapping) else None
    if not isinstance(image, str) or not image or "\\" in image or image.startswith("/"):
        return None
    parts = [*PurePosixPath(target_rel).parent.parts, *image.split("/")]
    if any(p in ("", ".", "..") for p in parts):
        return None
    return "/".join(parts)


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, Mapping) and value:
        out: dict[str, Any] = {}
        for k, v in cast(Mapping[str, Any], value).items():
            out.update(_flatten(v, f"{prefix}/{k}" if prefix else str(k)))
        return out
    return {prefix: json.dumps(value, sort_keys=True)}


def changed_fields(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[str]:
    """두 target 값의 바뀐 잎 필드 (`a/b` 꼴, 배열은 통째로 한 잎)."""
    fb, fa = _flatten(before), _flatten(after)
    return sorted(k for k in fb.keys() | fa.keys() if fb.get(k, _MISSING) != fa.get(k, _MISSING))


def _region(value: Mapping[str, Any]) -> list[float] | None:
    search = value.get("search")
    region = search.get("region") if isinstance(search, Mapping) else None
    if region is None:
        return None
    return [float(v) for v in cast(Sequence[Any], region)]


def _region_problem(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    frame_sizes: Sequence[Any] = (),
) -> Problem | None:
    rb, ra = _region(before), _region(after)
    if rb is None and ra is None:
        return None
    if rb is None:
        return Problem(2, "search_widened", "원래 검색 범위가 없던 target에 범위를 더하지 않는다")
    if ra is None:
        return Problem(2, "search_widened", "검색 범위를 지우면 화면 전체로 넓어진다")
    known = [_size(before.get("recorded")), _size(after.get("recorded"))]
    known += [_size({"client_size": s}) for s in frame_sizes]
    sizes = sorted({s for s in known if s is not None})
    if sizes:
        # 알려진 모든 프레임 크기(팀·후보 녹화 크기, 서비스가 아는 현재 크기)에서 두 범위를
        # 실행기와 같은 변환으로 픽셀 사각형으로 맞춰 넓이를 비교한다. 저장 자릿수 차이
        # (0.2539 ↔ 0.253907)는 넓힘이 아니고, 한 크기에서라도 1px 넓으면 거부한다
        from kookabug_platform.dpi import normalized_to_pixels

        for size in sizes:
            pb = normalized_to_pixels((rb[0], rb[1], rb[2], rb[3]), size)
            pa = normalized_to_pixels((ra[0], ra[1], ra[2], ra[3]), size)
            if pa[2] * pa[3] > pb[2] * pb[3]:
                return Problem(
                    2,
                    "search_widened",
                    f"새 검색 범위가 원래보다 넓다 ({size[0]}x{size[1]}에서 "
                    f"{pa[2]}x{pa[3]} > {pb[2]}x{pb[3]})",
                )
        return None
    if ra[2] * ra[3] > rb[2] * rb[3] + _EPS:
        return Problem(2, "search_widened", "새 검색 범위가 원래보다 넓다")
    return None


def _size(recorded: Any) -> tuple[int, int] | None:
    """`{"client_size": [w, h]}`의 크기 (없거나 틀리면 None)."""
    size = recorded.get("client_size") if isinstance(recorded, Mapping) else None
    if not isinstance(size, list | tuple):
        return None
    parts = cast(Sequence[Any], size)
    if len(parts) != 2 or not all(isinstance(v, int) and v > 0 for v in parts):
        return None
    return int(parts[0]), int(parts[1])


def _field_problem(fields: Sequence[str]) -> Problem | None:
    for name in fields:
        top = name.split("/", 1)[0]
        if top == "match":
            return Problem(2, "threshold_changed", f"매칭 기준 '{name}'을(를) 바꾸지 않는다")
        if name == "search/region" or name.startswith("search/region"):
            continue
        if name in _LOCATOR_FIELDS or top == "recorded":
            continue
        return Problem(2, "not_locator_only", f"'{name}'은(는) 위치 수리 허용 필드가 아니다")
    return None


def target_uses(files: Mapping[str, Any], target_rel: str) -> list[Use]:
    """팀 파일들(경로 → JSON 값: 그래프·화면 등)에서 `{"$target": target_rel}` 참조를 모두
    찾는다."""
    want = _key(target_rel)
    found: list[Use] = []
    for rel, value in sorted(files.items()):
        nodes = value.get("nodes") if isinstance(value, Mapping) else None
        for pointer, holder in _refs(value, ""):
            if _key(str(holder)) != want:
                continue
            parts = pointer.strip("/").split("/")
            node = typ = pin = None
            if (
                isinstance(nodes, Mapping)
                and len(parts) == 4
                and parts[0] == "nodes"
                and parts[2] == "in"
            ):
                node, pin = parts[1], parts[3]
                spec = cast(Mapping[str, Any], nodes).get(node)
                typ = spec.get("type") if isinstance(spec, Mapping) else None
            found.append(Use(rel, pointer, node, typ if isinstance(typ, str) else None, pin))
    return found


def _refs(value: Any, pointer: str) -> Iterator[tuple[str, Any]]:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, Any], value)
        if set(mapping) == {"$target"}:
            yield pointer, mapping["$target"]
            return
        for k, v in mapping.items():
            yield from _refs(v, f"{pointer}/{k}")
    elif isinstance(value, list):
        for i, v in enumerate(cast(list[Any], value)):
            yield from _refs(v, f"{pointer}/{i}")


def usage_problem(uses: Sequence[Use]) -> Problem | None:
    for use in uses:
        if not use.operation_only:
            where = f"{use.file}#{use.pointer}"
            return Problem(
                2,
                "target_used_for_judgment",
                f"이 target을 조작 밖(판정·화면 조건)에서 쓴다: {where}",
            )
    return None


def candidate_problem(
    changed: Mapping[str, tuple[bytes | None, bytes]],
    *,
    team_files: Mapping[str, Any],
    team_targets: Mapping[str, Any],
    frame_sizes: Sequence[Any] = (),
) -> Problem | None:
    """조건 2. `changed` = 경로 → (팀 바이트 또는 None, 후보 바이트). `team_files` = 참조를 찾을 팀
    JSON(tests·subgraphs·screens), `team_targets` = 팀 target 전부(경로 → 값, 공유 PNG 찾기).
    `frame_sizes` = 서비스가 아는 현재 프레임 크기들(`[w, h]`, 넓힘 비교에 더한다)."""
    if len({_key(rel) for rel in changed}) != len(changed):
        return Problem(2, "path_alias", "같은 파일을 가리키는 후보 경로가 둘 이상이다")
    targets = [rel for rel in changed if is_target(rel)]
    if len(targets) != 1:
        return Problem(2, "not_locator_only", "변경은 target 파일 하나(와 그 PNG)여야 한다")
    target = targets[0]
    before_raw, after_raw = changed[target]
    if before_raw is None:
        return Problem(2, "not_locator_only", "새 target은 자동 채택하지 않는다 (제자리 수리만)")
    try:
        before = json.loads(before_raw.decode("utf-8"))
        after = json.loads(after_raw.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return Problem(2, "not_locator_only", "target 파일을 읽을 수 없다")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return Problem(2, "not_locator_only", "target 파일이 객체가 아니다")
    before_map = cast(dict[str, Any], before)
    after_map = cast(dict[str, Any], after)
    image = image_rel(target, after_map)
    for rel in changed:
        if _key(rel) == _key(target):
            continue
        if image is None or _key(rel) != _key(image) or not is_png(rel):
            return Problem(2, "not_locator_only", f"'{rel}'은(는) target 이미지가 아니다")
    problem = _field_problem(changed_fields(before_map, after_map)) or _region_problem(
        before_map, after_map, frame_sizes
    )
    if problem is not None:
        return problem
    problem = usage_problem(target_uses(team_files, target))
    if problem is not None:
        return problem
    if image is not None and _key(image) in {_key(rel) for rel in changed}:
        users = image_users(team_targets, target, image)
        if users:
            return Problem(
                2,
                "target_used_for_judgment",
                f"바꾸는 이미지를 다른 target({users[0]})도 쓴다 (shared_image)",
            )
    return None


def image_users(team_targets: Mapping[str, Any], target: str, image: str) -> list[str]:
    """`image`(워크스페이스 기준)를 쓰는 `target` 밖의 팀 target (정규화 키 비교)."""
    return sorted(
        other
        for other, value in team_targets.items()
        if _key(other) != _key(target) and _key(image_rel(other, value) or "") == _key(image)
    )


@dataclass(frozen=True, slots=True)
class Judgment:
    """판정 입력이 기대는 것: 파일(그래프·target·PNG), 해석하는 `$setting` 키, 추적할 수 없는
    까닭(있으면 자동 채택하지 않는다)."""

    files: frozenset[str]
    settings: frozenset[str]
    untraceable: str | None


def _specials(value: Any) -> Iterator[tuple[str, Any]]:
    """입력 값 안의 특수 값 `(태그, 내용)` (로더 `_resolve`와 같은 규칙, `$literal` 안은 안
    본다)."""
    if isinstance(value, list):
        for v in cast(list[Any], value):
            yield from _specials(v)
    elif isinstance(value, Mapping):
        mapping = cast(Mapping[str, Any], value)
        if len(mapping) == 1:
            ((key, inner),) = mapping.items()
            if isinstance(key, str) and key.startswith("$"):
                if key != "$literal":
                    yield key, inner
                return
        for v in mapping.values():
            yield from _specials(v)


def judgment_inputs(
    graphs: Mapping[str, Any],
    root: str,
    *,
    is_assertion: Callable[[str], bool],
    targets: Mapping[str, Any],
    is_known: Callable[[str], bool] = lambda _: True,
) -> Judgment:
    """판정 의존성 (조건 3): 루트 그래프와 그 서브그래프 폐포(`graphs`)의 판정 노드마다 입력의
    `$target`(그 PNG까지)·`$setting`, 그리고 `$link`로 이어진 같은 그래프 노드의 입력을 거슬러
    모은다. 판정 노드가 든 그래프와 루트 그래프는 늘 든다.

    추적할 수 없는 것: 판정 입력(또는 그 `$link` 출처)의 `$secret`, 출처가 `TRACEABLE_PRODUCERS`
    밖·코어 표에 없는 노드·없는 노드인 `$link`, 코어 표에 없는 판정 노드(`is_known` 거짓 — 무엇을
    읽는지 모른다)."""
    by_key = {_key(k): v for k, v in targets.items()}
    files: set[str] = {root}
    settings: set[str] = set()
    untraceable: str | None = None

    def note(why: str) -> None:
        nonlocal untraceable
        if untraceable is None:
            untraceable = why

    for rel, value in sorted(graphs.items()):
        nodes = value.get("nodes") if isinstance(value, Mapping) else None
        if not isinstance(nodes, Mapping):
            continue
        table = cast(Mapping[str, Any], nodes)
        for node_id, node in sorted(table.items()):
            if not isinstance(node, Mapping):
                continue
            typ = cast(Mapping[str, Any], node).get("type")
            if not isinstance(typ, str) or not is_assertion(typ):
                continue
            files.add(rel)
            if not is_known(typ):
                note(f"판정 노드 {rel}#{node_id}의 타입이 코어 표에 없어 읽는 것을 모른다")
            seen: set[str] = set()
            todo = [str(node_id)]
            while todo:
                current = todo.pop()
                if current in seen:
                    continue
                seen.add(current)
                spec = table.get(current)
                ctype = spec.get("type") if isinstance(spec, Mapping) else None
                if not isinstance(ctype, str):
                    note(f"판정 입력이 {rel}의 없는 노드에서 온다")
                    continue
                producer = current != str(node_id)
                if not is_known(ctype) or (producer and ctype not in TRACEABLE_PRODUCERS):
                    note(
                        f"판정 입력이 {rel}#{current}({ctype})를 거쳐 오는데, 그 출력의 출처를 "
                        "따라갈 수 없다 (추적 가능 생산자 목록 밖)"
                    )
                    continue
                for tag, inner in _specials(cast(Mapping[str, Any], spec).get("in") or {}):
                    if tag == "$target":
                        target = str(inner)
                        files.add(target)
                        image = image_rel(target, by_key.get(_key(target)))
                        if image is not None:
                            files.add(image)
                    elif tag == "$setting":
                        settings.add(str(inner))
                    elif tag == "$secret":
                        note(f"판정 입력이 비밀값을 읽는다 ({rel}#{current})")
                    elif tag == "$link":
                        todo.append(str(inner).split(".", 1)[0])
                    else:
                        note(f"판정 입력에 모르는 특수 값 {tag}이(가) 있다")
    return Judgment(frozenset(files), frozenset(settings), untraceable)


def _calls(value: Any) -> set[str]:
    """그래프가 부르는 서브그래프 (`core.graph.call`의 `config.graph`, 정규화 키)."""
    nodes = value.get("nodes") if isinstance(value, Mapping) else None
    out: set[str] = set()
    if not isinstance(nodes, Mapping):
        return out
    for node in cast(Mapping[str, Any], nodes).values():
        if not isinstance(node, Mapping):
            continue
        spec = cast(Mapping[str, Any], node)
        config = spec.get("config")
        graph = config.get("graph") if isinstance(config, Mapping) else None
        if spec.get("type") == "core.graph.call" and isinstance(graph, str):
            out.add(_key(graph))
    return out


def reaching_graphs(graphs: Mapping[str, Any], target: str) -> set[str]:
    """`target`을 쓰는 그래프 (정규화 키): 직접 `$target`으로 읽는 그래프, 그것을 (거슬러) 부르는
    그래프, 그리고 그 그래프들이 부르는 서브그래프 전부 — 값이 호출 출력(`graph.call`)·호출
    입력(`graph.entry`)으로 오가므로 양쪽을 다 넣는다."""
    calls = {_key(rel): _calls(value) for rel, value in graphs.items()}
    found = {_key(use.file) for use in target_uses(graphs, target)}
    changed = True
    while changed:  # 부르는 쪽으로
        changed = False
        for rel, callee in calls.items():
            if rel not in found and callee & found:
                found.add(rel)
                changed = True
    todo = list(found)
    while todo:  # 불리는 쪽으로
        for callee in calls.get(todo.pop(), set()):
            if callee not in found:
                found.add(callee)
                todo.append(callee)
    return found


def _link_pins(spec: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """노드 입력의 `(핀, $link 출처 노드)`."""
    inputs = spec.get("in")
    if not isinstance(inputs, Mapping):
        return
    for pin, value in cast(Mapping[str, Any], inputs).items():
        for tag, inner in _specials({"_": value}):
            if tag == "$link":
                yield str(pin), str(inner).split(".", 1)[0]


def target_flow_problem(graphs: Mapping[str, Any], target: str) -> Problem | None:
    """조건 2 흐름 방향 (팀 기준 전체): 그래프마다 `target`을 `$target`으로 읽는 노드의 출력이
    `$link`로 흘러가는 곳이 `TARGET_VALUE_SINKS` 안뿐이어야 한다. 변수에 저장하거나 비교·분기·경계로
    흘러가면(직접이든 순수 노드를 거치든 — 순수 노드도 목록 밖이다) `target_used_for_judgment`.
    그래프 경계를 넘는 값은 `core.graph.exit`·`core.graph.call` 입력에서 막히므로 그래프 안만
    본다."""
    want = _key(target)
    for rel, value in sorted(graphs.items()):
        nodes = value.get("nodes") if isinstance(value, Mapping) else None
        if not isinstance(nodes, Mapping):
            continue
        table = {
            str(k): cast(Mapping[str, Any], v)
            for k, v in cast(Mapping[str, Any], nodes).items()
            if isinstance(v, Mapping)
        }
        tainted = {
            nid
            for nid, spec in table.items()
            if any(
                tag == "$target" and _key(str(inner)) == want
                for tag, inner in _specials(spec.get("in") or {})
            )
        }
        todo = list(tainted)
        while todo:
            source = todo.pop()
            for nid, spec in sorted(table.items()):
                for pin, origin in _link_pins(spec):
                    if origin != source:
                        continue
                    typ = spec.get("type")
                    if (typ, pin) not in TARGET_VALUE_SINKS:
                        return Problem(
                            2,
                            "target_used_for_judgment",
                            f"{rel}#{nid}({typ}).{pin}이(가) 이 target에서 나온 값을 "
                            "조작 밖에서 쓴다",
                        )
                    if nid not in tainted:  # 조작 노드에 출력이 생겨도 그 흐름까지 본다
                        tainted.add(nid)
                        todo.append(nid)
    return None


def judged_use_problem(
    graphs: Mapping[str, Any],
    target: str,
    *,
    is_assertion: Callable[[str], bool],
    targets: Mapping[str, Any],
    is_known: Callable[[str], bool] = lambda _: True,
) -> Problem | None:
    """조건 2 (팀 기준 전체): 팀의 그래프(tests·subgraphs, 경로 → 값) 어디서든 판정 입력이
    `$link`로 `target`을 거쳐 오면 `target_used_for_judgment`. `target`을 쓰는 그래프
    (`reaching_graphs`)에 출처를 추적할 수 없는 판정 입력이 있으면 안전 쪽으로 같은 거부.
    `judgment_inputs`와 같은 추적이다 (요청 시작과 게시 직전 재확인이 함께 쓴다). 흐름 분기
    (`CONTROL_NODES`)의 조건 입력이 `$link`로 이 target을 거쳐 와도 판정 사용이다. 정방향으로는
    `target_flow_problem`(target 값이 조작 핀 밖으로 흘러가면 거부)을 함께 적용한다."""
    problem = target_flow_problem(graphs, target)
    if problem is not None:
        return problem
    want = _key(target)
    reach = reaching_graphs(graphs, target)
    for rel, value in sorted(graphs.items()):
        judged = judgment_inputs(
            {rel: value}, rel, is_assertion=is_assertion, targets=targets, is_known=is_known
        )
        control = judgment_inputs(
            {rel: value}, rel, is_assertion=CONTROL_NODES.__contains__, targets=targets
        )
        if want in {_key(f) for f in judged.files} | {_key(f) for f in control.files}:
            return Problem(
                2, "target_used_for_judgment", f"{rel}의 판정 입력이 $link로 이 target을 거쳐 온다"
            )
        if judged.untraceable is not None and _key(rel) in reach:
            return Problem(
                2,
                "target_used_for_judgment",
                f"이 target을 쓰는 {rel}의 판정 입력 출처를 따라갈 수 없다 ({judged.untraceable})",
            )
    return None


def judgment_dependencies(
    graphs: Mapping[str, Any],
    root: str,
    *,
    is_assertion: Callable[[str], bool],
    targets: Mapping[str, Any],
) -> set[str]:
    """판정 의존성 파일 (`judgment_inputs(...).files`)."""
    return set(judgment_inputs(graphs, root, is_assertion=is_assertion, targets=targets).files)


def team_setting(config: Mapping[str, Any] | None, key: str, profile: str | None) -> Any:
    """팀 `kookabug.json` 값으로 해석한 설정 (프로필 덮어쓰기 → 팀 설정, 로더와 같은 순서). 개인
    `local.json`은 보지 않는다(범위 밖). 없으면 `MISSING`, `config`가 None이면 `UNKNOWN`."""
    if config is None:
        return UNKNOWN
    if profile is not None:
        profiles = config.get("profiles")
        found = profiles.get(profile) if isinstance(profiles, Mapping) else None
        layer = found.get("settings") if isinstance(found, Mapping) else None
        if isinstance(layer, Mapping) and key in layer:
            return cast(Mapping[str, Any], layer)[key]
    settings = config.get("settings")
    if isinstance(settings, Mapping) and key in settings:
        return cast(Mapping[str, Any], settings)[key]
    return MISSING


MISSING: Final = object()
UNKNOWN: Final = object()


def oracle_problem(
    *,
    original_graph_sha: str | None,
    current_graph_sha: str | None,
    original_claims: Sequence[Mapping[str, Any]],
    current_claims: Mapping[str, int | None],
    original_deps: Mapping[str, str | None],
    current_deps: Mapping[str, str | None],
    original_settings: Mapping[str, Any] | None = None,
    current_settings: Mapping[str, Any] | None = None,
) -> Problem | None:
    """조건 3. 원래(사건 `original`·원래 실패 실행 스냅샷)와 지금 팀이 같아야 한다. 설정은 판정
    입력이 해석하는 팀 설정 값(`team_setting`) — 원래 쪽을 알 수 없으면(`UNKNOWN`) 같다고 보지
    않는다."""
    if original_graph_sha is None or original_graph_sha != current_graph_sha:
        return Problem(3, "oracle_changed", "테스트 그래프가 원래 실패 때와 다르다")
    for claim in original_claims:
        cid = str(claim.get("id"))
        if current_claims.get(cid) != claim.get("rev"):
            return Problem(3, "claims_changed", f"주장 {cid}의 rev가 원래 실패 때와 다르다")
    for rel in sorted(set(original_deps) | set(current_deps)):
        if original_deps.get(rel, "?") != current_deps.get(rel, "?"):
            return Problem(3, "oracle_changed", f"판정 의존성 '{rel}'이(가) 원래 실패 때와 다르다")
    before, after = original_settings or {}, current_settings or {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, UNKNOWN), after.get(key, UNKNOWN)
        if old is UNKNOWN or new is UNKNOWN or _canon(old) != _canon(new):
            return Problem(
                3, "oracle_changed", f"판정이 읽는 설정 '{key}'이(가) 원래 실패 때와 다르다"
            )
    return None


def _canon(value: Any) -> str:
    if value is MISSING:
        return "\0missing"
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


# ---------------------------------------------------------------- 게시 (조건 7·8·되돌리기·수락)
#
# 모두 `.kookabug/adopt.lock`(채택끼리 줄 세움) → `.kookabug/knowledge.lock`(`filetx.locked`) 순서로
# 잡고, 팀 파일·채택 기록·원래 바이트 증거 묶음·작업 변경 상태·사건·감사 이력을 `filetx` 한 거래로
# 쓴다(전부 또는 없음). 확인은 잠금 안에서 다시 한다.

ADOPT_LOCK: Final = ".kookabug/adopt.lock"
ADOPTIONS_DIR: Final = "knowledge/adoptions"
CASES_DIR: Final = "knowledge/cases"


class AdoptFailed(Exception):
    """조건 하나가 실패했다 (아무것도 쓰지 않았다)."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.detail)
        self.problem = problem


@dataclass(frozen=True, slots=True)
class Manifest:
    """채택 manifest (R1): 검증 시작 때 고정한 것. 게시 직전에 같은지 다시 본다."""

    digest: str
    change: str
    candidate: Mapping[str, str]
    """후보 경로 → 사본 sha."""
    base: Mapping[str, str | None]
    """후보 경로 → 바탕 팀 sha (`base_sha256`)."""
    team: Mapping[str, str | None]
    """후보 밖 의존성 폐포 경로 → 그때 팀 sha (그래프·서브그래프·target·PNG·화면·kookabug.json)."""
    claims: Mapping[str, int | None]
    policy_sha: str
    tests: tuple[str, ...]
    """원래 테스트, 그다음 영향 테스트 (조건 6 — 게시 직전에 지금 팀으로 다시 계산해 같아야
    한다)."""
    refs: Mapping[str, str] = field(default_factory=dict[str, str])
    """조건 2 참조 스캔: 이 target을 `$target`으로 읽는 팀 tests·subgraphs·screens 파일 → sha."""
    image_users: tuple[str, ...] = ()
    """이 target의 PNG를 함께 쓰는 다른 팀 target (조건 2 공유 이미지)."""


def policy_sha(automation: Mapping[str, Any]) -> str:
    from kookabug_core.canonical import canonical_dumps

    return hashlib.sha256(canonical_dumps(dict(automation)).encode("utf-8")).hexdigest()


def case_rel(case_id: str) -> str:
    return f"{CASES_DIR}/{case_id}.json"


def adoption_rel(adoption_id: str) -> str:
    return f"{ADOPTIONS_DIR}/{adoption_id}.json"


def _load_json(root: Path, rel: str, kind: str) -> tuple[dict[str, Any], str] | None:
    from kookabug_core import filetx
    from kookabug_core.canonical import loads_strict
    from kookabug_core.knowledge.formats import KnowledgeError, shape_problem

    data = filetx.read(root, rel)
    if data is None:
        return None
    try:
        doc = loads_strict(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise KnowledgeError("format", f"'{rel}'을(를) 읽을 수 없다", file=rel) from exc
    problem = shape_problem(doc, kind)
    if problem is not None:
        raise KnowledgeError("format", f"'{rel}'의 형식이 틀렸다 ({problem})", file=rel)
    return cast(dict[str, Any], doc), filetx.sha256_of(data)


def load_case(root: Path, case_id: str) -> tuple[dict[str, Any], str]:
    from kookabug_core.knowledge.formats import KnowledgeError

    if not re.fullmatch(r"c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", case_id):
        raise KnowledgeError("unknown_id", "사건 ID 형식이 틀렸다", id=case_id)
    found = _load_json(root, case_rel(case_id), "case")
    if found is None:
        raise KnowledgeError("unknown_id", "없는 사건이다", id=case_id)
    return found


def load_adoption(root: Path, adoption_id: str) -> tuple[dict[str, Any], str]:
    from kookabug_core.knowledge.formats import KnowledgeError

    if not re.fullmatch(r"a-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}", adoption_id):
        raise KnowledgeError("unknown_id", "채택 ID 형식이 틀렸다", id=adoption_id)
    found = _load_json(root, adoption_rel(adoption_id), "adoption")
    if found is None:
        raise KnowledgeError("unknown_id", "없는 채택이다", id=adoption_id)
    return found


def list_adoptions(root: Path) -> list[dict[str, Any]]:
    folder = root / ADOPTIONS_DIR
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("a-*.json")):
        try:
            found = load_adoption(root, path.stem)
        except Exception:
            continue
        out.append(found[0])
    return out


def count_auto(root: Path, policy: str) -> int:
    """지금 정책 digest 아래 자동 채택 수 (되돌린 것 제외 — 조건 7)."""
    return sum(
        1
        for a in list_adoptions(root)
        if a.get("kind") == "auto" and a.get("policy_sha") == policy and a.get("reverted") is None
    )


def _put_case(tx: Any, doc: Mapping[str, Any], sha: str, **changes: Any) -> None:
    from kookabug_core.knowledge import store
    from kookabug_core.knowledge.formats import KnowledgeError, shape_problem

    new = dict(doc)
    new.update(changes)
    new["revision"] = int(doc["revision"]) + 1
    problem = shape_problem(new, "case")
    if problem is not None:
        raise KnowledgeError("format", f"사건 형식이 틀렸다 ({problem})")
    tx.write(case_rel(str(doc["id"])), store.encode(new), expect_sha=sha)


def _prev_bundle(adoption_id: str, files: Mapping[str, bytes], by: Mapping[str, Any]) -> Any:
    """채택 전 원래 팀 바이트 묶음 `e-<채택>-prev` (되돌리기가 sha로 찾는다)."""
    from kookabug_core import evidence

    named = {
        f"{i}-{PurePosixPath(rel).name}"[:128]: data for i, (rel, data) in enumerate(files.items())
    }
    return evidence.raw(
        bundle_id=f"e-{adoption_id}-prev",
        files=named,
        by=by,
        origin=f"채택 {adoption_id} 전 팀 파일의 원래 바이트 (되돌리기용)",
    )


def publish_auto(
    root: Path,
    manifest: Manifest,
    *,
    case_id: str,
    runs: Sequence[str],
    negatives: Sequence[Mapping[str, Any]],
    max_adoptions: int,
    check: Callable[[], Problem | None],
    check_secrets: Callable[[Sequence[tuple[str, str]]], None] | None = None,
    job: str | None = None,
) -> dict[str, Any]:
    """조건 7·8 (R1): 채택 잠금 안에서 후보 digest·정책 digest·팀 revision(후보 밖 폐포·주장
    rev)·누적 상한을 다시 확인하고 한 거래로 게시한다. `check()`는 잠금 안에서 부르는 추가
    확인(정책·폐포·참조 목록·영향 테스트를 지금 다시 계산해 비교 — 부르는 쪽이 만든다). 실패는
    `AdoptFailed`. `check_secrets`를 주면 채택 기록·감사 이력 줄 전체를 쓰기 전에 글자 검사한다
    (걸리면 `secret_in_text`, 아무것도 쓰지 않음)."""
    from kookabug_core import basis, evidence, filetx
    from kookabug_core.knowledge.formats import Actor, new_id, now, strings_of
    from kookabug_core.knowledge.ops import log_into

    # 작업이 낸 채택 요청이면 감사 이력에 그 작업을 남긴다 (보고 항목 `auto_adopted`의 근거, B5)
    actor = Actor("kookabug", "adopt", job=job)
    with filetx.file_lock(root, ADOPT_LOCK), filetx.locked(root):
        change = basis.load_change(root, manifest.change)
        if change is None or change.state != "active":
            raise AdoptFailed(Problem(8, "revision_conflict", "작업 기준 변경이 그 사이 바뀌었다"))
        # 후보·바탕 sha는 정규화 키로 찾는다 (변경 기록의 철자가 manifest와 달라도 같은 파일)
        candidate = {path_key(k): v for k, v in manifest.candidate.items()}
        base = {path_key(k): v for k, v in manifest.base.items()}
        copies: dict[str, bytes] = {}
        for entry in change.files:
            data = basis.copy_bytes(root, change, entry)
            rel = str(entry["path"])
            if data is None or candidate.get(path_key(rel)) != filetx.sha256_of(data):
                raise AdoptFailed(
                    Problem(8, "revision_conflict", "검증한 뒤 후보가 바뀌어 게시하지 않았다")
                )
            copies[rel] = data
        if {path_key(rel) for rel in copies} != set(candidate) or len(copies) != len(candidate):
            raise AdoptFailed(
                Problem(8, "revision_conflict", "검증한 뒤 후보 파일 목록이 바뀌었다")
            )
        problem = check()
        if problem is not None:
            raise AdoptFailed(problem)
        if count_auto(root, manifest.policy_sha) >= max_adoptions:
            raise AdoptFailed(
                Problem(
                    7, "adoption_cap", f"이 정책 아래 자동 채택이 상한({max_adoptions})에 닿았다"
                )
            )
        befores: dict[str, bytes] = {}
        for rel in sorted(copies):
            current = filetx.read(root, rel)
            sha = None if current is None else filetx.sha256_of(current)
            if sha != base[path_key(rel)]:
                raise AdoptFailed(
                    Problem(8, "revision_conflict", f"팀 파일 '{rel}'이(가) 그 사이 바뀌었다")
                )
            if current is not None:
                befores[rel] = current
        case_doc, case_sha = load_case(root, case_id)
        adoption_id = new_id("a")
        at = now()
        record: dict[str, Any] = {
            "format": "kookabug.adoption/0",
            "id": adoption_id,
            "kind": "auto",
            "case": case_id,
            "change": change.id,
            "files": [
                {
                    "path": rel,
                    "before_sha256": base[path_key(rel)],
                    "after_sha256": filetx.sha256_of(copies[rel]),
                }
                for rel in sorted(copies)
            ],
            "runs": list(runs),
            "negatives": [dict(n) for n in negatives],
            "policy_sha": manifest.policy_sha,
            "by": {"kind": "kookabug"},
            "at": at,
            "reverted": None,
        }
        log_entry = {
            "op": "adopt",
            "file": adoption_rel(adoption_id),
            "id": adoption_id,
            "fields": sorted(copies),
            "result": "applied",
        }
        if check_secrets is not None:
            check_secrets(
                [
                    *strings_of(record, "adoption"),
                    *strings_of(log_entry, "log"),
                    *actor.texts(),
                ]
            )
        tx = filetx.Tx(root)
        for rel, data in sorted(copies.items()):
            tx.write(rel, data, expect_sha=base[path_key(rel)])
        tx.create(adoption_rel(adoption_id), _encode(record, "adoption"))
        if befores:
            evidence.add_to(tx, _prev_bundle(adoption_id, befores, {"kind": "kookabug"}))
        basis.put_state(tx, change, "adopted")
        links = dict(cast(Mapping[str, Any], case_doc.get("links") or {}))
        links["adoption"] = adoption_id
        working = list(links.get("working") or [])
        if change.id not in working:
            working.append(change.id)
        links["working"] = working
        _put_case(
            tx,
            case_doc,
            case_sha,
            state="resolved",
            resolution={"by": "adoption", "adoption": adoption_id, "at": at},
            links=links,
        )
        log_into(root, tx, [log_entry], actor)
        tx.commit()
    return record


def log_cancelled(root: Path, case_id: str, change_id: str, *, job: str | None = None) -> None:
    """취소된 자동 채택 요청을 감사 이력에 남긴다 (게시하지 않았다 — 사건·작업 기준 변경은 그대로).
    ID 두 개는 요청이 준 값이지만 이미 있는 사건·변경 ID로 확인된 것이다."""
    from kookabug_core import filetx
    from kookabug_core.knowledge.formats import Actor
    from kookabug_core.knowledge.ops import log_into

    entry = {
        "op": "adopt",
        "file": case_rel(case_id),
        "id": change_id,
        "result": "refused",
        "code": "adopt_cancelled",
    }
    with filetx.file_lock(root, ADOPT_LOCK), filetx.locked(root):
        tx = filetx.Tx(root)
        log_into(root, tx, [entry], Actor("kookabug", "adopt", job=job))
        tx.commit()


def _encode(doc: Mapping[str, Any], kind: str) -> bytes:
    from kookabug_core.knowledge import store
    from kookabug_core.knowledge.formats import KnowledgeError, shape_problem

    problem = shape_problem(dict(doc), kind)
    if problem is not None:
        raise KnowledgeError("format", f"{kind} 형식이 틀렸다 ({problem})")
    return store.encode(dict(doc))


def revert(root: Path, adoption_id: str, *, by: str) -> dict[str, Any]:
    """`adopt.revert` (사람 전용): 지금 팀 파일이 채택 뒤 바이트일 때만 원래 바이트로 되돌린다. 한
    번만(`already_reverted`). 사용자가 그사이 고쳤으면 `revision_conflict`로 아무것도 안 한다.
    사건은 `open`, 변경은 `reverted`. 게임 계정·서버 상태는 되돌리지 않는다."""
    from kookabug_core import basis, evidence, filetx
    from kookabug_core.knowledge.formats import Actor, KnowledgeError, new_id, now
    from kookabug_core.knowledge.ops import log_into

    actor = Actor("human", by)
    try:
        with filetx.file_lock(root, ADOPT_LOCK), filetx.locked(root):
            record, record_sha = load_adoption(root, adoption_id)
            if record.get("kind") == "revert":
                raise KnowledgeError("format", "되돌리기 기록은 되돌리지 않는다")
            if record.get("reverted") is not None:
                raise KnowledgeError("already_reverted", "이미 되돌린 채택이다")
            files = cast(list[dict[str, Any]], record.get("files") or [])
            if not files:
                raise KnowledgeError("nothing_to_revert", "되돌릴 파일이 없는 채택이다")
            manifest = evidence.load_manifest(root, f"e-{adoption_id}-prev")
            tx = filetx.Tx(root)
            for item in files:
                rel = str(item["path"])
                current = filetx.read(root, rel)
                sha = None if current is None else filetx.sha256_of(current)
                if sha != item["after_sha256"]:
                    raise KnowledgeError(
                        "revision_conflict",
                        f"'{rel}'이(가) 채택 뒤 바뀌어 되돌리지 않았다",
                        path=rel,
                    )
                before = item["before_sha256"]
                if before is None:
                    tx.delete(rel, expect_sha=str(sha))
                    continue
                listed = cast(list[dict[str, Any]], (manifest or {}).get("files") or [])
                prev_file = next((f for f in listed if f.get("sha256") == before), None)
                data = (
                    None
                    if prev_file is None
                    else filetx.read(
                        root, f"knowledge/evidence/e-{adoption_id}-prev/{prev_file['path']}"
                    )
                )
                if data is None or filetx.sha256_of(data) != before:
                    raise KnowledgeError(
                        "evidence_missing", f"'{rel}'의 원래 바이트 묶음이 없어 되돌리지 않았다"
                    )
                tx.replace(rel, data, expect_sha=str(sha))
            revert_id = new_id("a")
            at = now()
            tx.create(
                adoption_rel(revert_id),
                _encode(
                    {
                        "format": "kookabug.adoption/0",
                        "id": revert_id,
                        "kind": "revert",
                        "case": record.get("case"),
                        "change": record.get("change"),
                        "changes": list(record.get("changes") or []),
                        "files": [
                            {
                                "path": f["path"],
                                "before_sha256": f["after_sha256"],
                                "after_sha256": f["before_sha256"],
                            }
                            for f in files
                        ],
                        "by": {"kind": "human", "id": by},
                        "at": at,
                        "reverted": {"adoption": adoption_id, "at": at},
                    },
                    "adoption",
                ),
            )
            updated = dict(record)
            updated["reverted"] = {"adoption": revert_id, "at": at}
            tx.write(adoption_rel(adoption_id), _encode(updated, "adoption"), expect_sha=record_sha)
            change_ids = [record["change"]] if record.get("change") else []
            change_ids += list(record.get("changes") or [])
            for cid in change_ids:
                change = basis.load_change(root, str(cid))
                if change is not None and change.state in ("adopted", "accepted"):
                    basis.put_state(tx, change, "reverted")
            case_id = record.get("case")
            if isinstance(case_id, str):
                try:
                    found: tuple[dict[str, Any], str] | None = load_case(root, case_id)
                except KnowledgeError:
                    found = None
                if found is not None and found[0].get("state") == "resolved":
                    _put_case(tx, found[0], found[1], state="open", resolution=None)
            log_into(
                root,
                tx,
                [
                    {
                        "op": "revert",
                        "file": adoption_rel(adoption_id),
                        "id": adoption_id,
                        "fields": [str(f["path"]) for f in files],
                        "result": "applied",
                    }
                ],
                actor,
            )
            tx.commit()
    except filetx.TxError as exc:
        raise KnowledgeError(exc.code, exc.message) from exc
    return {
        "adoption": adoption_id,
        "reverted": revert_id,
        "files": [str(f["path"]) for f in files],
    }


def decide(
    root: Path,
    *,
    changes: Sequence[str],
    claims: Sequence[Mapping[str, Any]],
    accept: bool,
    by: str,
    also: Callable[[Any], None] | None = None,
) -> dict[str, Any]:
    """`working.accept`·`working.reject` (사람 전용). 수락은 파일 변경·작업 주장을 한 거래로 팀에
    반영한다(전부 또는 없음): 변경마다 팀 파일 sha가 `base_sha256`와 같아야 하고
    (`revision_conflict`),
    사본이 `after_sha256`와 같아야 한다. 거절은 덧씌움에서 뺀다(`rejected`, 팀 파일 그대로).
    화면 지도 후보는 다루지 않는다(D6 승격).

    `also(tx)`: 같은 잠금·같은 거래에 더 쓸 것 (M8 `report.decide`의 보고 결정 — 재확인도 그 안에서
    한다). 예외를 내면 아무것도 반영하지 않는다."""
    from kookabug_core import basis, evidence, filetx
    from kookabug_core.knowledge.formats import Actor, KnowledgeError, new_id, now
    from kookabug_core.knowledge.ops import decide_working_claims, log_into

    if not changes and not claims:
        raise KnowledgeError("format", "고를 변경·주장이 없다")
    actor = Actor("human", by)
    try:
        with filetx.file_lock(root, ADOPT_LOCK), filetx.locked(root):
            loaded: list[basis.Change] = []
            for cid in dict.fromkeys(changes):
                change = basis.load_change(root, cid)
                if change is None:
                    raise KnowledgeError("unknown_id", "없는 작업 기준 변경이다", id=cid)
                if change.state != "active":
                    raise KnowledgeError(
                        "change_not_active",
                        f"작업 기준 변경 {cid}은(는) {change.state}이다",
                        id=cid,
                    )
                loaded.append(change)
            tx = filetx.Tx(root)
            writes: dict[str, tuple[bytes, str | None]] = {}
            befores: dict[str, bytes] = {}
            entries: list[dict[str, Any]] = []
            if accept:
                for change in loaded:
                    for item in change.files:
                        rel = str(item["path"])
                        if path_key(rel) in {path_key(w) for w in writes}:
                            raise KnowledgeError(
                                "format", f"'{rel}'을(를) 두 변경이 담아 한 번에 수락할 수 없다"
                            )
                        current = filetx.read(root, rel)
                        sha = None if current is None else filetx.sha256_of(current)
                        if sha != item["base_sha256"]:
                            raise KnowledgeError(
                                "revision_conflict",
                                f"팀 파일 '{rel}'이(가) 작업 기준을 만든 뒤 바뀌었다 — 다시 확인",
                                id=change.id,
                                path=rel,
                            )
                        data = basis.copy_bytes(root, change, item)
                        if data is None:
                            raise KnowledgeError(
                                "revision_conflict",
                                f"작업 사본 '{rel}'이(가) 기록과 다르다",
                                id=change.id,
                            )
                        writes[rel] = (data, sha)
                        if current is not None:
                            befores[rel] = current
            for rel, (data, sha) in sorted(writes.items()):
                tx.write(rel, data, expect_sha=sha)
            decided = (
                decide_working_claims(root, tx, claims, actor=actor, accept=accept)
                if claims
                else {"claims": [], "conflicts": [], "entries": []}
            )
            entries += decided["entries"]
            adoption_id: str | None = None
            at = now()
            if accept:
                adoption_id = new_id("a")
                tx.create(
                    adoption_rel(adoption_id),
                    _encode(
                        {
                            "format": "kookabug.adoption/0",
                            "id": adoption_id,
                            "kind": "accept",
                            "case": None,
                            "change": None,
                            "changes": [c.id for c in loaded],
                            "files": [
                                {
                                    "path": rel,
                                    "before_sha256": sha,
                                    "after_sha256": filetx.sha256_of(data),
                                }
                                for rel, (data, sha) in sorted(writes.items())
                            ],
                            "by": {"kind": "human", "id": by},
                            "at": at,
                            "reverted": None,
                        },
                        "adoption",
                    ),
                )
                if befores:
                    evidence.add_to(
                        tx, _prev_bundle(adoption_id, befores, {"kind": "human", "id": by})
                    )
            for change in loaded:
                basis.put_state(tx, change, "accepted" if accept else "rejected")
            if accept:
                for case_id in sorted({str(c.doc["case"]) for c in loaded if c.doc.get("case")}):
                    try:
                        case_doc, case_sha = load_case(root, case_id)
                    except KnowledgeError:
                        continue
                    if case_doc.get("state") in ("resolved", "closed"):
                        continue
                    links = dict(cast(Mapping[str, Any], case_doc.get("links") or {}))
                    links["adoption"] = adoption_id
                    _put_case(
                        tx,
                        case_doc,
                        case_sha,
                        state="resolved",
                        resolution={"by": "human", "adoption": adoption_id, "at": at},
                        links=links,
                    )
            entries += [
                {
                    "op": "accept" if accept else "reject",
                    "file": basis.change_rel(c.id),
                    "id": c.id,
                    "fields": c.paths(),
                    "result": "applied",
                }
                for c in loaded
            ]
            if also is not None:
                also(tx)
            log_into(root, tx, entries, actor)
            tx.commit()
    except filetx.TxError as exc:
        if exc.code == "tx_invalid":
            raise KnowledgeError("format", exc.message) from exc
        raise KnowledgeError(exc.code, exc.message) from exc
    return {
        "adoption": adoption_id,
        "changes": [c.id for c in loaded],
        "files": sorted(writes),
        "claims": decided["claims"],
        "conflicts": decided["conflicts"],
    }
