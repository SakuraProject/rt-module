# Setting, Description: ダッシュボードのコマンドのデータの型等がある。

from typing import TypedDict


class CommandData(TypedDict, total=False):
    headding: str
    category: str
    help: str