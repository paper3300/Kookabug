"""Kookabug 코어 노드."""

__version__ = "0.1.0.dev0"

# 노드가 있는 모듈. pyproject `[tool.kookabug].modules`와 같다 (설치된 wheel에는 pyproject가 없다)
MODULES = (
    "kookabug_nodes.graph",
    "kookabug_nodes.test",
    "kookabug_nodes.flow",
    "kookabug_nodes.values",
    "kookabug_nodes.log",
)
