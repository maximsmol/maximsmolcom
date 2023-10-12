from beartype import beartype

from json_type import JsonValue, ArrayOfTest


def test(x: JsonValue): ...


test_beartype = beartype(test)


@beartype
def test_beartype_simple(x: ArrayOfTest): ...
