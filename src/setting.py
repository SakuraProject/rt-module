# Setting, Description: ダッシュボードのコマンドのデータの型等がある。

from __future__ import annotations

from typing import TypedDict, Union, Optional, Literal, Any


class Kwargs(TypedDict):
    "ダッシュボードでのコマンドのキーワード引数のデータの型です。"
    type: Union[Literal["Chanenl", "Role", "User", "Literal", "str", "int", "float"], str]
    default: Union[str, int, float, None]
    extra: Optional[Union[dict, Any]]


class CommandData(TypedDict, total=False):
    "ダッシュボードのコマンドのデータの型です。"
    headding: dict[str, str]
    category: dict[str, str]
    kwargs: dict[str, Kwargs]
    help: str


class CommandRunData(TypedDict, total=False):
    "ダッシュボードからコマンドを実行した際の実行内容のデータの型です。"
    name: str
    kwargs: list[str]
    channel_id: int
    guild_id: int
    user_id: int