class ScreencapError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}" if message else f"[{code}]")


class ScreencapInitError(ScreencapError):
    pass


class ScreencapRuntimeError(ScreencapError):
    pass
