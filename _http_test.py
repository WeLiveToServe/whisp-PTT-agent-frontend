import threading
import time
from http.client import HTTPConnection

from whisp_server_redline import ThreadingHTTPServer, RequestHandler

server = ThreadingHTTPServer(("127.0.0.1", 8001), RequestHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

conn = HTTPConnection("127.0.0.1", 8001, timeout=10)
conn.request("POST", "/api/record/start")
resp = conn.getresponse()
print("start status", resp.status)
print("start body", resp.read())

conn.request("POST", "/api/record/stop")
resp = conn.getresponse()
print("stop status", resp.status)
body = resp.read()
print("stop body", body)

server.shutdown()
server.server_close()