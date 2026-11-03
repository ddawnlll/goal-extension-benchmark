#!/usr/bin/env python3
"""Deterministic OpenAI-compatible fixture for the real DSH goal stack.

Not a benchmark model. Start on a host port reachable by the Docker relay.
The first goal round deliberately remains unfinished. The second obtains the
native goal and completes it; `--mode cap` always leaves it unfinished.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = b'{"object":"list","data":[]}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        messages = req.get('messages', [])
        rounds = sum('<goal_round>' in str(m.get('content', '')) for m in messages if m.get('role') == 'user')
        last = messages[-1] if messages else {}
        tool = None
        threshold = 3 if self.server.mode == 'blocked' else 2
        if self.server.mode != 'cap' and rounds >= threshold:
            if last.get('role') == 'tool':
                try:
                    goal = json.loads(last['content'])['goal']
                    args = {'goal_id': goal['id'], 'revision': goal['revision'],
                            'action': 'blocked' if self.server.mode == 'blocked' else 'complete'}
                    if self.server.mode == 'blocked':
                        args['blocked_reason'] = 'Fixture dependency remains unavailable.'
                    tool = ('update_goal', args)
                except (ValueError, KeyError, TypeError):
                    pass
            else:
                tool = ('get_goal', {})
        delta = {'role': 'assistant', 'content': 'OK' if not tool else None}
        finish = 'stop'
        if tool:
            delta['tool_calls'] = [{'index': 0, 'id': 'call_fixture', 'type': 'function',
                                    'function': {'name': tool[0], 'arguments': json.dumps(tool[1])}}]
            finish = 'tool_calls'
        def chunk(delta, reason):
            return {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1,
                    'model': 'deepseek-v4.1-flash',
                    'choices': [{'index': 0, 'delta': delta, 'finish_reason': reason}]}
        payload = ('data: ' + json.dumps(chunk(delta, None)) + '\n\n' +
                   'data: ' + json.dumps(chunk({}, finish)) + '\n\n' + 'data: [DONE]\n\n').encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=19991)
    parser.add_argument('--mode', choices=['complete', 'blocked', 'cap'], default='complete')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('0.0.0.0', args.port), Handler)
    server.mode = args.mode
    server.serve_forever()


if __name__ == '__main__':
    main()
