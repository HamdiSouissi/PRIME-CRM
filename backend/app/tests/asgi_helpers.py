"""In-memory ASGI helpers: no socket, proxy, or hosted service is opened."""


class WithClientIP:
    def __init__(self, app, client_ip: str | None):
        self.app = app
        self.client_ip = client_ip

    async def __call__(self, scope, receive, send):
        if scope.get("type") in {"http", "websocket"}:
            scope = dict(scope)
            scope["client"] = None if self.client_ip is None else (self.client_ip, 12345)
        await self.app(scope, receive, send)
