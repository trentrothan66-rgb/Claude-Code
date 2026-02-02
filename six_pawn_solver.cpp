#include <iostream>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <queue>
#include <string>
#include <cstdint>
#include <chrono>
#include <fstream>
#include <algorithm>

using namespace std;

// Constants
const int FILES = 6;  // b through g
const int RANKS = 8;
const int WHITE = 0;
const int BLACK = 1;

// Outcomes
const int UNKNOWN = 0;
const int WHITE_WIN = 1;
const int BLACK_WIN = 2;
const int DRAW = 3;

const int WHITE_START_RANK = 1;
const int BLACK_START_RANK = 6;
const int WHITE_PROMO_RANK = 7;
const int BLACK_PROMO_RANK = 0;

// Position structure using bitboards
struct Position {
    uint64_t white_pawns;  // 48 bits used (6 files × 8 ranks)
    uint64_t black_pawns;  // 48 bits used
    int to_move;           // 0=white, 1=black
    int ep_file;           // -1 or 0-5 for en passant file

    // Encode position as unique key
    __uint128_t to_key() const {
        __uint128_t key = white_pawns;
        key |= ((__uint128_t)black_pawns) << 48;
        key |= ((__uint128_t)to_move) << 96;
        key |= ((__uint128_t)(ep_file + 1)) << 97;
        return key;
    }

    static Position from_key(__uint128_t key) {
        Position pos;
        pos.white_pawns = key & ((1ULL << 48) - 1);
        pos.black_pawns = (key >> 48) & ((1ULL << 48) - 1);
        pos.to_move = (key >> 96) & 1;
        pos.ep_file = ((key >> 97) & 0x7) - 1;
        return pos;
    }

    int get_square(int file, int rank) const {
        int sq = rank * FILES + file;
        if (white_pawns & (1ULL << sq)) return WHITE;
        if (black_pawns & (1ULL << sq)) return BLACK;
        return -1;  // empty
    }

    void set_square(int file, int rank, int piece) {
        int sq = rank * FILES + file;
        uint64_t mask = ~(1ULL << sq);
        white_pawns &= mask;
        black_pawns &= mask;
        if (piece == WHITE) white_pawns |= (1ULL << sq);
        else if (piece == BLACK) black_pawns |= (1ULL << sq);
    }

    int count_pawns(int color) const {
        return __builtin_popcountll(color == WHITE ? white_pawns : black_pawns);
    }
};

// Hash function for __uint128_t
struct KeyHash {
    size_t operator()(const __uint128_t& key) const {
        return (size_t)(key ^ (key >> 64));
    }
};

// Tablebase entry
struct TablebaseEntry {
    int outcome;
    int distance;
    string best_move;
};

// Move structure
struct Move {
    Position new_pos;
    string notation;
    bool is_promotion;

    Move(const Position& pos, const string& note, bool promo = false)
        : new_pos(pos), notation(note), is_promotion(promo) {}
};

// Make a move (returns nullptr if promotion)
Move* make_move(const Position& pos, int from_file, int from_rank,
                int to_file, int to_rank, bool double_push) {
    int color = pos.to_move;
    int promo_rank = (color == WHITE) ? WHITE_PROMO_RANK : BLACK_PROMO_RANK;

    string notation = string(1, 'b' + from_file) + to_string(from_rank + 1) +
                     string(1, 'b' + to_file) + to_string(to_rank + 1);

    // Check for promotion
    if (to_rank == promo_rank) {
        return new Move(pos, notation, true);  // Promotion
    }

    Position new_pos = pos;
    int from_sq = from_rank * FILES + from_file;
    int to_sq = to_rank * FILES + to_file;

    if (color == WHITE) {
        new_pos.white_pawns &= ~(1ULL << from_sq);
        new_pos.white_pawns |= (1ULL << to_sq);
        new_pos.black_pawns &= ~(1ULL << to_sq);  // Capture
    } else {
        new_pos.black_pawns &= ~(1ULL << from_sq);
        new_pos.black_pawns |= (1ULL << to_sq);
        new_pos.white_pawns &= ~(1ULL << to_sq);  // Capture
    }

    new_pos.ep_file = double_push ? to_file : -1;
    new_pos.to_move = 1 - color;

    return new Move(new_pos, notation, false);
}

// Make en passant move
Move* make_move_ep(const Position& pos, int from_file, int from_rank,
                   int to_file, int to_rank) {
    int color = pos.to_move;
    Position new_pos = pos;

    int from_sq = from_rank * FILES + from_file;
    int to_sq = to_rank * FILES + to_file;
    int victim_rank = (color == WHITE) ? 4 : 3;
    int victim_sq = victim_rank * FILES + to_file;

    if (color == WHITE) {
        new_pos.white_pawns &= ~(1ULL << from_sq);
        new_pos.white_pawns |= (1ULL << to_sq);
        new_pos.black_pawns &= ~(1ULL << victim_sq);
    } else {
        new_pos.black_pawns &= ~(1ULL << from_sq);
        new_pos.black_pawns |= (1ULL << to_sq);
        new_pos.white_pawns &= ~(1ULL << victim_sq);
    }

    new_pos.ep_file = -1;
    new_pos.to_move = 1 - color;

    string notation = string(1, 'b' + from_file) + to_string(from_rank + 1) +
                     "x" + string(1, 'b' + to_file) + to_string(to_rank + 1) + "e.p.";
    return new Move(new_pos, notation, false);
}

// Generate all legal moves
vector<Move*> generate_moves(const Position& pos) {
    vector<Move*> moves;
    int color = pos.to_move;
    int direction = (color == WHITE) ? 1 : -1;
    int start_rank = (color == WHITE) ? WHITE_START_RANK : BLACK_START_RANK;

    for (int file = 0; file < FILES; file++) {
        for (int rank = 0; rank < RANKS; rank++) {
            if (pos.get_square(file, rank) != color) continue;

            // Forward one square
            int new_rank = rank + direction;
            if (new_rank >= 0 && new_rank < RANKS && pos.get_square(file, new_rank) == -1) {
                Move* move = make_move(pos, file, rank, file, new_rank, false);
                if (move) moves.push_back(move);

                // Forward two from start rank (only if not promotion)
                if (rank == start_rank && !move->is_promotion) {
                    int new_rank2 = rank + 2 * direction;
                    if (pos.get_square(file, new_rank2) == -1) {
                        Move* move2 = make_move(pos, file, rank, file, new_rank2, true);
                        if (move2) moves.push_back(move2);
                    }
                }
            }

            // Captures
            for (int df : {-1, 1}) {
                int new_file = file + df;
                int new_rank = rank + direction;
                if (new_file >= 0 && new_file < FILES && new_rank >= 0 && new_rank < RANKS) {
                    int target = pos.get_square(new_file, new_rank);
                    if (target != -1 && target != color) {
                        Move* move = make_move(pos, file, rank, new_file, new_rank, false);
                        if (move) moves.push_back(move);
                    }
                }
            }

            // En passant
            if (pos.ep_file >= 0 && pos.ep_file < FILES) {
                if (color == WHITE && rank == 4 && abs(file - pos.ep_file) == 1) {
                    if (pos.get_square(pos.ep_file, 4) == BLACK) {
                        Move* move = make_move_ep(pos, file, rank, pos.ep_file, 5);
                        if (move) moves.push_back(move);
                    }
                } else if (color == BLACK && rank == 3 && abs(file - pos.ep_file) == 1) {
                    if (pos.get_square(pos.ep_file, 3) == WHITE) {
                        Move* move = make_move_ep(pos, file, rank, pos.ep_file, 2);
                        if (move) moves.push_back(move);
                    }
                }
            }
        }
    }

    return moves;
}

// Check if position is terminal
pair<bool, int> is_terminal(const Position& pos) {
    int white_count = pos.count_pawns(WHITE);
    int black_count = pos.count_pawns(BLACK);

    if (white_count == 0) return {true, BLACK_WIN};
    if (black_count == 0) return {true, WHITE_WIN};

    // Check for promotion
    for (int file = 0; file < FILES; file++) {
        if (pos.get_square(file, WHITE_PROMO_RANK) == WHITE) return {true, WHITE_WIN};
        if (pos.get_square(file, BLACK_PROMO_RANK) == BLACK) return {true, BLACK_WIN};
    }

    // Check for stalemate
    vector<Move*> moves = generate_moves(pos);
    bool has_moves = moves.size() > 0;
    for (auto m : moves) delete m;

    if (!has_moves) {
        if (white_count > black_count) return {true, WHITE_WIN};
        if (black_count > white_count) return {true, BLACK_WIN};
        return {true, DRAW};
    }

    return {false, UNKNOWN};
}

// Enumerate all reachable positions
unordered_set<__uint128_t, KeyHash> enumerate_positions() {
    cout << "Enumerating all reachable positions..." << endl;

    // Create starting position
    Position start;
    start.white_pawns = 0;
    start.black_pawns = 0;
    start.to_move = WHITE;
    start.ep_file = -1;

    for (int file = 0; file < FILES; file++) {
        start.white_pawns |= (1ULL << (WHITE_START_RANK * FILES + file));
        start.black_pawns |= (1ULL << (BLACK_START_RANK * FILES + file));
    }

    unordered_set<__uint128_t, KeyHash> visited;
    queue<__uint128_t> q;

    __uint128_t start_key = start.to_key();
    visited.insert(start_key);
    q.push(start_key);

    size_t count = 0;
    auto last_report = chrono::steady_clock::now();

    while (!q.empty()) {
        __uint128_t pos_key = q.front();
        q.pop();

        Position pos = Position::from_key(pos_key);
        count++;

        // Progress report every 5 seconds
        auto now = chrono::steady_clock::now();
        if (chrono::duration_cast<chrono::seconds>(now - last_report).count() >= 5) {
            cout << "  Enumerated " << count << " positions, queue size: " << q.size() << endl;
            last_report = now;
        }

        // Generate moves
        vector<Move*> moves = generate_moves(pos);
        for (Move* move : moves) {
            if (!move->is_promotion) {
                __uint128_t new_key = move->new_pos.to_key();
                if (visited.find(new_key) == visited.end()) {
                    visited.insert(new_key);
                    q.push(new_key);
                }
            }
            delete move;
        }
    }

    cout << "Total reachable positions: " << visited.size() << endl;
    return visited;
}

// Retrograde analysis
unordered_map<__uint128_t, TablebaseEntry, KeyHash> retrograde_analysis(
    const unordered_set<__uint128_t, KeyHash>& all_positions) {

    cout << "\nPerforming retrograde analysis..." << endl;

    unordered_map<__uint128_t, TablebaseEntry, KeyHash> tablebase;

    // Find all terminal positions
    for (const auto& pos_key : all_positions) {
        Position pos = Position::from_key(pos_key);
        auto [is_term, outcome] = is_terminal(pos);
        if (is_term) {
            tablebase[pos_key] = {outcome, 0, ""};
        }
    }

    cout << "Found " << tablebase.size() << " terminal positions" << endl;

    // Iterative solving
    int max_iterations = 200;
    int iteration = 0;

    while (iteration < max_iterations) {
        iteration++;
        size_t newly_solved = 0;

        for (const auto& pos_key : all_positions) {
            if (tablebase.find(pos_key) != tablebase.end()) continue;

            Position pos = Position::from_key(pos_key);

            // Try to solve this position
            vector<Move*> moves = generate_moves(pos);

            bool all_moves_solved = true;
            vector<tuple<int, int, string>> move_evals;

            for (Move* move : moves) {
                if (move->is_promotion) {
                    // Immediate win
                    int outcome = (pos.to_move == WHITE) ? WHITE_WIN : BLACK_WIN;
                    move_evals.push_back({outcome, 1, move->notation});
                } else {
                    __uint128_t new_key = move->new_pos.to_key();
                    auto it = tablebase.find(new_key);
                    if (it != tablebase.end()) {
                        move_evals.push_back({it->second.outcome, it->second.distance + 1, move->notation});
                    } else {
                        all_moves_solved = false;
                        break;
                    }
                }
            }

            // Clean up moves
            for (auto m : moves) delete m;

            if (!all_moves_solved || move_evals.empty()) continue;

            // Apply minimax
            auto best = move_evals[0];

            if (pos.to_move == WHITE) {
                // White maximizes
                for (const auto& eval : move_evals) {
                    auto [outcome, dist, move_str] = eval;
                    auto [best_outcome, best_dist, best_move] = best;

                    if (outcome == WHITE_WIN && best_outcome != WHITE_WIN) {
                        best = eval;
                    } else if (outcome == WHITE_WIN && best_outcome == WHITE_WIN && dist < best_dist) {
                        best = eval;
                    } else if (outcome == DRAW && best_outcome == BLACK_WIN) {
                        best = eval;
                    } else if (outcome == BLACK_WIN && best_outcome == BLACK_WIN && dist > best_dist) {
                        best = eval;
                    }
                }
            } else {
                // Black maximizes
                for (const auto& eval : move_evals) {
                    auto [outcome, dist, move_str] = eval;
                    auto [best_outcome, best_dist, best_move] = best;

                    if (outcome == BLACK_WIN && best_outcome != BLACK_WIN) {
                        best = eval;
                    } else if (outcome == BLACK_WIN && best_outcome == BLACK_WIN && dist < best_dist) {
                        best = eval;
                    } else if (outcome == DRAW && best_outcome == WHITE_WIN) {
                        best = eval;
                    } else if (outcome == WHITE_WIN && best_outcome == WHITE_WIN && dist > best_dist) {
                        best = eval;
                    }
                }
            }

            auto [outcome, dist, move_str] = best;
            tablebase[pos_key] = {outcome, dist, move_str};
            newly_solved++;
        }

        cout << "Iteration " << iteration << ": solved " << newly_solved
             << " new positions, total " << tablebase.size() << "/" << all_positions.size() << endl;

        if (newly_solved == 0) break;
    }

    // Mark any remaining as draws
    for (const auto& pos_key : all_positions) {
        if (tablebase.find(pos_key) == tablebase.end()) {
            tablebase[pos_key] = {DRAW, 0, ""};
        }
    }

    cout << "Solved " << tablebase.size() << " positions in " << iteration << " iterations" << endl;

    return tablebase;
}

int main() {
    cout << "============================================================" << endl;
    cout << "Six Pawn Chess - C++ Retrograde Analysis Solver" << endl;
    cout << "============================================================" << endl;

    auto start_time = chrono::steady_clock::now();

    // Enumerate positions
    unordered_set<__uint128_t, KeyHash> all_positions = enumerate_positions();

    auto enum_time = chrono::steady_clock::now();
    auto enum_duration = chrono::duration_cast<chrono::seconds>(enum_time - start_time).count();
    cout << "Enumeration completed in " << enum_duration << " seconds" << endl;

    // Retrograde analysis
    auto tablebase = retrograde_analysis(all_positions);

    auto retro_time = chrono::steady_clock::now();
    auto retro_duration = chrono::duration_cast<chrono::seconds>(retro_time - enum_time).count();
    cout << "Retrograde analysis completed in " << retro_duration << " seconds" << endl;

    // Analyze starting position
    cout << "\n============================================================" << endl;
    cout << "STARTING POSITION ANALYSIS" << endl;
    cout << "============================================================" << endl;

    Position start;
    start.white_pawns = 0;
    start.black_pawns = 0;
    start.to_move = WHITE;
    start.ep_file = -1;

    for (int file = 0; file < FILES; file++) {
        start.white_pawns |= (1ULL << (WHITE_START_RANK * FILES + file));
        start.black_pawns |= (1ULL << (BLACK_START_RANK * FILES + file));
    }

    __uint128_t start_key = start.to_key();
    auto it = tablebase.find(start_key);

    if (it != tablebase.end()) {
        string outcome_str;
        switch (it->second.outcome) {
            case WHITE_WIN: outcome_str = "White wins"; break;
            case BLACK_WIN: outcome_str = "Black wins"; break;
            case DRAW: outcome_str = "Draw"; break;
            default: outcome_str = "Unknown"; break;
        }

        cout << "Result: " << outcome_str << endl;
        cout << "Distance to terminal: " << it->second.distance << " moves" << endl;
        cout << "Best first move: " << it->second.best_move << endl;
    } else {
        cout << "ERROR: Starting position not in tablebase!" << endl;
    }

    cout << "\n============================================================" << endl;
    cout << "Solver completed successfully!" << endl;
    cout << "============================================================" << endl;

    return 0;
}
