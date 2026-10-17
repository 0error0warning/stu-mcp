"""Loopback transport shared by the two local pages; startup never needs DNS."""
from http.server import ThreadingHTTPServer
from socketserver import TCPServer


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind performs getfqdn(), which can block indefinitely
        # in macOS name resolution. Both callers bind a literal loopback address.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]
