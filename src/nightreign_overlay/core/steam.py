"""Public Steam identity helpers; never read credentials or initialize SteamAPI."""

from __future__ import annotations


def valid_steam_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 17
        and value.isascii()
        and value.isdigit()
        and 76561197960265728 <= int(value) <= 76561202255233023
    )


def profile_uri(steam_id: str) -> str | None:
    return f"steam://url/SteamIDPage/{steam_id}" if valid_steam_id(steam_id) else None


def current_steam_account() -> str:
    """Read the Steam client's public ActiveUser number, not its login session."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as key:
            account = winreg.QueryValueEx(key, "ActiveUser")[0]
        if type(account) is int and 0 < account <= 0xFFFFFFFF:
            return str(76561197960265728 + account)
    except (ImportError, OSError):
        pass
    return ""
