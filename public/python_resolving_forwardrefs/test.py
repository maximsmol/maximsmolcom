# note: must go first
from type_check import check_type

import json
from typeguard import check_type as tg_check_type
from fn import test, test_beartype, test_beartype_simple
from json_type import TestType

# all of these typecheck
test(1)
test("hello")
test(False)
test(None)
test([1, 2, 3])
test({"hello": "world"})

# ---

print("Trying beartype with `JsonValue`:")

try:
    test_beartype([[]])
except Exception as e:
    # explicit type aliases are not supported?
    #
    # beartype.roar.BeartypeCallHintForwardRefException:
    # Forward reference 'fn.JsonValue' referent
    # typing.Union[
    #   int, float, str, bool,
    #   NoneType, typing.List[ForwardRef('JsonValue')],
    #   typing.Dict[str, ForwardRef('JsonValue')]
    # ] not class.
    print(e)

print("\nTrying beartype with `ArrayOfTest`:")

try:
    test_beartype_simple([TestType()])
except Exception as e:
    # beartype.roar.BeartypeCallHintForwardRefException:
    # Forward reference "fn.TestType" unimportable.
    print(e)

# ---

print("\nTrying typeguard:")

from json_type import JsonValue as JsonVal

x = tg_check_type([set()], JsonVal)
# TypeHintWarning: Cannot resolve forward reference 'JsonValue'

try:
    print(json.dumps(x))
except Exception as e:
    print(e)

# ---
print("\nTrying `ForwardRef` monkey-patch:")
assert check_type(1, JsonVal)
assert check_type("hello", JsonVal)
assert check_type(False, JsonVal)
assert check_type(None, JsonVal)
assert check_type([1, 2, 3], JsonVal)
assert check_type({"hello": "world"}, JsonVal)
print("  All good")
