#!/usr/bin/env python3
"""Local preview with Vercel-style clean URLs (/explorer -> explorer.html).

    python scripts/dev_server.py [port]      # default 8787
"""
import http.server
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def send_head(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path != "/" and not os.path.splitext(path)[1]:
            candidate = os.path.join(ROOT, path.strip("/") + ".html")
            if os.path.isfile(candidate):
                self.path = path.rstrip("/") + ".html" + self.path[len(path):]
        return super().send_head()

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print("ZycaScan preview on http://localhost:%d" % port, flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
