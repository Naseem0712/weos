"""Keep Railway-generated URLs attached without serving the application on them."""

from starlette.responses import PlainTextResponse


class BlockRailwayDomainsMiddleware:
    """Reject generated public domains before routes, static files, and CORS.

    Use the actual Host header, never client-supplied X-Forwarded-Host.
    The custom domain and Railway's healthcheck.railway.app are unaffected.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            hosts = [
                value.decode("latin-1").split(":", 1)[0].lower().rstrip(".")
                for key, value in scope.get("headers", [])
                if key.lower() == b"host"
            ]
            if any(host.endswith(".up.railway.app") for host in hosts):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    response = PlainTextResponse(
                        "Forbidden",
                        status_code=403,
                        headers={
                            "X-Robots-Tag": "noindex, nofollow, noarchive",
                            "Cache-Control": "no-store",
                        },
                    )
                    await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
