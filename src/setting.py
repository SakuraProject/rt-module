# Setting, Description: ダッシュボードのコマンドのデータの型等がある。

from __future__ import annotations

from typing import TypedDict, Union, Literal


class CommandData(TypedDict, total=False):
    headding: dict[str, str]
    category: dict[str, str]
    help: dict[str, str]
    kwargs: dict[str, Union[Literal["Chanenl", "Role", "User"], str]]