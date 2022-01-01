# RT - RTC Feature Types

from __future__ import annotations

from typing import TypedDict, Literal, List


class Snowflake(TypedDict):
    id: int
    name: str


class HasAvatar(Snowflake):
    avatar_url: str


class User(HasAvatar):
    full_name: str


class Member(User):
    guild: Guild


class Channel(Snowflake):
    guild: Guild
    type: Literal["text", "voice"]


class Guild(HasAvatar):
    members: List[Member]
    text_channels: List[Channel]
    voice_channels: List[Channel]
    channels: List[Channel]