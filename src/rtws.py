# RT - RTConnection

from __future__ import annotations

from typing import NewType, TypedDict, Literal, Union, Optional, Any
from collections.abc import Iterable, Callable, Coroutine, Sequence

from dataclasses import dataclass

import asyncio

from inspect import iscoroutinefunction
from traceback import format_exc
from secrets import token_hex
from time import time

from websockets import connect, WebSocketServerProtocol, WebSocketClientProtocol
from sanic.server.websockets.impl import WebsocketImplProtocol
from ujson import loads, dumps

from .utils import DataEvent


MainData = Optional[Union[dict[str, Any], list[Any], tuple[Any, ...], str, int, float, Any]]
WebSocket = Union[WebSocketServerProtocol, WebSocketClientProtocol, WebsocketImplProtocol]
Session = NewType("Session", str)


@dataclass
class Queues:
    sending: asyncio.Queue
    waiting: dict[Session, DataEvent]


class Packet(TypedDict):
    "通信時にどのようにデータを梱包するかの型です。"
    status: Literal["Ok", "Error"]
    type: Literal["request", "response"]
    data: Union[Sequence[Sequence[MainData], dict[str, MainData]], str]
    session: Session
    event: str


class RequestError(Exception):
    "リクエストに失敗した際に発生するエラーです。"


EventCoroutine = Coroutine[Any, Any, MainData]
EventFunction = Union[Callable[..., EventCoroutine], Callable[..., MainData]]


class RTWebSocket:
    "サーバーとクライアントと通信を簡単に行うためのものです。"

    ws: Optional[WebSocket] = None
    queues: Optional[Queues] = None

    def __init__(
        self, name: str, *, timeout: float = 10.0, cooldown: float = 0.0001,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        self.name, self.timeout, self.cooldown = name, timeout, cooldown
        self._loop = loop

        self.started = asyncio.Event()
        self.events: dict[str, EventFunction] = {}

        self._successfully_disconnected = None

    def set_event(self, function: EventFunction, name: Optional[str] = None) -> None:
        "イベントを設定します。相手はこれで設定したイベントを呼び出します。そしてこれで設定した関数が返した値を相手に送り返します。"
        awb = iscoroutinefunction(getattr(function, "__func__", function))
        try: function.__awaitable__ = awb
        except: function.__func__.__awaitable__ = awb
        self.events[name or function.__name__] = function

    def remove_event(self, function_or_name: Union[EventFunction, str]) -> None:
        "イベントを削除します。"
        if not isinstance(function_or_name, str):
            function_or_name = function_or_name.__name__
        del self.events[function_or_name]

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
        assert not self.is_ready(), "既にイベントループは使用中のため設定できません。"
        self._loop = value

    async def wait_until_ready(self) -> None:
        "接続するまで待機します。"
        await self.started.wait()

    def is_ready(self) -> bool:
        "準備完了かどうかです。"
        return self.started.is_set()

    def is_connected(self) -> bool:
        "接続をしているかどうかです。"
        return not self.ws.closed

    def make_session(self) -> Session:
        "セッションコードを作成します。"
        return f"RTWS.{self.name}[{time()},{token_hex(8)}]"

    def _packet_repr(self, request: Packet) -> str:
        # リクエストデータをログ等で識別するのに使える状態にします。
        return f"<Packet type={request['type']} event={request['event']} status={request['status']} session={request['session']}>"

    def _make_response(self, request: Packet, data: MainData, status: str) -> Packet:
        # レスポンスのデータを作ります。
        return Packet(
            status=status, type="response", data=data,
            session=request["session"], event=request["event"]
        )

    async def _process_request(self, request: Packet) -> None:
        # リクエストを処理します。
        try:
            assert request["event"] in self.events, "イベントが見つかりませんでした。"
            data = self.events[request["event"]](*request["data"][0], **request["data"][1])
            if self.events[request["event"]].__awaitable__:
                data = await data
            data = self._make_response(request, data, "Ok")
        except Exception:
            self.log(
                "warning", "An error occurred while processing the request: %s"
                % self._packet_repr(request)
            )
            data = self._make_response(request, format_exc(), "Error")
        await self.queues.sending.put(data)

    async def _receiver_handler(self) -> None:
        # 受信を行います。
        while self.is_connected():
            data: Packet = loads(await self.ws.recv())
            if data["type"] == "request":
                # リクエストの場合は相手からのリクエストを処理する。
                self.log("info", "Received request: %s" % self._packet_repr(data))
                self.loop.create_task(
                    self._process_request(data),
                    name=f"RTWebSocket.{self.name}: Process request"
                )
            else:
                # レスポンスの場合はレスポンス待機中のDataEventにレスポンスのデータを設定する。
                self.log("info", "Received response: %s" % self._packet_repr(data))
                if data["session"] in self.queues.waiting:
                    self.queues.waiting[data["session"]].set(data)

    async def _sender_handler(self) -> None:
        # 送信を行います。
        while self.is_connected():
            try: data: Packet = self.queues.sending.get_nowait()
            except asyncio.QueueEmpty: await asyncio.sleep(self.cooldown)
            else:
                self.log("info", "Send packet: %s" % self._packet_repr(data))
                await self.ws.send(dumps(data, ensure_ascii=False))

    async def request(self, event: str, *args, **kwargs) -> MainData:
        "リクエストを行います。相手側であらかじめ登録されているイベントに設定されている関数が返した値が返ります。"
        await self.queues.sending.put(data := Packet(
            status="Ok", type="request", data=(args, kwargs),
            session=self.make_session(), event=event
        ))
        self.queues.waiting[data["session"]] = DataEvent()
        try: data: Optional[Packet] = await asyncio.wait_for(
            self.queues.waiting[data["session"]].wait(), timeout=self.timeout
        )
        except asyncio.TimeoutError: raise RequestError(f"Failed to request: Timeout")
        if data is None: raise RequestError(f"Failed to request: Disconnected")
        if data["status"] == "Error":
            raise RequestError(f"Failed to request:\n{data['data']}")
        return data["data"]

    async def communicate(self) -> None:
        "接続をしてバックエンドとの通信を開始します。"
        assert self.ws is not None, "WebSocketが接続されていません。"
        self.clean()
        self.queues = Queues(asyncio.Queue(), {})
        self._disconnect_reason = None
        self.started.set()
        self.receiver_task = self.loop.create_task(
            self._receiver_handler(), name=f"RTWebSocket.{self.name}: Receiver"
        )
        self.sender_task = self.loop.create_task(
            self._sender_handler(), name=f"RTWebSocket.{self.name}: Sender"
        )
        self.log("info", "Started connection")
        done, pending = await asyncio.wait(
            (self.receiver_task, self.sender_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            try:
                if task.exception() is not None:
                    self.log("error", "Disconnected by error:", task.exception())
                    self._successfully_disconnected = task.exception()
            except asyncio.InvalidStateError: ...
        for task in pending: task.cancel()
        self.clean()
        self.started.clear()

    async def start(
        self, url: str, *args, reconnect: bool = True,
        okstatus: Iterable[int] = (1000,), **kwargs
    ) -> None:
        "`connect`でWebSocketを用意してから`communicate`を実行します。また、再接続を自動で行います。"
        while 1:
            try: self.ws = await self.connect(url, *args, **kwargs)
            except OSError as e: self.log("warning", "Failed to connect to WebSocket: %s" % e)
            else:
                await self.communicate()
                if hasattr(self.ws, "close_code"):
                    if self.ws.close_code in okstatus and self._successfully_disconnected is None:
                        self.log(
                            "info", "Disconnected successfully: %s %s"
                            % (self.ws.close_code, self.ws.close_reason)
                        )
                        break
                    else:
                        self.log(
                            "error", "Disconnected due to internal error: %s %s"
                            % (
                                (self.ws.close_code, self.ws.close_reason)
                                if self._successfully_disconnected is None else
                                (self._successfully_disconnected, "")
                            )
                        )
                else:
                    self.log("error", "Disconnected")
            if reconnect:
                self.log("info", "Retry the connection after 3 seconds")
                await asyncio.sleep(3)
            else: break

    async def connect(self, url: str, *args, **kwargs) -> None:
        "接続を行う関数です。デフォルトではwebsocketsというライブラリを使用します。"
        self.log("info", "Connecting...")
        return await connect(url, *args, **kwargs)

    async def close(self, *args, **kwargs) -> None:
        "WebSocketを閉じます。"
        assert self.ws is not None and self.is_connected(), "まだ接続していません。"
        self.log("info", "Closing...")
        await self.ws.close(*args, **kwargs)
        self.clean()

    def clean(self):
        "残っているWaitingのお片付けをする。"
        if self.queues and self.queues.waiting:
            self.log("info", "Cleaning...")
            for value in list(self.queues.waiting.values()):
                value.set(None)
            self.queues = None

    def __del__(self):
        self.clean()