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
#include <iomanip>

using namespace std;

// ============================================================
// CONSTANTS
// ============================================================

const int FILES = 6;  // Files b-g (0-5)
const int RANKS = 8;  // Ranks 1-8 (0-7)

// Win conditions
const int8_t RESULT_UNKNOWN = 127;
const int8_t RESULT_DRAW = 0;
const int8_t RESULT_WHITE_WIN = 1;
const int8_t RESULT_BLACK_WIN = -1;

// Starting ranks (0-indexed)
const int WHITE_START_RANK = 1;  // Rank 2
const int BLACK_START_RANK = 6;  // Rank 7
const int WHITE_PROMO_RANK = 7;  // Rank 8
const int BLACK_PROMO_RANK = 0;  // Rank 1

// File names
const char* CANONICAL_POSITIONS_FILE = "canonical_positions.bin";
const char* TABLEBASE_FILE = "tablebase.bin";
const char* POSITION_CHECKPOINT_FILE = "position_gen_checkpoint.bin";

// ============================================================
// POSITION STRUCTURE
// ============================================================

struct Position {
    uint64_t white_pawns;  // Bitboard for white pawns
    uint64_t black_pawns;  // Bitboard for black pawns
    bool white_to_move;
    int8_t en_passant_file;  // -1 if no en passant available

    Position() : white_pawns(0), black_pawns(0), white_to_move(true), en_passant_file(-1) {}

    // Get square index for file/rank
    static inline int square(int file, int rank) {
        return rank * FILES + file;
    }

    // Check if square has a piece
    int get_piece(int file, int rank) const {
        int sq = square(file, rank);
        if (white_pawns & (1ULL << sq)) return 0;  // White
        if (black_pawns & (1ULL << sq)) return 1;  // Black
        return -1;  // Empty
    }

    // Count pawns
    int count_pawns(bool white) const {
        return __builtin_popcountll(white ? white_pawns : black_pawns);
    }

    // Horizontal flip symmetry
    Position horizontal_flip() const {
        Position flipped;
        flipped.white_to_move = white_to_move;
        flipped.en_passant_file = (en_passant_file >= 0) ? (FILES - 1 - en_passant_file) : -1;

        // Flip each pawn's file position
        for (int rank = 0; rank < RANKS; rank++) {
            for (int file = 0; file < FILES; file++) {
                int sq = square(file, rank);
                int flipped_file = FILES - 1 - file;
                int flipped_sq = square(flipped_file, rank);

                if (white_pawns & (1ULL << sq)) {
                    flipped.white_pawns |= (1ULL << flipped_sq);
                }
                if (black_pawns & (1ULL << sq)) {
                    flipped.black_pawns |= (1ULL << flipped_sq);
                }
            }
        }

        return flipped;
    }

    // Get canonical form (lexicographically smallest)
    Position canonical() const {
        Position flipped = horizontal_flip();

        // Compare as 128-bit keys
        if (white_pawns < flipped.white_pawns) return *this;
        if (white_pawns > flipped.white_pawns) return flipped;

        if (black_pawns < flipped.black_pawns) return *this;
        if (black_pawns > flipped.black_pawns) return flipped;

        if (!white_to_move && flipped.white_to_move) return *this;
        if (white_to_move && !flipped.white_to_move) return flipped;

        if (en_passant_file < flipped.en_passant_file) return *this;
        return flipped;
    }

    // Convert to 128-bit key for hashing
    __uint128_t to_key() const {
        __uint128_t key = white_pawns;
        key |= ((__uint128_t)black_pawns) << 48;
        key |= ((__uint128_t)(white_to_move ? 1 : 0)) << 96;
        key |= ((__uint128_t)(en_passant_file + 1)) << 97;
        return key;
    }

    // Create position from key
    static Position from_key(__uint128_t key) {
        Position pos;
        pos.white_pawns = key & ((1ULL << 48) - 1);
        pos.black_pawns = (key >> 48) & ((1ULL << 48) - 1);
        pos.white_to_move = ((key >> 96) & 1) != 0;
        pos.en_passant_file = ((key >> 97) & 0x7) - 1;
        return pos;
    }

    bool operator==(const Position& other) const {
        return white_pawns == other.white_pawns &&
               black_pawns == other.black_pawns &&
               white_to_move == other.white_to_move &&
               en_passant_file == other.en_passant_file;
    }
};

// Hash function for positions
struct KeyHash {
    size_t operator()(const __uint128_t& key) const {
        return (size_t)(key ^ (key >> 64));
    }
};

// ============================================================
// MOVE STRUCTURE
// ============================================================

struct Move {
    int from_file, from_rank;
    int to_file, to_rank;
    bool is_capture;
    bool is_en_passant;
    int en_passant_square;  // Square where captured pawn was

    Move() : from_file(-1), from_rank(-1), to_file(-1), to_rank(-1),
             is_capture(false), is_en_passant(false), en_passant_square(-1) {}

    string to_notation() const {
        string notation;
        notation += char('b' + from_file);
        notation += char('1' + from_rank);
        if (is_capture) notation += 'x';
        notation += char('b' + to_file);
        notation += char('1' + to_rank);
        if (is_en_passant) notation += "e.p.";
        return notation;
    }
};

// ============================================================
// EVALUATION STRUCTURE
// ============================================================

struct Evaluation {
    int8_t result;      // 1=white wins, -1=black wins, 0=draw, 127=unknown
    uint8_t depth;      // Distance to terminal position

    Evaluation() : result(RESULT_UNKNOWN), depth(0) {}
    Evaluation(int8_t r, uint8_t d) : result(r), depth(d) {}
};

// ============================================================
// MOVE GENERATION
// ============================================================

vector<Move> generate_moves(const Position& pos) {
    vector<Move> moves;
    bool is_white = pos.white_to_move;
    int direction = is_white ? 1 : -1;
    int start_rank = is_white ? WHITE_START_RANK : BLACK_START_RANK;
    int promo_rank = is_white ? WHITE_PROMO_RANK : BLACK_PROMO_RANK;

    // Iterate through all pawns of current color
    for (int file = 0; file < FILES; file++) {
        for (int rank = 0; rank < RANKS; rank++) {
            int piece = pos.get_piece(file, rank);
            if (piece == -1) continue;
            if ((piece == 0) != is_white) continue;  // Not our pawn

            // Forward 1 square
            int new_rank = rank + direction;
            if (new_rank >= 0 && new_rank < RANKS) {
                if (pos.get_piece(file, new_rank) == -1) {
                    // Don't include promotions in forward search
                    if (new_rank != promo_rank) {
                        Move move;
                        move.from_file = file;
                        move.from_rank = rank;
                        move.to_file = file;
                        move.to_rank = new_rank;
                        move.is_capture = false;
                        moves.push_back(move);
                    }

                    // Forward 2 squares from starting position
                    if (rank == start_rank && new_rank != promo_rank) {
                        int new_rank2 = rank + 2 * direction;
                        if (new_rank2 >= 0 && new_rank2 < RANKS &&
                            pos.get_piece(file, new_rank2) == -1) {
                            Move move;
                            move.from_file = file;
                            move.from_rank = rank;
                            move.to_file = file;
                            move.to_rank = new_rank2;
                            move.is_capture = false;
                            moves.push_back(move);
                        }
                    }
                }

                // Diagonal captures
                for (int df : {-1, 1}) {
                    int new_file = file + df;
                    if (new_file >= 0 && new_file < FILES) {
                        int target = pos.get_piece(new_file, new_rank);
                        if (target != -1 && (target == 0) != is_white) {
                            // Enemy piece - don't include promotions
                            if (new_rank != promo_rank) {
                                Move move;
                                move.from_file = file;
                                move.from_rank = rank;
                                move.to_file = new_file;
                                move.to_rank = new_rank;
                                move.is_capture = true;
                                moves.push_back(move);
                            }
                        }
                    }
                }
            }

            // En passant captures
            if (pos.en_passant_file >= 0) {
                int ep_file = pos.en_passant_file;
                if (is_white && rank == 4) {  // White on rank 5 (0-indexed rank 4)
                    if (abs(file - ep_file) == 1) {
                        // Check if enemy pawn is on rank 5
                        if (pos.get_piece(ep_file, 4) == 1) {  // Black pawn
                            Move move;
                            move.from_file = file;
                            move.from_rank = 4;
                            move.to_file = ep_file;
                            move.to_rank = 5;
                            move.is_capture = true;
                            move.is_en_passant = true;
                            move.en_passant_square = Position::square(ep_file, 4);
                            moves.push_back(move);
                        }
                    }
                } else if (!is_white && rank == 3) {  // Black on rank 4 (0-indexed rank 3)
                    if (abs(file - ep_file) == 1) {
                        // Check if enemy pawn is on rank 4
                        if (pos.get_piece(ep_file, 3) == 0) {  // White pawn
                            Move move;
                            move.from_file = file;
                            move.from_rank = 3;
                            move.to_file = ep_file;
                            move.to_rank = 2;
                            move.is_capture = true;
                            move.is_en_passant = true;
                            move.en_passant_square = Position::square(ep_file, 3);
                            moves.push_back(move);
                        }
                    }
                }
            }
        }
    }

    return moves;
}

// Apply move to position
Position apply_move(const Position& pos, const Move& move) {
    Position new_pos = pos;

    int from_sq = Position::square(move.from_file, move.from_rank);
    int to_sq = Position::square(move.to_file, move.to_rank);

    // Move the pawn
    if (pos.white_to_move) {
        new_pos.white_pawns &= ~(1ULL << from_sq);
        new_pos.white_pawns |= (1ULL << to_sq);
        // Remove captured piece
        new_pos.black_pawns &= ~(1ULL << to_sq);
        if (move.is_en_passant) {
            new_pos.black_pawns &= ~(1ULL << move.en_passant_square);
        }
    } else {
        new_pos.black_pawns &= ~(1ULL << from_sq);
        new_pos.black_pawns |= (1ULL << to_sq);
        // Remove captured piece
        new_pos.white_pawns &= ~(1ULL << to_sq);
        if (move.is_en_passant) {
            new_pos.white_pawns &= ~(1ULL << move.en_passant_square);
        }
    }

    // Set en passant file if double push
    if (abs(move.to_rank - move.from_rank) == 2) {
        new_pos.en_passant_file = move.to_file;
    } else {
        new_pos.en_passant_file = -1;
    }

    new_pos.white_to_move = !pos.white_to_move;
    return new_pos;
}

// Check if position is terminal and return result
pair<bool, int8_t> is_terminal(const Position& pos) {
    int white_count = pos.count_pawns(true);
    int black_count = pos.count_pawns(false);

    // Check for extinction
    if (white_count == 0) return {true, RESULT_BLACK_WIN};
    if (black_count == 0) return {true, RESULT_WHITE_WIN};

    // Check for promotion
    for (int file = 0; file < FILES; file++) {
        if (pos.get_piece(file, WHITE_PROMO_RANK) == 0) return {true, RESULT_WHITE_WIN};
        if (pos.get_piece(file, BLACK_PROMO_RANK) == 1) return {true, RESULT_BLACK_WIN};
    }

    // Check for stalemate (no legal moves)
    vector<Move> moves = generate_moves(pos);
    if (moves.empty()) {
        if (white_count > black_count) return {true, RESULT_WHITE_WIN};
        if (black_count > white_count) return {true, RESULT_BLACK_WIN};
        return {true, RESULT_DRAW};
    }

    return {false, RESULT_UNKNOWN};
}

// ============================================================
// CHECKPOINT FUNCTIONS
// ============================================================

void save_position_checkpoint(const unordered_set<__uint128_t, KeyHash>& canonical_positions,
                               const deque<__uint128_t>& queue,
                               size_t total_visited) {
    ofstream out(POSITION_CHECKPOINT_FILE, ios::binary);

    // Save total visited count
    out.write((char*)&total_visited, sizeof(total_visited));

    // Save canonical positions
    size_t count = canonical_positions.size();
    out.write((char*)&count, sizeof(count));
    for (const __uint128_t& key : canonical_positions) {
        out.write((char*)&key, sizeof(key));
    }

    // Save queue
    size_t queue_size = queue.size();
    out.write((char*)&queue_size, sizeof(queue_size));
    for (const __uint128_t& key : queue) {
        out.write((char*)&key, sizeof(key));
    }

    out.close();
}

bool load_position_checkpoint(unordered_set<__uint128_t, KeyHash>& canonical_positions,
                               deque<__uint128_t>& queue,
                               size_t& total_visited) {
    ifstream in(POSITION_CHECKPOINT_FILE, ios::binary);
    if (!in) return false;

    // Load total visited count
    in.read((char*)&total_visited, sizeof(total_visited));

    // Load canonical positions
    size_t count;
    in.read((char*)&count, sizeof(count));
    for (size_t i = 0; i < count; i++) {
        __uint128_t key;
        in.read((char*)&key, sizeof(key));
        canonical_positions.insert(key);
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
    cout << "Loaded checkpoint: " << count << " canonical positions, "
         << queue_size << " in queue, " << total_visited << " total visited" << endl;
    return true;
}

// ============================================================
// POSITION GENERATION (MEMORY OPTIMIZED)
// ============================================================

unordered_set<__uint128_t, KeyHash> enumerate_positions() {
    cout << "\n============================================================" << endl;
    cout << "POSITION GENERATION (Forward BFS with Checkpointing)" << endl;
    cout << "============================================================\n" << endl;

    unordered_set<__uint128_t, KeyHash> canonical_positions;
    deque<__uint128_t> queue;  // Store keys instead of Position structs
    size_t total_visited = 0;

    // Try to load checkpoint
    if (load_position_checkpoint(canonical_positions, queue, total_visited)) {
        cout << "Resuming from checkpoint...\n" << endl;
    } else {
        // Initial position
        Position start;
        start.white_to_move = true;
        start.en_passant_file = -1;
        for (int file = 0; file < FILES; file++) {
            start.white_pawns |= (1ULL << Position::square(file, WHITE_START_RANK));
            start.black_pawns |= (1ULL << Position::square(file, BLACK_START_RANK));
        }

        Position start_canonical = start.canonical();
        __uint128_t start_key = start_canonical.to_key();

        canonical_positions.insert(start_key);
        queue.push_back(start_key);
        total_visited = 1;
    }

    auto start_time = chrono::steady_clock::now();
    auto last_report = start_time;
    auto last_checkpoint = start_time;
    size_t checkpoint_counter = canonical_positions.size();

    while (!queue.empty()) {
        __uint128_t pos_key = queue.front();
        queue.pop_front();

        Position pos = Position::from_key(pos_key);

        // Progress report every 5 seconds
        auto now = chrono::steady_clock::now();
        if (chrono::duration_cast<chrono::seconds>(now - last_report).count() >= 5) {
            auto elapsed = chrono::duration_cast<chrono::seconds>(now - start_time).count();
            double ratio = (double)canonical_positions.size() / total_visited;
            cout << "  Canonical: " << canonical_positions.size()
                 << " | Total visited: " << total_visited
                 << " | Queue: " << queue.size()
                 << " | Compression: " << fixed << setprecision(2) << ratio
                 << " | Time: " << elapsed << "s" << endl;
            last_report = now;
        }

        // Checkpoint every 1M canonical positions
        if (canonical_positions.size() - checkpoint_counter >= 1000000) {
            auto elapsed = chrono::duration_cast<chrono::seconds>(now - start_time).count();
            cout << "  [Checkpoint at " << canonical_positions.size()
                 << " positions, " << elapsed << "s]" << endl;
            save_position_checkpoint(canonical_positions, queue, total_visited);
            checkpoint_counter = canonical_positions.size();
            last_checkpoint = now;
        }

        // Generate all legal moves
        vector<Move> moves = generate_moves(pos);
        for (const Move& move : moves) {
            Position new_pos = apply_move(pos, move);
            Position canonical = new_pos.canonical();
            __uint128_t canonical_key = canonical.to_key();

            // Check if we've seen this canonical position before
            if (canonical_positions.find(canonical_key) == canonical_positions.end()) {
                canonical_positions.insert(canonical_key);
                queue.push_back(canonical_key);
            }

            total_visited++;
        }
    }

    // Final checkpoint
    save_position_checkpoint(canonical_positions, queue, total_visited);

    auto end_time = chrono::steady_clock::now();
    auto duration = chrono::duration_cast<chrono::seconds>(end_time - start_time).count();

    cout << "\nPosition generation complete:" << endl;
    cout << "  Canonical positions: " << canonical_positions.size() << endl;
    cout << "  Total positions generated: " << total_visited << endl;
    cout << "  Compression ratio: " << fixed << setprecision(2)
         << (double)canonical_positions.size() / total_visited << endl;
    cout << "  Time: " << duration << " seconds (" << (duration/60) << " minutes)" << endl;

    // Clean up checkpoint file
    remove(POSITION_CHECKPOINT_FILE);

    return canonical_positions;
}

// ============================================================
// RETROGRADE ANALYSIS
// ============================================================

unordered_map<__uint128_t, Evaluation, KeyHash> retrograde_analysis(
    const unordered_set<__uint128_t, KeyHash>& canonical_positions) {

    cout << "\n============================================================" << endl;
    cout << "RETROGRADE ANALYSIS" << endl;
    cout << "============================================================\n" << endl;

    unordered_map<__uint128_t, Evaluation, KeyHash> tablebase;
    unordered_map<__uint128_t, vector<__uint128_t>, KeyHash> predecessors;
    unordered_map<__uint128_t, int, KeyHash> successor_count;
    queue<__uint128_t> eval_queue;

    auto start_time = chrono::steady_clock::now();

    // Step 1: Initialize tablebase and build predecessor graph
    cout << "Building predecessor graph..." << endl;
    size_t terminal_count = 0;
    size_t pos_count = 0;
    auto last_report = start_time;

    for (const __uint128_t& pos_key : canonical_positions) {
        Position pos = Position::from_key(pos_key);
        tablebase[pos_key] = Evaluation();

        // Check if terminal
        auto [is_term, result] = is_terminal(pos);
        if (is_term) {
            tablebase[pos_key] = Evaluation(result, 0);
            eval_queue.push(pos_key);
            terminal_count++;
        } else {
            // Generate successors and build predecessor links
            vector<Move> moves = generate_moves(pos);
            successor_count[pos_key] = moves.size();

            for (const Move& move : moves) {
                Position new_pos = apply_move(pos, move);
                Position new_canonical = new_pos.canonical();
                __uint128_t new_key = new_canonical.to_key();

                predecessors[new_key].push_back(pos_key);
            }
        }

        pos_count++;
        auto now = chrono::steady_clock::now();
        if (pos_count % 100000 == 0 && chrono::duration_cast<chrono::seconds>(now - last_report).count() >= 3) {
            cout << "  Processed " << pos_count << "/" << canonical_positions.size() << " positions" << endl;
            last_report = now;
        }
    }

    cout << "  Terminal positions: " << terminal_count << endl;
    cout << "  Non-terminal positions: " << (canonical_positions.size() - terminal_count) << endl;

    // Step 2: Propagate evaluations backward
    cout << "\nPropagating evaluations backward..." << endl;
    size_t evaluated = terminal_count;
    size_t last_report_count = evaluated;
    auto last_report_time = chrono::steady_clock::now();

    while (!eval_queue.empty()) {
        __uint128_t current_key = eval_queue.front();
        eval_queue.pop();

        Evaluation current_eval = tablebase[current_key];

        // Check all predecessors
        if (predecessors.find(current_key) != predecessors.end()) {
            for (__uint128_t pred_key : predecessors[current_key]) {
                if (tablebase[pred_key].result != RESULT_UNKNOWN) continue;

                // Decrement successor count
                successor_count[pred_key]--;

                // If all successors evaluated, evaluate this position
                if (successor_count[pred_key] == 0) {
                    Position pred_pos = Position::from_key(pred_key);
                    vector<Move> moves = generate_moves(pred_pos);

                    // Find best move (minimax)
                    int8_t best_result = (pred_pos.white_to_move ? -2 : 2);
                    uint8_t best_depth = 255;

                    for (const Move& move : moves) {
                        Position next_pos = apply_move(pred_pos, move);
                        Position next_canonical = next_pos.canonical();
                        __uint128_t next_key = next_canonical.to_key();

                        Evaluation next_eval = tablebase[next_key];
                        int8_t result = next_eval.result;
                        uint8_t depth = next_eval.depth + 1;

                        bool better = false;
                        if (pred_pos.white_to_move) {
                            // White wants to maximize
                            if (result > best_result) better = true;
                            else if (result == best_result && result == RESULT_WHITE_WIN && depth < best_depth) better = true;
                            else if (result == best_result && result != RESULT_WHITE_WIN && depth > best_depth) better = true;
                        } else {
                            // Black wants to minimize
                            if (result < best_result) better = true;
                            else if (result == best_result && result == RESULT_BLACK_WIN && depth < best_depth) better = true;
                            else if (result == best_result && result != RESULT_BLACK_WIN && depth > best_depth) better = true;
                        }

                        if (better) {
                            best_result = result;
                            best_depth = depth;
                        }
                    }

                    tablebase[pred_key] = Evaluation(best_result, best_depth);
                    eval_queue.push(pred_key);
                    evaluated++;

                    // Progress report every 50k evaluations
                    if (evaluated - last_report_count >= 50000) {
                        auto now = chrono::steady_clock::now();
                        auto elapsed = chrono::duration_cast<chrono::seconds>(now - start_time).count();
                        cout << "  Evaluated: " << evaluated << "/" << canonical_positions.size()
                             << " | Queue: " << eval_queue.size()
                             << " | Time: " << elapsed << "s" << endl;
                        last_report_count = evaluated;
                    }
                }
            }
        }
    }

    auto end_time = chrono::steady_clock::now();
    auto duration = chrono::duration_cast<chrono::seconds>(end_time - start_time).count();

    cout << "\nRetrograde analysis complete:" << endl;
    cout << "  Positions evaluated: " << evaluated << endl;
    cout << "  Time: " << duration << " seconds (" << (duration/60) << " minutes)" << endl;

    return tablebase;
}

// ============================================================
// FILE I/O
// ============================================================

void save_canonical_positions(const unordered_set<__uint128_t, KeyHash>& positions) {
    ofstream out(CANONICAL_POSITIONS_FILE, ios::binary);

    size_t count = positions.size();
    out.write((char*)&count, sizeof(count));

    for (const __uint128_t& key : positions) {
        out.write((char*)&key, sizeof(key));
    }

    out.close();
    cout << "\nSaved " << count << " canonical positions to " << CANONICAL_POSITIONS_FILE << endl;
}

unordered_set<__uint128_t, KeyHash> load_canonical_positions() {
    unordered_set<__uint128_t, KeyHash> positions;
    ifstream in(CANONICAL_POSITIONS_FILE, ios::binary);

    if (!in) return positions;

    size_t count;
    in.read((char*)&count, sizeof(count));

    for (size_t i = 0; i < count; i++) {
        __uint128_t key;
        in.read((char*)&key, sizeof(key));
        positions.insert(key);
    }

    in.close();
    cout << "Loaded " << count << " canonical positions from " << CANONICAL_POSITIONS_FILE << endl;
    return positions;
}

void save_tablebase(const unordered_map<__uint128_t, Evaluation, KeyHash>& tablebase) {
    ofstream out(TABLEBASE_FILE, ios::binary);

    size_t count = tablebase.size();
    out.write((char*)&count, sizeof(count));

    for (const auto& entry : tablebase) {
        out.write((char*)&entry.first, sizeof(entry.first));
        out.write((char*)&entry.second.result, sizeof(entry.second.result));
        out.write((char*)&entry.second.depth, sizeof(entry.second.depth));
    }

    out.close();
    cout << "Saved tablebase (" << count << " positions) to " << TABLEBASE_FILE << endl;
}

unordered_map<__uint128_t, Evaluation, KeyHash> load_tablebase() {
    unordered_map<__uint128_t, Evaluation, KeyHash> tablebase;
    ifstream in(TABLEBASE_FILE, ios::binary);

    if (!in) return tablebase;

    size_t count;
    in.read((char*)&count, sizeof(count));

    for (size_t i = 0; i < count; i++) {
        __uint128_t key;
        int8_t result;
        uint8_t depth;

        in.read((char*)&key, sizeof(key));
        in.read((char*)&result, sizeof(result));
        in.read((char*)&depth, sizeof(depth));

        tablebase[key] = Evaluation(result, depth);
    }

    in.close();
    cout << "Loaded tablebase (" << count << " positions) from " << TABLEBASE_FILE << endl;
    return tablebase;
}

// ============================================================
// ANALYSIS & OUTPUT
// ============================================================

void analyze_initial_position(const unordered_map<__uint128_t, Evaluation, KeyHash>& tablebase) {
    cout << "\n============================================================" << endl;
    cout << "INITIAL POSITION ANALYSIS" << endl;
    cout << "============================================================\n" << endl;

    // Create initial position
    Position start;
    start.white_to_move = true;
    start.en_passant_file = -1;
    for (int file = 0; file < FILES; file++) {
        start.white_pawns |= (1ULL << Position::square(file, WHITE_START_RANK));
        start.black_pawns |= (1ULL << Position::square(file, BLACK_START_RANK));
    }

    Position start_canonical = start.canonical();
    __uint128_t start_key = start_canonical.to_key();

    auto it = tablebase.find(start_key);
    if (it == tablebase.end()) {
        cout << "ERROR: Initial position not found in tablebase!" << endl;
        return;
    }

    Evaluation eval = it->second;

    string result_str;
    if (eval.result == RESULT_WHITE_WIN) result_str = "WHITE WINS";
    else if (eval.result == RESULT_BLACK_WIN) result_str = "BLACK WINS";
    else if (eval.result == RESULT_DRAW) result_str = "DRAW";
    else result_str = "UNKNOWN";

    cout << "Result: " << result_str << endl;
    cout << "Depth to mate/terminal: " << (int)eval.depth << " moves" << endl;

    // Find all optimal first moves
    cout << "\nOptimal first moves:" << endl;
    vector<Move> moves = generate_moves(start);
    vector<string> optimal_moves;

    for (const Move& move : moves) {
        Position next_pos = apply_move(start, move);
        Position next_canonical = next_pos.canonical();
        __uint128_t next_key = next_canonical.to_key();

        auto next_it = tablebase.find(next_key);
        if (next_it != tablebase.end()) {
            Evaluation next_eval = next_it->second;
            // Check if this move leads to the best result
            if (next_eval.result == eval.result && next_eval.depth == eval.depth - 1) {
                optimal_moves.push_back(move.to_notation());
            }
        }
    }

    for (const string& move_str : optimal_moves) {
        cout << "  " << move_str << endl;
    }
}

void print_statistics(const unordered_map<__uint128_t, Evaluation, KeyHash>& tablebase) {
    cout << "\n============================================================" << endl;
    cout << "TABLEBASE STATISTICS" << endl;
    cout << "============================================================\n" << endl;

    size_t white_wins = 0;
    size_t black_wins = 0;
    size_t draws = 0;
    size_t unknown = 0;

    for (const auto& entry : tablebase) {
        if (entry.second.result == RESULT_WHITE_WIN) white_wins++;
        else if (entry.second.result == RESULT_BLACK_WIN) black_wins++;
        else if (entry.second.result == RESULT_DRAW) draws++;
        else unknown++;
    }

    cout << "Total positions: " << tablebase.size() << endl;
    cout << "White wins: " << white_wins << " (" << fixed << setprecision(1)
         << (100.0 * white_wins / tablebase.size()) << "%)" << endl;
    cout << "Black wins: " << black_wins << " (" << fixed << setprecision(1)
         << (100.0 * black_wins / tablebase.size()) << "%)" << endl;
    cout << "Draws: " << draws << " (" << fixed << setprecision(1)
         << (100.0 * draws / tablebase.size()) << "%)" << endl;
    if (unknown > 0) {
        cout << "Unknown: " << unknown << " (" << fixed << setprecision(1)
             << (100.0 * unknown / tablebase.size()) << "%)" << endl;
    }
}

// ============================================================
// MAIN
// ============================================================

int main(int argc, char* argv[]) {
    cout << "\n============================================================" << endl;
    cout << "SIX PAWN CHESS - COMPLETE SOLVER" << endl;
    cout << "Memory-Optimized with Checkpointing" << endl;
    cout << "============================================================" << endl;

    bool load_existing = false;
    if (argc > 1 && string(argv[1]) == "--load") {
        load_existing = true;
    }

    auto total_start = chrono::steady_clock::now();

    unordered_set<__uint128_t, KeyHash> canonical_positions;
    unordered_map<__uint128_t, Evaluation, KeyHash> tablebase;

    if (load_existing) {
        cout << "\nAttempting to load existing data..." << endl;
        canonical_positions = load_canonical_positions();

        if (canonical_positions.empty()) {
            cout << "No existing canonical positions found. Running full generation..." << endl;
            canonical_positions = enumerate_positions();
            save_canonical_positions(canonical_positions);
        }

        tablebase = load_tablebase();

        if (tablebase.empty()) {
            cout << "\nNo existing tablebase found. Running retrograde analysis..." << endl;
            tablebase = retrograde_analysis(canonical_positions);
            save_tablebase(tablebase);
        }
    } else {
        // Full generation and solve
        canonical_positions = enumerate_positions();
        save_canonical_positions(canonical_positions);

        tablebase = retrograde_analysis(canonical_positions);
        save_tablebase(tablebase);
    }

    auto total_end = chrono::steady_clock::now();
    auto total_duration = chrono::duration_cast<chrono::seconds>(total_end - total_start).count();

    // Output analysis
    analyze_initial_position(tablebase);
    print_statistics(tablebase);

    cout << "\n============================================================" << endl;
    cout << "SOLVER COMPLETE" << endl;
    cout << "Total runtime: " << total_duration << " seconds ("
         << (total_duration / 60) << " minutes)" << endl;
    cout << "============================================================\n" << endl;

    return 0;
}
