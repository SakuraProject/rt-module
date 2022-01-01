# RT - RTConnection

from typing import (
    NewType, TypedDict, Coroutine, Callable, Literal, Union, Optional,
    Any, Dict
)

from asyncio import (
    AbstractEventLoop, get_event_loop, wait_for, TimeoutError, sleep
)
from secrets import token_hex
from time import time

from websockets import (
    ConnectionClosed, ConnectionClosedError,
    WebSocketServerProtocol, WebSocketClientProtocol
)
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
def response(status: ResponseStatus, data: MainData, message: str, **kwargs) -> str:
    "レスポンスのデータを作ります。"
    kwargs["status"] = status
    kwargs["data"] = data
    kwargs["message"] = message
    return dumps(kwargs)


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

    def __init__(
        self, name: str, *, cooldown: float = 0.001,
        loop: Optional[AbstractEventLoop] = None
    ):
        self.queues: Dict[SessionNonce, TimedDataEvent] = {}
        self.name, self.cooldown = name, cooldown
        self.loop = loop or get_event_loop()
        self.connected = False

        self.events: Dict[str, EventFunction] = {}

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
        self.queues[create_session_nonce(self.name)] = (
            event := TimedDataEvent(
                subject=("request", response(
                    "Ok", data, message, event_name=event_name,
                    session=create_session_nonce(self.name)
                ))
            )
        )
        # レスポンス
        data: Data = await event.wait()
        del self.queues[data["session"]]
        if data["status"] == "Error":
            raise RequestError(data["message"])
        else:
            return data["data"]

    def on_response(self, data: Data) -> None:
        """渡されたセッションノンスに対応してレスポンスを待機しているセッションの`DataEvent`をsetします。
        `request`のレスポンスが帰ってきた際に呼び出されます。

        Raises: KeyError"""
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
            return self.response(
                data["session"], None, "Error", f"{e.__class__.__name__}: {e}"
            )

    def on_request(self, data: Data) -> None:
        """相手からリクエストがきた際に呼び出される関数です。
        `process_request`の呼び出しを`try`でラップしてエラーハンドリングをするコルーチン関数のコルーチンをイベントループにタスクとして追加します。"""
        if data["event_name"] in self.events:
            self.loop.create_task(
                self._wrap_error_handling(
                    self.events[data["event_name"]](data["data"])
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
        self, ws: Union[WebSocketServerProtocol, WebSocketClientProtocol]
    ):
        "RTConnectionの通信を開始します。"
        if self.connected:
            await ws.close(reason="既に接続しています。")
        else:
            self.logger("info", "Start RTConnection")
            self.connected, self.ws = True, ws
            try:
                while True:
                    # 相手からのメッセージを待機する。
                    try:
                        data: Data = loads(
                            await wait_for(ws.recv(), timeout=self.cooldown)
                        )
                    except TimeoutError:
                        ...
                    else:
                        if detect_nonce_name(data["session"]) == self.NAME:
                            # リクエストのレスポンスなら
                            self.on_response(data)
                        else:
                            # 相手からのリクエストなら
                            self.on_request(data)
                    finally:
                        await sleep(self.cooldown)
                    # こっちからリクエストやレスポンスを送る。
                    if queue := self.get_queue():
                        print(queue.subject)
                        await ws.send(dumps(queue.subject[1]))
                        if queue.subject[0] == "Response":
                            del self.queues[queue.subject[1]["session"]]
            except ConnectionClosed as e:
                # 切断された際
                if isinstance(e, ConnectionClosedError):
                    self.logger("error", f"Disconnected by error:")
                    frame = e.sent or e.recv
                    if frame is not None:
                        self.logger("error", f"\tReason: {frame.reason}")
                else:
                    self.logger("info", "Disconnected successfully.")
            except Exception as e:
                # 切断以外でエラーを発生させてしまった場合はこっちから切断する。
                # ここは実行されるべきではない。
                self.logger("error", f"{e.__class__.__name__}: {e}")
                await ws.close(4444, reason=f"{e.__class__.__name__}: {e}")
            finally:
                self.connected = False