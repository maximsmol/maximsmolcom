import sys
from types import FrameType, UnionType
from typing import ForwardRef, Union, get_args, get_origin, TypeAliasType

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


def check_type(value: object, type) -> bool:
    origin = get_origin(type)
    if origin is Union or origin is UnionType:
        args = get_args(type)
        return any(check_type(value, x) for x in args)

    if isinstance(type, TypeAliasType):
        return check_type(value, type.__value__)

    if isinstance(type, ForwardRef):
        frame = forward_frames[id(type)]

        next = frame.f_globals.get(type.__forward_arg__)
        if next is None:
            next = frame.f_locals[type.__forward_arg__]

        return check_type(value, next)

    if origin is list:
        field_type = get_args(type)[0]
        return isinstance(value, list) and all(
            check_type(element, field_type) for element in value
        )

    if origin is dict:
        key_type, field_type = get_args(type)
        return isinstance(value, dict) and all(
            check_type(k, key_type) and check_type(v, field_type)
            for k, v in value.items()
        )

    if isinstance(value, type):
        return True

    return False
