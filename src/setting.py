# Setting, Description: ダッシュボードのコマンドのデータの型等がある。

from __future__ import annotations

from typing import TypedDict, Union, Optional, Literal, Any


class Kwargs(TypedDict):
    type: Union[Literal["Chanenl", "Role", "User", "Literal", "str", "int", "float"], str]
    default: Union[str, int, float, None]
    extra: Optional[Union[dict, Any]]


class CommandData(TypedDict, total=False):
    headding: dict[str, str]
    category: dict[str, str]
    help: dict[str, str]
    kwargs: dict[str, Kwargs]