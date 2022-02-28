# rt-module
RTのBotとバックエンドのプログラムの両方で使うようなものを入れるモジュールです。  
[こちら](https://rt-team.github.io/rt-module)からガバガバですが大体のAPI内容を見れます。

## 使用用途
* RTWS (`rtws`)
  WebSocketを使用して簡単に何か実行するリクエストをするためのものです。  
  rt-backendとrt-botが通信をするためのもので、`get_guild`等のイベントリクエストが可能です。
* その他
  rt-backendとrt-botで使用する型等です。