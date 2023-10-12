from typing import Dict, List, TypeAlias
from beartype.roar import BeartypeDecorHintPep585DeprecationWarning

import warnings

warnings.simplefilter("ignore", BeartypeDecorHintPep585DeprecationWarning)

JsonValue: TypeAlias = (
    int | float | str | bool | None | List["JsonValue"] | Dict[str, "JsonValue"]
)


class TestType: ...


ArrayOfTest: TypeAlias = List["TestType"]
