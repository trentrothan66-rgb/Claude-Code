#include <iostream>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <queue>
#include <deque>
#include <string>
#include <cstdint>
#include <chrono>
#include <fstream>
#include <algorithm>
#include <cstring>

using namespace std;

// Constants
const int FILES = 6;
const int RANKS = 8;
const int WHITE = 0;
const int BLACK = 1;

const int UNKNOWN = 0;
const int WHITE_WIN = 1;
const int BLACK_WIN = 2;
const int DRAW = 3;

const int WHITE_START_RANK = 1;
const int BLACK_START_RANK = 6;
const int WHITE_PROMO_RANK = 7;
const int BLACK_PROMO_RANK = 0;

// Checkpoint filenames
const char* ENUM_CHECKPOINT = "enum_checkpoint.bin";
const char* RETRO_CHECKPOINT = "retro_checkpoint.bin";

// Position structure
struct Position {
    uint64_t white_pawns;
    uint64_t black_pawns;
    int to_move;
    int ep_file;

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
        return -1;
    }

    int count_pawns(int color) const {
        return __builtin_popcountll(color == WHITE ? white_pawns : black_pawns);
    }
};

struct KeyHash {
    size_t operator()(const __uint128_t& key) const {
        return (size_t)(key ^ (key >> 64));
    }
};

struct TablebaseEntry {
    int outcome;
    int distance;
    string best_move;
};

struct Move {
    Position new_pos;
    string notation;
    bool is_promotion;

    Move(const Position& pos, const string& note, bool promo = false)
        : new_pos(pos), notation(note), is_promotion(promo) {}
};

// Forward declarations
vector<Move*> generate_moves(const Position& pos);
pair<bool, int> is_terminal(const Position& pos);

// Checkpoint functions
void save_enumeration_checkpoint(const unordered_set<__uint128_t, KeyHash>& visited,
                                 const deque<__uint128_t>& queue) {
    ofstream out(ENUM_CHECKPOINT, ios::binary);

    // Save visited set
    size_t visited_size = visited.size();
    out.write((char*)&visited_size, sizeof(visited_size));
    for (const auto& key : visited) {
        out.write((char*)&key, sizeof(key));
    }

    // Save queue
    size_t queue_size = queue.size();
    out.write((char*)&queue_size, sizeof(queue_size));
    for (const auto& key : queue) {
        out.write((char*)&key, sizeof(key));
    }

    out.close();
    cout << "  [Checkpoint saved: " << visited_size << " visited, " << queue_size << " in queue]" << endl;
}

bool load_enumeration_checkpoint(unordered_set<__uint128_t, KeyHash>& visited,
                                 deque<__uint128_t>& queue) {
    ifstream in(ENUM_CHECKPOINT, ios::binary);
    if (!in) return false;

    // Load visited set
    size_t visited_size;
    in.read((char*)&visited_size, sizeof(visited_size));
    for (size_t i = 0; i < visited_size; i++) {
        __uint128_t key;
        in.read((char*)&key, sizeof(key));
        visited.insert(key);
    }

    // Load queue
    size_t queue_size;
    in.read((char*)&queue_size, sizeof(queue_size));
    for (size_t i = 0; i < queue_size; i++) {
        __uint128_t key;
        in.read((char*)&key, sizeof(key));
        queue.push_back(key);
    }

    in.close();
    cout << "Resuming from checkpoint: " << visited_size << " visited, " << queue_size << " in queue" << endl;
    return true;
}

void save_retrograde_checkpoint(const unordered_map<__uint128_t, TablebaseEntry, KeyHash>& tablebase,
                                int iteration) {
    ofstream out(RETRO_CHECKPOINT, ios::binary);

    // Save iteration
    out.write((char*)&iteration, sizeof(iteration));

    // Save tablebase
    size_t tb_size = tablebase.size();
    out.write((char*)&tb_size, sizeof(tb_size));

    for (const auto& entry : tablebase) {
        out.write((char*)&entry.first, sizeof(entry.first));
        out.write((char*)&entry.second.outcome, sizeof(entry.second.outcome));
        out.write((char*)&entry.second.distance, sizeof(entry.second.distance));

        size_t move_len = entry.second.best_move.length();
        out.write((char*)&move_len, sizeof(move_len));
        out.write(entry.second.best_move.c_str(), move_len);
    }

    out.close();
    cout << "  [Checkpoint saved: iteration " << iteration << ", " << tb_size << " positions solved]" << endl;
}

bool load_retrograde_checkpoint(unordered_map<__uint128_t, TablebaseEntry, KeyHash>& tablebase,
                                int& iteration) {
    ifstream in(RETRO_CHECKPOINT, ios::binary);
    if (!in) return false;

    // Load iteration
    in.read((char*)&iteration, sizeof(iteration));

    // Load tablebase
    size_t tb_size;
    in.read((char*)&tb_size, sizeof(tb_size));

    for (size_t i = 0; i < tb_size; i++) {
        __uint128_t key;
        TablebaseEntry entry;

        in.read((char*)&key, sizeof(key));
        in.read((char*)&entry.outcome, sizeof(entry.outcome));
        in.read((char*)&entry.distance, sizeof(entry.distance));

        size_t move_len;
        in.read((char*)&move_len, sizeof(move_len));

        char* move_buf = new char[move_len + 1];
        in.read(move_buf, move_len);
        move_buf[move_len] = '\0';
        entry.best_move = string(move_buf);
        delete[] move_buf;

        tablebase[key] = entry;
    }

    in.close();
    cout << "Resuming retrograde analysis from iteration " << iteration
         << " with " << tb_size << " positions solved" << endl;
    return true;
}

// Move generation (same as before, just declarations here)
Move* make_move(const Position& pos, int from_file, int from_rank,
                int to_file, int to_rank, bool double_push);
Move* make_move_ep(const Position& pos, int from_file, int from_rank,
                   int to_file, int to_rank);

Move* make_move(const Position& pos, int from_file, int from_rank,
                int to_file, int to_rank, bool double_push) {
    int color = pos.to_move;
    int promo_rank = (color == WHITE) ? WHITE_PROMO_RANK : BLACK_PROMO_RANK;

    string notation = string(1, 'b' + from_file) + to_string(from_rank + 1) +
                     string(1, 'b' + to_file) + to_string(to_rank + 1);

    if (to_rank == promo_rank) {
        return new Move(pos, notation, true);
    }

    Position new_pos = pos;
    int from_sq = from_rank * FILES + from_file;
    int to_sq = to_rank * FILES + to_file;

    if (color == WHITE) {
        new_pos.white_pawns &= ~(1ULL << from_sq);
        new_pos.white_pawns |= (1ULL << to_sq);
        new_pos.black_pawns &= ~(1ULL << to_sq);
    } else {
        new_pos.black_pawns &= ~(1ULL << from_sq);
        new_pos.black_pawns |= (1ULL << to_sq);
        new_pos.white_pawns &= ~(1ULL << to_sq);
    }

    new_pos.ep_file = double_push ? to_file : -1;
    new_pos.to_move = 1 - color;

    return new Move(new_pos, notation, false);
}

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

vector<Move*> generate_moves(const Position& pos) {
    vector<Move*> moves;
    int color = pos.to_move;
    int direction = (color == WHITE) ? 1 : -1;
    int start_rank = (color == WHITE) ? WHITE_START_RANK : BLACK_START_RANK;

    for (int file = 0; file < FILES; file++) {
        for (int rank = 0; rank < RANKS; rank++) {
            if (pos.get_square(file, rank) != color) continue;

            int new_rank = rank + direction;
            if (new_rank >= 0 && new_rank < RANKS && pos.get_square(file, new_rank) == -1) {
                Move* move = make_move(pos, file, rank, file, new_rank, false);
                if (move) moves.push_back(move);

                if (rank == start_rank && !move->is_promotion) {
                    int new_rank2 = rank + 2 * direction;
                    if (pos.get_square(file, new_rank2) == -1) {
                        Move* move2 = make_move(pos, file, rank, file, new_rank2, true);
                        if (move2) moves.push_back(move2);
                    }
                }
            }

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

pair<bool, int> is_terminal(const Position& pos) {
    int white_count = pos.count_pawns(WHITE);
    int black_count = pos.count_pawns(BLACK);

    if (white_count == 0) return {true, BLACK_WIN};
    if (black_count == 0) return {true, WHITE_WIN};

    for (int file = 0; file < FILES; file++) {
        if (pos.get_square(file, WHITE_PROMO_RANK) == WHITE) return {true, WHITE_WIN};
        if (pos.get_square(file, BLACK_PROMO_RANK) == BLACK) return {true, BLACK_WIN};
    }

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

unordered_set<__uint128_t, KeyHash> enumerate_positions() {
    cout << "Enumerating all reachable positions..." << endl;

    unordered_set<__uint128_t, KeyHash> visited;
    deque<__uint128_t> queue;

    // Try to load checkpoint
    if (load_enumeration_checkpoint(visited, queue)) {
        cout << "Resuming enumeration from checkpoint..." << endl;
    } else {
        // Start fresh
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
        visited.insert(start_key);
        queue.push_back(start_key);
    }

    size_t count = visited.size();
    size_t last_checkpoint = count;
    auto last_report = chrono::steady_clock::now();

    while (!queue.empty()) {
        __uint128_t pos_key = queue.front();
        queue.pop_front();

        Position pos = Position::from_key(pos_key);
        count++;

        // Progress report
        auto now = chrono::steady_clock::now();
        if (chrono::duration_cast<chrono::seconds>(now - last_report).count() >= 5) {
            cout << "  Enumerated " << count << " positions, queue size: " << queue.size() << endl;
            last_report = now;
        }

        // Checkpoint every 1M positions
        if (count - last_checkpoint >= 1000000) {
            save_enumeration_checkpoint(visited, queue);
            last_checkpoint = count;
        }

        // Generate moves
        vector<Move*> moves = generate_moves(pos);
        for (Move* move : moves) {
            if (!move->is_promotion) {
                __uint128_t new_key = move->new_pos.to_key();
                if (visited.find(new_key) == visited.end()) {
                    visited.insert(new_key);
                    queue.push_back(new_key);
                }
            }
            delete move;
        }
    }

    // Final checkpoint
    save_enumeration_checkpoint(visited, queue);

    cout << "Total reachable positions: " << visited.size() << endl;

    // Clean up checkpoint file
    remove(ENUM_CHECKPOINT);

    return visited;
}

unordered_map<__uint128_t, TablebaseEntry, KeyHash> retrograde_analysis(
    const unordered_set<__uint128_t, KeyHash>& all_positions) {

    cout << "\nPerforming retrograde analysis..." << endl;

    unordered_map<__uint128_t, TablebaseEntry, KeyHash> tablebase;
    int iteration = 0;

    // Try to load checkpoint
    if (load_retrograde_checkpoint(tablebase, iteration)) {
        cout << "Resuming retrograde analysis..." << endl;
    } else {
        // Find all terminal positions
        for (const auto& pos_key : all_positions) {
            Position pos = Position::from_key(pos_key);
            auto [is_term, outcome] = is_terminal(pos);
            if (is_term) {
                tablebase[pos_key] = {outcome, 0, ""};
            }
        }
        cout << "Found " << tablebase.size() << " terminal positions" << endl;
    }

    int max_iterations = 200;

    while (iteration < max_iterations) {
        iteration++;
        size_t newly_solved = 0;

        for (const auto& pos_key : all_positions) {
            if (tablebase.find(pos_key) != tablebase.end()) continue;

            Position pos = Position::from_key(pos_key);
            vector<Move*> moves = generate_moves(pos);

            bool all_moves_solved = true;
            vector<tuple<int, int, string>> move_evals;

            for (Move* move : moves) {
                if (move->is_promotion) {
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

            for (auto m : moves) delete m;

            if (!all_moves_solved || move_evals.empty()) continue;

            // Minimax
            auto best = move_evals[0];

            if (pos.to_move == WHITE) {
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

        // Checkpoint after each iteration
        save_retrograde_checkpoint(tablebase, iteration);

        if (newly_solved == 0) break;
    }

    for (const auto& pos_key : all_positions) {
        if (tablebase.find(pos_key) == tablebase.end()) {
            tablebase[pos_key] = {DRAW, 0, ""};
        }
    }

    cout << "Solved " << tablebase.size() << " positions in " << iteration << " iterations" << endl;

    // Clean up checkpoint
    remove(RETRO_CHECKPOINT);

    return tablebase;
}

int main() {
    cout << "============================================================" << endl;
    cout << "Six Pawn Chess - C++ Solver with Checkpointing" << endl;
    cout << "============================================================" << endl;

    auto start_time = chrono::steady_clock::now();

    unordered_set<__uint128_t, KeyHash> all_positions = enumerate_positions();

    auto enum_time = chrono::steady_clock::now();
    auto enum_duration = chrono::duration_cast<chrono::seconds>(enum_time - start_time).count();
    cout << "Enumeration completed in " << enum_duration << " seconds" << endl;

    auto tablebase = retrograde_analysis(all_positions);

    auto retro_time = chrono::steady_clock::now();
    auto retro_duration = chrono::duration_cast<chrono::seconds>(retro_time - enum_time).count();
    cout << "Retrograde analysis completed in " << retro_duration << " seconds" << endl;

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
