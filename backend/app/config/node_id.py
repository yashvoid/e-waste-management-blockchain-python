import re

_NODE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")


def is_valid_node_id(value: str) -> bool:
    return _NODE_ID_PATTERN.fullmatch(value) is not None
