"""Run with python -m unittest WEOS.test_domain_access."""

import unittest

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from WEOS.api.domain_access import BlockRailwayDomainsMiddleware


async def page(request):
    return PlainTextResponse("application content")


async def socket(websocket):
    await websocket.accept()
    await websocket.send_text("application content")


class DomainAccessTests(unittest.TestCase):
    def setUp(self):
        app = Starlette(routes=[Route("/{path:path}", page), WebSocketRoute("/ws", socket)])
        app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])
        app.add_middleware(BlockRailwayDomainsMiddleware)
        self.client = TestClient(app)

    def test_generated_domains_block_all_paths_and_methods(self):
        for host in ("weos.up.railway.app", "web-production-71845.up.railway.app",
                     "WEOS.UP.RAILWAY.APP.:443"):
            for path in ("/", "/api/projects", "/assets/app.js", "/health", "/robots.txt"):
                for method in ("GET", "HEAD", "POST", "OPTIONS"):
                    with self.subTest(host=host, path=path, method=method):
                        response = self.client.request(method, path, headers={
                            "host": host, "x-forwarded-host": "weos.allukraft.com",
                            "origin": "https://weos.allukraft.com",
                            "access-control-request-method": "POST",
                        })
                        self.assertEqual(response.status_code, 403)
                        self.assertIn("noindex", response.headers["x-robots-tag"])
                        self.assertNotIn("application content", response.text)
                        self.assertNotIn("location", response.headers)

    def test_custom_domain_local_development_and_healthcheck(self):
        for host in ("weos.allukraft.com", "localhost:8000", "127.0.0.1:8000",
                     "testserver", "healthcheck.railway.app"):
            response = self.client.get("/health", headers={"host": host})
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("x-robots-tag", response.headers)

    def test_generated_domain_websocket_is_blocked(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect("/ws", headers={"host": "weos.up.railway.app"}):
                self.fail("Blocked host accepted a websocket")


if __name__ == "__main__":
    unittest.main()
