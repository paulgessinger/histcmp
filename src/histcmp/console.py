from rich.console import Console as RichConsole

from rich.theme import Theme

custom_theme = Theme(
    {"info": "dim cyan", "warning": "yellow", "good": "bold green", "fail": "bold red"}
)

class Console(RichConsole):
    def __init__(self, *args, **kwargs):
        kwargs["theme"] = custom_theme
        super().__init__(*args, **kwargs)

    def info(self, *args, **kwargs):
        self.print(":information:", *args, style="info", **kwargs)


    def fail(self, *args, **kwargs):
        kwargs.setdefault("highlight", False)
        self.print(":stop_sign:", *args, style="fail", **kwargs)


    def good(self,*args, **kwargs):
        kwargs.setdefault("highlight", False)
        self.print(":white_check_mark:", *args, style="good", **kwargs)


    def warn(self, *args, **kwargs):
        kwargs.setdefault("highlight", False)
        self.print(":exclamation:", *args, style="warning", **kwargs)
