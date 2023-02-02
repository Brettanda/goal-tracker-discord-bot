from __future__ import annotations

from typing import TypedDict, TYPE_CHECKING
import json


if TYPE_CHECKING:
    class AppCommandParameterDefault(TypedDict):
        name: str
        description: str

    class CommandDefault(TypedDict):
        help: str

    class AppCommandDefaultParameters(CommandDefault, total=False):
        parameters: dict[str, AppCommandParameterDefault]

    class AppCommandDefault(AppCommandDefaultParameters, total=True):
        command_name: str

    class AppCommandGroupDefault(CommandDefault):
        command_name: str
        commands: dict[str, AppCommandDefault]

    class CogDefault(TypedDict):
        cog_description: str

    class Errors(TypedDict):
        invalid_user: str
        cooldown: str
        no_private_message: str
        overflow: str
        missing_functionality: str

    class InfoPing(AppCommandDefault):
        response: str

    class InfoInfo(TypedDict):
        title: str
        footer: str
        titles: list[str]

    class InfoLanguages(AppCommandDefault):
        page: str
        list: str

    class Info(TypedDict):
        ping: InfoPing
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

    class Reminder(CogDefault):
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


en: I18n = {
    "_lang_name": "English",
    "_lang_emoji": "🇺🇸",
    "_translator": "Motostar#0001",
    "errors": {
        "invalid_user": "Invalid user. Please mention a user or provide a user ID.",
        "cooldown": "This command is on a cooldown, and will be available in `{}` or <t:{}:R>",
        "no_private_message": "This command does not work in non-server text channels",
        "overflow": "An arguments number is too large.",
        "missing_functionality": "Sorry, this functionality is currently unavailable. Try again later?"
    },
    "info": {
        "ping": {
            "command_name": "ping",
            "help": "Pong!",
            "response": "Ping!\n⏳ API is {}ms"
        },
        "languages": {
            "command_name": "languages",
            "help": "Get a list of languages I support",
            "page": "Crowdin Page",
            "list": "{} has localization support for the following languages: \n```\n{}\n```If you don't see your native language in this list you can contribute on the Crowdin page.\nIf supported the language that I speak will match your Discord language settings."
        },
        "info": {
            "title": "{} - About",
            "footer": "Made with ❤️ and discord.py!",
            "titles": [
                "Servers joined",
                "Latency",
                "Shards",
                "Uptime",
                "CPU/RAM",
                "Existed since"
            ]
        },
        "invite": "Invite me :)"
    },
    "reminder": {
        "cog_description": "Set reminders for yourself",
        "set": "Reminder set {}\n{}",
        "empty": "You have no reminders.",
        "not_found": "No reminder found",
        "list_title": "Reminders",
        "delete": {
            "missing": "You have no reminder with that ID.",
            "deleted": "Reminder deleted."
        },
        "clear": {
            "prompt": "Are you sure you want to delete {}?",
            "cancelled": "Cancelled.",
            "success": "Successfully deleted {}."
        }
    }
}

dump = json.dumps(en, indent=2)

with open("./i18n/locales/en/main.json", "w") as f:
    f.write(dump)
