# RT Module - Utils

from typing import TypeVar, Any

from asyncio import Event
from time import time


DataT = TypeVar("DataT")
class DataEvent(Event):
    "データを返すように設定した`asyncio.Event`です。"

    data: DataT = None

    def __init__(self, *args, subject: Any = None, **kwargs):
        self.subject = subject
        super().__init__(*args, **kwargs)

    def set(self, data: DataT) -> None:
        self.data = data
        return super().set()

    async def wait(self) -> DataT:
        await super().wait()
        return self.data

    def __str__(self) -> str:
        return f"<DataEvent subject={self.subject} original={Event.__str__(self)}>"


class TimedDataEvent(DataEvent):
    "`DataEvent`を時間を記録するように拡張したものです。"

    def __init__(self, *args, **kwargs):
        self.created_at = time()
        super().__init__(*args, **kwargs)

    def __str__(self) -> str:
        return DataEvent.__str__(self).replace(
            'DataEvent ', f'TimedDataEvent created_at={self.created_at} '
        )