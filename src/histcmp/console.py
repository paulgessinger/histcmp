from rich.console import Console

from rich.theme import Theme

custom_theme = Theme(
    {"info": "dim cyan", "warning": "yellow", "good": "bold green", "fail": "bold red"}
)
console = Console(theme=custom_theme)


def info(*args, **kwargs):
    console.print(":information:", *args, style="info", **kwargs)


def fail(*args, **kwargs):
    kwargs.setdefault("highlight", False)
    console.print(":stop_sign:", *args, style="fail", **kwargs)


def good(*args, **kwargs):
    kwargs.setdefault("highlight", False)
    console.print(":white_check_mark:", *args, style="good", **kwargs)


def warn(*args, **kwargs):
    kwargs.setdefault("highlight", False)
    console.print(":exclamation:", *args, style="warning", **kwargs)
