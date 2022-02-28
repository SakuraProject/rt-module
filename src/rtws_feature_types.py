# RT - RTWS Feature Types

from __future__ import annotations

from typing import TypedDict, Literal, List


class Snowflake(TypedDict):
    "IDと名前"
    id: int
    name: str


class HasAvatar(Snowflake):
    "アバターを持っているデータの型"
    avatar_url: str


class User(HasAvatar):
    "ユーザーの型"
    full_name: str


class Member(User):
    "メンバーの型"
    guild: Guild


class Channel(Snowflake):
    "チャンネルの型"
    guild: Guild
    type: Literal["text", "voice"]


class Role(Snowflake):
    "ロールの型"
    ...


class Guild(HasAvatar):
    "ギルドの型"
    members: List[Member]
    text_channels: List[Channel]
    voice_channels: List[Channel]
    channels: List[Channel]
    roles: List[Role]