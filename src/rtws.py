# RT - RTConnection

from __future__ import annotations

from typing import NewType, TypedDict, Literal, Union, Optional, Any
from collections.abc import Iterable

from dataclasses import dataclass

import asyncio

from inspect import iscoroutinefunction
from traceback import format_exc
from secrets import token_hex
from time import time

from websockets import connect, ConnectionClosed, WebSocketServerProtocol, WebSocketClientProtocol
from ujson import loads, dumps

from .utils import DataEvent


MainData = Optional[Union[dict[str, Any], list[Any], tuple[Any, ...], str, int, float, Any]]
WebSocket = Union[WebSocketServerProtocol, WebSocketClientProtocol]
Session = NewType("Session", str)


@dataclass
class Queues:
    sending: asyncio.Queue
    waiting: dict[Session, DataEvent]


class Packet(TypedDict):
    status: Literal["Ok", "Error"]
    type: Literal["request", "response"]
    data: MainData
    session: Session


class RTWebSocket:

    ws: Optional[WebSocket] = None
    queues: Optional[Queues] = None

    def __init__(
        self, name: str, *, timeout: float = 8, cooldown: float = 0.0001,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        self.name, self.timeout, self.cooldown = name, timeout, cooldown
        self._loop = loop

        self.started = asyncio.Event()

    def log(self, mode: str, *args, **kwargs) -> None:
        print(f"[RTWebSocket.{self.name}] [{mode}]", *args, **kwargs)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        "使用しているイベントループを返します。設定されていなければ自動で取得されます。"
        if self._loop is None: self._loop = asyncio.get_running_loop()
        return self._loop

    @loop.setter
    def loop(self, value: asyncio.AbstractEventLoop):
        "使用予定のイベントループを変更します。接続中の場合は設定できません。"
        assert not self.is_connected(), "既にイベントループは使用中のため設定できません。"
        self._loop = value

    async def wait_until_connect(self) -> None:
        "接続するまで待機します。"
        await self.started.wait()

    def is_connected(self) -> bool:
        "接続したかどうかです。"
        return self.started.is_set()

    def create_session(self) -> Session:
        "セッションコードを作成します。"
        return f"RTWS.{self.name}[{time()},{token_hex(8)}]"

    async def _process_request(self, data: Packet):
        ...

    async def _receiver_handler(self) -> None:
        # 受信を行います。
        async for data in self.ws.recv():
            if data == "ping": await self.ws.pong(); continue
            data: Packet = loads(data)
            if data["request"]:
                # リクエストの場合は相手からのリクエストを処理する。
                self.loop.create_task(
                    self._process_request(data),
                    name=f"RTWebSocket.processRequest: {self.name}"
                )
            else:
                # レスポンスの場合はレスポンス待機中のDataEventにレスポンスのデータを設定する。
                if data["session"] in self.queues.waiting:
                    self.queues.waiting[data["session"]].set(data)

    async def _sender_handler(self) -> None:
        # 送信を行います。
        while 1:
            await self.ws.send(
                dumps(await self.queues.sending.get(), ensure_ascii=False)
            )

    async def connect(self) -> None:
        "接続をしてバックエンドとの通信を開始します。"
        self.queues = Queues(asyncio.Queue(), asyncio.Queue(), asyncio.Queue())
        self.started.set()
        self.receiver_task = self.loop.create_task(
            self._receiver_handler(), name=f"RTWebSocket.receiver: {self.name}"
        )
        self.sender_task = self.loop.create_task(
            self._sender_handler(), name=f"RTWebSocket.sender: {self.name}"
        )
        _, pending = await asyncio.wait(
            (self.receiver_task, self.sender_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending: task.cancel()
        self.started.clear()

    async def start(
        self, ws: WebSocket, reconnect: bool = True,
        okstatus: Iterable[int] = (1000,)
    ) -> None:
        "WebSocketで`connect`を実行します。また、再接続を自動で行います。"
        self.ws = ws
        while reconnect:
            try: await self.connect()
            except ConnectionClosed as e:
                if (close := (e.rcvd or e.sent)).status in okstatus:
                    self.log(
                        "info", "Disconnected successfully: %s - %s"
                        % (close.status, close.reason)
                    )
                    break
                else:
                    self.log("error", "Disconnected due to internal error:\n%s" % format_exc())
            if reconnect: await asyncio.sleep(3)

    async def start_with_websockets(self, url: str, *args, **kwargs) -> None:
        "WebSocketライブラリのwebsocketsを使用して`start`を実行します。"
        self.start(await connect(url, *args, **kwargs))