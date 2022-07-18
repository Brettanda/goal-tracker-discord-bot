from __future__ import annotations

from typing import TypedDict, TYPE_CHECKING


if TYPE_CHECKING:
    class Errors(TypedDict):
        invalid_user: str
        cooldown: str
        no_private_message: str
        overflow: str
        missing_functionality: str

    class InfoInfo(TypedDict):
        title: str
        footer: str
        titles: list[str]

    class InfoLanguages(TypedDict):
        page: str
        list: str

    class Info(TypedDict):
        ping: str
        languages: InfoLanguages
        info: InfoInfo
        invite: str

    class ReminderDelete(TypedDict):
        missing: str
        deleted: str

    class ReminderClear(TypedDict):
        prompt: str
        cancelled: str
        success: str

    class Reminder(TypedDict):
        set: str
        empty: str
        not_found: str
        list_title: str
        delete: ReminderDelete
        clear: ReminderClear


class I18n(TypedDict):
    _lang_name: str
    _lang_emoji: str
    _translator: str
    errors: Errors
    info: Info
    reminder: Reminder
