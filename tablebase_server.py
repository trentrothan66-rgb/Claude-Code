#!/usr/bin/env python3
"""
Tablebase Server for Six Pawn Chess

Serves tablebase lookups over HTTP for the web UI.
"""

import pickle
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import os

# Import position encoding from solver
from six_pawn_solver import Position, WHITE, BLACK, WHITE_WIN, BLACK_WIN, DRAW, FILES


class TablebaseHandler(BaseHTTPRequestHandler):
    """HTTP request handler for tablebase lookups."""

    tablebase = None

    def do_GET(self):
        """Handle GET requests."""
        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == '/':
            # Serve the HTML file
            self.serve_html()
        elif path == '/lookup':
            # Lookup position in tablebase
            self.lookup_position(parsed_path.query)
        elif path == '/stats':
            # Return tablebase statistics
            self.get_stats()
        else:
            self.send_error(404, 'Not Found')

    def do_POST(self):
        """Handle POST requests."""
        if self.path == '/lookup':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            self.lookup_position_post(data)
        else:
            self.send_error(404, 'Not Found')

    def serve_html(self):
        """Serve the game HTML file."""
        try:
            with open('six_pawn_game.html', 'rb') as f:
                content = f.read()

            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_error(404, 'HTML file not found')

    def lookup_position(self, query_string):
        """Lookup a position in the tablebase via GET."""
        params = parse_qs(query_string)

        try:
            # Parse position from query parameters
            white_pawns = int(params.get('white', [0])[0])
            black_pawns = int(params.get('black', [0])[0])
            to_move = int(params.get('to_move', [0])[0])
            ep_file = int(params.get('ep_file', [-1])[0])

            result = self.do_lookup(white_pawns, black_pawns, to_move, ep_file)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        except Exception as e:
            self.send_error(500, str(e))

    def lookup_position_post(self, data):
        """Lookup a position in the tablebase via POST."""
        try:
            # Parse board position
            board = data.get('board')
            to_move = data.get('to_move')
            ep_file = data.get('ep_file', -1)

            # Encode board to position
            white_pawns = 0
            black_pawns = 0

            for rank in range(8):
                for file in range(8):
                    piece = board[rank][file]
                    if piece == 0:  # WHITE
                        sq = rank * FILES + (file - 1)  # Adjust for b-g files
                        if 0 <= sq < 48:
                            white_pawns |= (1 << sq)
                    elif piece == 1:  # BLACK
                        sq = rank * FILES + (file - 1)
                        if 0 <= sq < 48:
                            black_pawns |= (1 << sq)

            result = self.do_lookup(white_pawns, black_pawns, to_move, ep_file)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        except Exception as e:
            print(f"Error in lookup_position_post: {e}")
            self.send_error(500, str(e))

    def do_lookup(self, white_pawns, black_pawns, to_move, ep_file):
        """Perform the actual tablebase lookup."""
        if TablebaseHandler.tablebase is None:
            return {
                'error': 'Tablebase not loaded',
                'outcome': 'unknown',
                'distance': 0,
                'best_move': None
            }

        pos = Position(white_pawns, black_pawns, to_move, ep_file)
        pos_key = pos.to_key()

        if pos_key in TablebaseHandler.tablebase:
            outcome, distance, best_move = TablebaseHandler.tablebase[pos_key]

            outcome_str = {
                WHITE_WIN: 'white_win',
                BLACK_WIN: 'black_win',
                DRAW: 'draw'
            }.get(outcome, 'unknown')

            return {
                'outcome': outcome_str,
                'distance': distance,
                'best_move': best_move,
                'found': True
            }
        else:
            return {
                'outcome': 'unknown',
                'distance': 0,
                'best_move': None,
                'found': False
            }

    def get_stats(self):
        """Return tablebase statistics."""
        if TablebaseHandler.tablebase is None:
            stats = {
                'loaded': False,
                'positions': 0
            }
        else:
            stats = {
                'loaded': True,
                'positions': len(TablebaseHandler.tablebase),
                'size_mb': os.path.getsize('six_pawn_tablebase.pkl') / (1024 * 1024)
                           if os.path.exists('six_pawn_tablebase.pkl') else 0
            }

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(stats).encode())

    def log_message(self, format, *args):
        """Override to customize logging."""
        print(f"[{self.address_string()}] {format % args}")


def load_tablebase(filename):
    """Load the tablebase from disk."""
    print(f"Loading tablebase from {filename}...")
    try:
        with open(filename, 'rb') as f:
            tablebase = pickle.load(f)
        print(f"Loaded {len(tablebase):,} positions")
        return tablebase
    except FileNotFoundError:
        print(f"Warning: Tablebase file {filename} not found")
        return None
    except Exception as e:
        print(f"Error loading tablebase: {e}")
        return None


def main():
    """Start the tablebase server."""
    print("=" * 60)
    print("Six Pawn Chess - Tablebase Server")
    print("=" * 60)

    # Load tablebase
    TablebaseHandler.tablebase = load_tablebase('six_pawn_tablebase.pkl')

    # Start server
    port = 8000
    server = HTTPServer(('localhost', port), TablebaseHandler)

    print(f"\nServer running on http://localhost:{port}/")
    print("Press Ctrl+C to stop\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.shutdown()


if __name__ == '__main__':
    main()
