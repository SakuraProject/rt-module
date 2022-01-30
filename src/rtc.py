# RT - RTConnection

from __future__ import annotations

from typing import (
    NewType, TypedDict, Coroutine, Callable, Literal, Union, Optional, Any
)

from asyncio import (
    AbstractEventLoop, get_running_loop, wait_for, TimeoutError as AioTimeoutError,
    sleep, Event
)
from traceback import print_exc
from secrets import token_hex
from time import time

from websockets import ConnectionClosed, WebSocketServerProtocol, WebSocketClientProtocol
from ujson import dumps, loads

from .utils import TimedDataEvent


#   Type
ResponseStatus = Union[Literal["Ok", "Error"], int, str]
SessionNonce = NewType("SessionName", str)
MainData = NewType("MainData", object)
class Data(TypedDict, total=False):
    "通信時のデータのJSONの辞書の型です。"
    # Main
    status: ResponseStatus
    data: MainData
    message: str
    # RTConnection
    event_name: Optional[str]
    session: Optional[SessionNonce]
    # Other
    extras: Any


EventCoroutine = Coroutine[Any, Any, MainData]
EventFunction = Callable[[MainData], EventCoroutine]


#   Normal
def response(status: ResponseStatus, data: MainData, message: str, **kwargs) -> dict:
    "レスポンスのデータを作ります。"
    kwargs["status"] = status
    kwargs["data"] = data
    kwargs["message"] = message
    return kwargs


def detect_nonce_name(nonce: SessionNonce) -> str:
    "セッションノンスから名前を割り出します。"
    return nonce[5:nonce.find(",")]


def create_session_nonce(
    name: Optional[str] = None, nonce_length: int = 5
) -> SessionNonce:
    "通信時にセッションとして使うノンスを作成します。"
    return f"Name:{name},Time:{time()},Nonce:{token_hex(nonce_length)}"


class RequestError(Exception):
    ...


class RTConnection:
    """RTConnectionをするためのクラスです。
    `websockets`ライブラリで使われることを想定しています。"""

    ws: Union[WebSocketServerProtocol, WebSocketClientProtocol] = None
    TIMEOUT = 5

    def __init__(
        self, name: str, *, cooldown: float = 0.01,
        loop: Optional[AbstractEventLoop] = None
    ):
        self.queues: dict[SessionNonce, TimedDataEvent] = {}
        self.name, self.cooldown = name, cooldown
        self.loop = loop
        self.ready = Event()

        self.events: dict[str, EventFunction] = {}

    def set_loop(self, loop: Optional[AbstractEventLoop]) -> None:
        "イベントループを設定します。これは接続以前に実行されるべきです。"
        self.loop = loop or get_running_loop()

    def _make_session_name(self, data: Data) -> str:
        return f"{data.get('event_name', '...')} - {data['session']}"

    @property
    def connected(self) -> bool:
        return self.ready.is_set()

    def set_event(self, function: EventFunction, name: Optional[str] = None) -> None:
        "イベントを登録します。"
        self.events[name or function.__name__] = function

    def remove_event(self, name: str) -> None:
        "イベントを削除します。"
        del self.events[name]

    async def request(
        self, event_name: str, data: MainData, message: str = "Fight"
    ) -> MainData:
        """リクエストをしてデータを取得します。"""
        session = create_session_nonce(self.name)
        self.queues[session] = (
            event := TimedDataEvent(
                subject=("request", response(
                    "Ok", data, message, event_name=event_name,
                    session=session
                ))
            )
        )
        event.sended = False
        # レスポンス
        try:
            data: Data = await wait_for(event.wait(), timeout=self.TIMEOUT)
        except AioTimeoutError:
            self.logger(
                "warning", "Timeout waiting for event: %s"
                % self._make_session_name({"session": session, "event_name": event_name})
            )
            data: Data = response("Error", None, "Timeout", session=session)
        if session in self.queues:
            del self.queues[session]
        if data["status"] == "Error":
            raise RequestError(data["message"])
        else:
            return data["data"]

    def on_response(self, data: Data) -> None:
        """渡されたセッションノンスに対応してレスポンスを待機しているセッションの`DataEvent`をsetします。
        `request`のレスポンスが帰ってきた際に呼び出されます。

        Raises: KeyError"""
        self.logger("info", "Received response: %s" % self._make_session_name(data))
        self.queues[data["session"]].set(data)

    def response(
        self, session: SessionNonce, data: MainData,
        status: ResponseStatus = "Ok", message: str = "Tired"
    ) -> None:
        """相手から来たリクエストへのレスポンスをするための関数です。"""
        self.queues[session] = TimedDataEvent(
            subject=("response", response(status, data, message, session=session))
        )

    async def process_request(self, data: Data):
        """相手から来たリクエストを処理します。
        この関数は何も実装されていません。
        この関数はリクエストのイベントに対応した関数を実行してその関数の返り値を`response`に渡すように実装しましょう。"""
        raise NotImplementedError()

    async def _wrap_error_handling(self, coro: EventCoroutine, data: Data) -> None:
        try:
            return self.response(data["session"], await coro)
        except Exception as e:
            print_exc()
            return self.response(
                data["session"], None, "Error", f"{e.__class__.__name__}: {e}"
            )

    def on_request(self, data: Data) -> None:
        """相手からリクエストがきた際に呼び出される関数です。
        `process_request`の呼び出しを`try`でラップしてエラーハンドリングをするコルーチン関数のコルーチンをイベントループにタスクとして追加します。"""
        self.logger("info", "Received request: %s" % self._make_session_name(data))
        if data["event_name"] in self.events:
            self.loop.create_task(
                self._wrap_error_handling(
                    self.events[data["event_name"]](data["data"]), data
                )
            )
        else:
            self.response(
                data["session"], None, "Error",
                f"EventNotFound: {data['event_name']}"
            )

    def logger(self, mode: str, *args, **kwargs) -> Any:
        "ログ出力をします。"
        return print(mode, *args, **kwargs)

    def get_queue(self) -> Optional[TimedDataEvent]:
        "一番登録されたのが遅いキューのキーとデータのタプルを返します。"
        before, before_key = time() + 1, None
        for key, value in list(self.queues.items()):
            if value.created_at < before:
                before, before_key = value.created_at, key
        if before_key is not None:
            return self.queues[before_key]

    async def communicate(
        self, ws: Union[WebSocketServerProtocol, WebSocketClientProtocol],
        first: bool = False
    ):
        "RTConnectionの通信を開始します。"
        if self.connected:
            return await ws.close(reason="既に接続されています。")
        assert self.loop is not None, "イベントループを設定してください。"
        self.ws, self.queues = ws, {}
        self.ready.set()
        self.logger("info", "Start RTConnection")
        # on_readyがあれば実行する。
        if "on_connect" in self.events:
            self.loop.create_task(self.events["on_connect"](self))

        try:
            while True:
                if first:
                    sent = False
                    if queue := self.get_queue():
                        if not getattr(queue, "sent", False):
                            self.logger("info", "Send data: %s" % self._make_session_name(queue.subject[1]))
                            queue.sent = True
                            await ws.send(dumps(queue.subject[1]))
                            sent = True
                        if queue.subject[0] == "response":
                            del self.queues[queue.subject[1]["session"]]
                    if not sent:
                        await ws.send("Nothing")
                await sleep(self.cooldown)
                data = await ws.recv()
                if data != "Nothing":
                    data: Data = loads(data)
                    if detect_nonce_name(data["session"]) == self.name:
                        self.on_response(data)
                    else:
                        self.on_request(data)
                await sleep(self.cooldown)
                if not first:
                    first = True
        except Exception as e:
            if isinstance(e, ConnectionClosed):
                self.logger("info", "Disconnected")
            else:
                self.logger("error", "Something went wrong")
                await ws.close()
            print_exc()
            self.last_exception = e
        finally:
            for queue in list(self.queues.values()):
                queue.set(response("Error", None, "Disconnected"))