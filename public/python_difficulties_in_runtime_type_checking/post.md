# Python: Difficulties in Runtime Type-checking

Static typing is relatively unpopular in the Python ecosystem, despite [the standard library including a module](https://docs.python.org/3/library/typing.html) since 3.5, which released September 13, 2015 (more than 8 years ago!)[^python35-release]

Adoption is slow in large part because using Python types with non-trivial code can be _extremely hard._ Consider the problem of ingesting external data, such as

- SQL query results or
- JSON/YAML from APIs or files.

---

The typical solution is to type the data as `typing.Any` which

1. spreads like a virus through all downstream uses of the data and
2. lacks any IDE support like autocomplete.

```py3
data: typing.Any = res.json() # {"user_id": "df25a386-fc0d-4d5d-9d9d-47df52b3f19f"}
uid = data["user_id"] # note: this will not autocomplete

# type of `uid` is `typing.Any`

next_user = uid + 1
# Python exception:
# ‼️ TypeError: can only concatenate str (not "int") to str
```

---

A better alternative is to define the expected data type, then use `typing.cast`:

```py3
class UserPayload(TypedDict):
    user_id: str

user_data = typing.cast(UserPayload, res.json())
uid = user_data["user_id"] # note: `user_id` autocompletes!

# type of `uid` is `str`

next_user = uid + 1
# IDE warning from pyright:
# ⚠️ Operator "+" not supported for types "str" and "Literal[1]"
```

This is still merely a hack since casting simply silences the type error without doing anything to ensure the data has the expected type.

```py3
x: str = typing.cast(str, 123) # obviously broken but no error

x.lower()
# ‼️ AttributeError: 'int' object has no attribute 'lower'
```

---

The best possible solution is to somehow do a type-check at runtime.

The requirements are:

1. use the standard `typing` type annotations,
2. verify that data is compatible with the expected type,
3. not change the data itself.

This eliminates existing libraries like [Pydantic](https://github.com/pydantic/pydantic) and [marshmallow](https://github.com/marshmallow-code/marshmallow) which require using custom definitions for data models/schemas. Both these libraries also focus on more general issues of data validation (e.g. conditions like `x > 10`), serialization and parsing, etc. We only care about types.

**Possible solutions:**

- [Typeguard](https://github.com/agronholm/typeguard) is probably the best known one
  - Rewrites the instrumented function body to add type checks
  - [It is relatively inactive and looking for a new maintainer](https://github.com/agronholm/typeguard/issues/198)
- [Beartype](https://github.com/beartype/beartype) is probably the most complete one
  - Wraps functions in a proxy function that does the type checks
  - _Does not expose a `check_type` function._ Only a decorator
  - Sidenote: the documentation is **very** strange and the code is unusual

## Evaluating Our Options

Let's test these runtime type checkers. Consider the example of an API that returns "any valid JSON" as metadata in its response:

```json
// curl https://example.com/user/12345
{
  "id": 12345,
  "name": "John Doe",

  // this is arbitrary JSON
  "metadata": {
    "number": 111,
    "note": "hello world",
    "todo": ["buy milk", "write book"]
    // ...
  }
}
```

---

We try define the Python type for `user["metadata"]` and get `NameError`s:

```py3
JsonValue = (
  # supported primitive values
  int | float | str | bool | None |

  List[JsonValue] | # ‼️ NameError: name 'JsonValue' is not defined
  Dict[str, JsonValue] # ‼️ NameError: name 'JsonValue' is not defined
)
```

To fix them we use string annotations:[^pep695]

```py3
JsonValue = (
  # supported primitive values
  int | float | str | bool | None |

  List["JsonValue"] |
  Dict[str, "JsonValue"]
)
```

Now, we can try to use `JsonValue` with our typecheckers.

---

When we test in a context where `JsonValue` is not available by its original name, Typeguard breaks:

```py3
from json_type import JsonValue as JsonVal

# Note that "JsonValue" is not in scope since we renamed it:
# >>> print(JsonValue)
# NameError: name 'JsonValue' is not defined

x = typeguard.check_type([set()], JsonVal)
# TypeHintWarning: Cannot resolve forward reference 'JsonValue'

# The type check does not prevent a downstream error:
print(json.dumps(x))
# ‼️‼️‼️
# TypeError: Object of type set is not JSON serializable
# ‼️‼️‼️
```

[Beartype breaks in a similar way.](#breaking-beartype) <br/> [So do the standard library utilities.](#typing-get-type-hints)

---

Here is a rough outline of what happens:

1. When we used string annotations, we introduced a new type, `typing.ForwardRef`:
   ```pycon
   >>> JsonValue
   typing.Union[
     int, float, str, bool, NoneType,
     typing.List[ForwardRef('JsonValue')],
     typing.Dict[str, ForwardRef('JsonValue')]
   ]
   ```
1. The type checker starts to type check our value `[set()]` by trying to match it with `JsonValue` i.e. `typing.Union[int, float, ...]`.

1. Since `[set()]` is a list, it matches the `typing.List[...]` type, and the type checker recurses on the elements.

1. The first element is `set()` and we must match it with `ForwardRef('JsonValue')` which is the type of the elements specified in our `typing.List`.

1. The `ForwardRef` says to look for a type named `JsonValue`, so we look for `JsonValue` in the current scope and don't find it. Remember that we imported it renamed as `JsonVal`.

1. At this point Beartype and the standard library throw an error and Typeguard silently ignores the type and prints a warning.

To fix this, we need to **find a way to reliably resolve `typing.ForwardRef` to its target, regardles of what is available in scope.** This is our ultimate goal.

## Investigating

---

Examining the `ForwardRef` value:

```pycon
>>> list_type = typing.get_args(json_type.JsonValue)[-2]; list_type
typing.List[ForwardRef('JsonValue')]

>>> fr = typing.get_args(list_type)[0]; fr
ForwardRef('JsonValue')

>>> pprint({k: getattr(fr, k) for k in dir(fr)})
{'__forward_arg__': 'JsonValue',
 '__forward_code__': <code object <module> at 0x10a1ebab0, file "<string>", line 1>,
 '__forward_evaluated__': False,
 '__forward_is_argument__': True,
 '__forward_is_class__': False,
 '__forward_module__': None,
 '__forward_value__': None,
 '_evaluate': <bound method ForwardRef._evaluate of ForwardRef('JsonValue')>,

 # unimportant attributes omitted
 ...}
```

Of particular interest is the `_evaluate` method as its name suggests that it might be related. Unfortunately, it is not as simple as calling it:

```pycon
>>> help(fr._evaluate)
Help on method _evaluate in module typing:

_evaluate(globalns, localns, recursive_guard) method of typing.ForwardRef instance
>>> fr._evaluate(globals(), locals(), set())
Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File ".../lib/python3.12/typing.py", line 900, in _evaluate
    eval(self.__forward_code__, globalns, localns),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "<string>", line 1, in <module>
NameError: name 'JsonValue' is not defined
```

We need to somehow come up with the `globals()` and `locals()` that have the referred-to type available. Ideally, these are the same namespaces as at the point of definition of the type.

## Monkey-patching `ForwardRef`

Since we get instances of the `ForwardRef` class, its `__init__` method must be called at some point:

```py3
og = ForwardRef.__init__
def tracer(self, *args, **kwargs):
    print(args, kwargs)
    return og(self, *args, **kwargs)
ForwardRef.__init__ = tracer

JsonValue: TypeAlias = (
    int | float | str | bool | None | List["JsonValue"] | Dict[str, "JsonValue"]
)

# ('JsonValue',) {'module': None, 'is_class': False}
# ('JsonValue',) {'module': None, 'is_class': False}
```

Now, as all the best Python hacks go, we break out `sys._getframe()`:[^cpython-warning]

```py3
def tracer(self, *args, **kwargs):
    global frame
    frame = sys._getframe().f_back  # get caller frame
    return og(self, *args, **kwargs)
```

```pycon
>>> frame.f_code.co_filename
'.../lib/python3.12/typing.py'
>>> frame.f_back.f_back.f_back.f_back.f_back.f_code.co_filename
'.../python_resolving_forwardrefs/json_type.py'
>>> top_fr = frame.f_back.f_back.f_back.f_back.f_back
>>> pprint(top_fr.f_globals)
{'JsonValue': typing.Union[int, float, str, bool, NoneType, typing.List[ForwardRef('JsonValue')], typing.Dict[str, ForwardRef('JsonValue')]],
 ...}
>>> fr._evaluate(top_fr.f_globals, top_fr.f_locals, set())
typing.Union[int, float, str, bool, NoneType, typing.List[ForwardRef('JsonValue')], typing.Dict[str, ForwardRef('JsonValue')]]
```

Getting from here to a "production-ready" hack is relatively straightforward:

```py3
# to avoid polluting the class more than necessary,
# store all new state out-of-band
forward_frames: dict[int, FrameType] = {}

real_init = ForwardRef.__init__

def init(self, *args, **kwargs):
    cur = sys._getframe().f_back
    assert cur is not None

    typing_filename = cur.f_code.co_filename
    while cur is not None and cur.f_code.co_filename == typing_filename:
        cur = cur.f_back

    if cur is not None:
        forward_frames[id(self)] = cur
    real_init(self, *args, **kwargs)

ForwardRef.__init__ = init
```

Usage examples and a toy type-checker using the above code are available in [the code repository.](https://github.com/maximsmol/maximsmolcom/tree/4d694e70151b7d7751d92c9e8fcfa91b69176d1d/public/python_resolving_forwardrefs)

## Epilog

Python 3.12 avoided this issue in the new `type JsonValue = ...` ([PEP 695](https://peps.python.org/pep-0695/#generic-type-alias)) aliases. `TypeAlias` is being deprecated. The new syntax does not create `typing.ForwardRef` at all, instead the fully resolved target is stored in `typing.TypeAliasType.__value__`.

This is great!

Unfortunately, neither `beartype` nor `typeguard` support it yet.<br/>[`Mypy` also lacks support.](https://github.com/python/mypy/issues/15238)<br/>[`Pyright` commendably introduced support in May 2023.](https://github.com/microsoft/pyright/issues/5108)

### Rant (Deprecated in Python 3.12)

I'm leaving the following rant as-is for the following reasons:

- The overall message regarding future typing PEPs still stands.
  - It lists some reasons why PEP 695 is so good.
  - There are similar issues in other parts of the standard `typing` module.
  - Other typing PEPs need to get the message. Example: [PEP 563 i.e. `from __future__ import annotations`](https://peps.python.org/pep-0563/) would basically turn all annotations into strings that are impossible to evaluate at runtime.
- We will likely have to deal with leftover `ForwardRef`s for a few years.
- Most tools do not support the new syntax yet.
- Most people are not going to see the deprecation warning in the `TypeAlias` docs.
  - There should probably be a deprecation message on `ForwardRef` **and a runtime warning.**
- I've learned about PEP 695 only after finishing the post.

---

It simply should not be this hard to deal with Python's `typing`.

A simple task—reading external data—carries a gotcha in the standard library. Everything works as expected _unless_ a very specific set of circumstances arises. Maybe these circumstances are rare, but they are entirely plausible. The motivation for this hack came from production code not an academic exercise.

The specific conditions that trigger the problem are hard to explain and inconsistent between type checker implementations:

- Static type checkers (e.g. Mypy, Pyright) "just work"
- `typeguard.check_type` requires all `ForwardRef`s to be resolvable at call site
- `beartype` and `typeguard.typechecked` decorators require the `ForwardRef`s to be resolvable _at function definition site_
- [New Python features change the story entirely,](#python-3-9-generic-standard-collections) making it _worse_

Is it any wonder that adoption has been slow? When even modern projects _dedicated to type-checking_ get it wrong, the temptation is to just `typing.cast` away all problems.

---

**To turn this around, future PEPs should:**

1. strive for parity between runtime and static type-checking,
2. aim for [consistency above all](#python-3-10-union-inconsistency),
3. not accept [arbitrary limitations on standard library types and functions.](#typing-get-type-hints),
4. aim to provide _standard_ ways to interact with `typing`, ideally a reference type-checker implementation that is usable at runtime.

## Appendix

### `from __future__ import annotations` ([PEP 563](https://peps.python.org/pep-0563/))

Deferred annotation evaluation does nothing for us because the alias is defined in regular Python code and not an annotation:

```py3
from __future__ import annotations

class List1:
  child: List1 | None # PEP 563 makes this reference OK

List2 = List2 | None # regular Python variable, NOT an annotation
# ‼️ NameError: name 'List2' is not defined.
```

### Python 3.9 Generic Standard Collections

Using the [standard collections as generic types (PEP 585)](https://peps.python.org/pep-0585/) _does not produce a `ForwardRef`._ It leaves the value as a `str`:

```pycon
>>> typing.get_args(list["Test"])
('Test',)
>>> type(typing.get_args(list["Test"])[0])
<class 'str'>
```

A quote from the [standard library docs](https://docs.python.org/3/library/typing.html) supports this:

> Note: PEP 585 generic types such as `list["SomeClass"]` will not be implicitly transformed into `list[ForwardRef("SomeClass")]` and thus will not automatically resolve to `list[SomeClass]`.

Built-in classes like `list` and `str` cannot be patched.[^forbidden-fruit]
This means that this hack is _deprecated_ since 3.9 with no alternative. It might be possible to devise an even bigger hack, but for now I suggest simply using `typing.List` etc. when required.

### Breaking Beartype

1. Beartype with sometimes throw `BeartypeCallHintForwardRefException: Forward reference 'fn.JsonValue' referent ... not class.` when using `JsonValue` so we have to use a different type.
2. Need to use a function because we only get a decorator.

```py3
# test_type.py
class TestType: ...
ArrayOfTest: TypeAlias = List["TestType"]

# fn.py
from test_type import ArrayOfTest, TestType as TT

@beartype
def test(x: ArrayOfTest): ...

test([TT()])
# ‼️‼️‼️
# beartype.roar.BeartypeCallHintForwardRefException:
# Forward reference "fn.TestType" unimportable
# ‼️‼️‼️
```

### `typing.get_type_hints`

The standard library documentation [explicitly disclaims support for our usage of `ForwardRef` in the utility method `get_type_hints`:](https://docs.python.org/3/library/typing.html)

> **Note:** `get_type_hints()` does not work with imported type aliases that include forward references. Enabling postponed evaluation of annotations (PEP 563) may remove the need for most forward references.

### Python 3.10 Union Inconsistency

The new way of writing unions introduced in [PEP604](https://peps.python.org/pep-0604/) does not match `typing.Union` and gives inconsistent results depending on the type arguments:

```pycon
>>> int | list[str]
int | list[str]

>>> type(int | list[str])
<class 'types.UnionType'>
# not the same as `typing.Union`?

>>> int | typing.List[str]
typing.Union[int, typing.List[str]]
# why is this `typing.Union` now?

>>> # typing.Union is consistent:
>>> typing.Union[int, list[str]]
typing.Union[int, list[str]]
>>> typing.Union[int, typing.List[str]]
typing.Union[int, typing.List[str]]
```

## Reproducibility

[Code repository available on GitHub](https://github.com/maximsmol/maximsmolcom/tree/f1677c5c15441ab2568bd8e93845123195b70cc1/public/python_difficulties_in_runtime_type_checking)

All experiments were done with

- `Python 3.12.0 | packaged by Anaconda, Inc. | (main, Oct  2 2023, 12:29:27) [Clang 14.0.6 ] on darwin`
- `beartype==0.16.2`
- `typeguard==4.1.5`

## Footnotes

[^python35-release]: <https://www.python.org/downloads/release/python-350/>
[^pep695]: This has been deprecated in Python 3.12, the new syntax is `type JsonValue = ...` ([PEP 695](https://peps.python.org/pep-0695/#generic-type-alias)). More on this in [the epilog.](#epilog)
[^cpython-warning]: And break compatibility with some Python runtimes! `sys._getframe` is only predictable in the default CPython implementation.
[^forbidden-fruit]: Not strictly true, you can abuse C FFI to modify the method tables: <https://pypi.org/project/forbiddenfruit/>
