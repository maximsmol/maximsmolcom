from typing import Dict, List, TypeAlias
from beartype.roar import BeartypeDecorHintPep585DeprecationWarning

import warnings

warnings.simplefilter("ignore", BeartypeDecorHintPep585DeprecationWarning)

JsonValue: TypeAlias = (
    int | float | str | bool | None | List["JsonValue"] | Dict[str, "JsonValue"]
)


class TestType: ...


ArrayOfTest: TypeAlias = List["TestType"]

# using Python 3.12
type JsonValue312 = (
    int | float | str | bool | None | list[JsonValue312] | dict[str, JsonValue312]
)
