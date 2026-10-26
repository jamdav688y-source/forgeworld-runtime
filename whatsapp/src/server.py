#!/usr/bin/env python3
"""Minimal live webhook receiver (stdlib only, no framework dependency).

Only meaningful once real Meta credentials/webhook config exist -- until
then this is exercised exclusively through tests/fixtures, never run
against live traffic. Heavier processing (classification, drafting) is
deliberately kept out of the request/response path per mission Section 7.10;
this handler only authenticates, normalizes, and ledgers, then returns 200.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from . import webhook_adapter


class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            challenge = webhook_adapter.verify_challenge(query)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(challenge.encode())
        except webhook_adapter.VerificationError as e:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(str(e).encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length)
        signature = self.headers.get("X-Hub-Signature-256", "")
        result = webhook_adapter.process_webhook_payload(raw_body, signature)
        # Always 200 to Meta per platform contract; the *result* carries the
        # real governance state (BLOCKED_BY_POLICY etc.) into the ledger.
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({"trace_id": result["trace_id"]}).encode())

    def log_message(self, format, *args):
        pass  # avoid leaking request details to stderr; ledger is the audit trail


def run(host="127.0.0.1", port=8443):
    server = HTTPServer((host, port), WebhookHandler)
    print(f"WhatsApp webhook receiver listening on {host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
