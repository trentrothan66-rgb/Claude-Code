#!/usr/bin/env python3
"""
Estimate completion time for the six-pawn solver based on current progress.
"""

import re
from datetime import datetime, timedelta

def parse_log():
    """Parse the solver log to extract progress data."""
    progress_data = []

    try:
        with open('solver_output.log', 'r') as f:
            for line in f:
                # Match enumeration lines
                match = re.search(r'Enumerated ([\d,]+) positions, queue size: ([\d,]+)', line)
                if match:
                    enumerated = int(match.group(1).replace(',', ''))
                    queue_size = int(match.group(2).replace(',', ''))
                    progress_data.append((enumerated, queue_size))

        return progress_data
    except FileNotFoundError:
        print("Error: solver_output.log not found")
        return []

def estimate_total_positions(data):
    """Estimate total positions based on recent growth patterns."""
    if len(data) < 10:
        return None

    # Look at the last few data points
    recent_data = data[-20:]

    # Check if queue is growing or shrinking
    queue_changes = []
    for i in range(1, len(recent_data)):
        enum_change = recent_data[i][0] - recent_data[i-1][0]
        queue_change = recent_data[i][1] - recent_data[i-1][1]
        queue_changes.append(queue_change / enum_change if enum_change > 0 else 0)

    avg_queue_growth_rate = sum(queue_changes) / len(queue_changes)

    last_enum, last_queue = recent_data[-1]

    # If queue is still growing, we're far from done
    if avg_queue_growth_rate > 0:
        # Rough estimate: total = enumerated + queue + future growth
        # This is speculative
        estimated_total = last_enum + last_queue * 2
        return estimated_total, "Queue still growing - rough estimate"
    else:
        # Queue is shrinking, getting closer
        estimated_total = last_enum + last_queue
        return estimated_total, "Queue shrinking - nearing completion"

def analyze_progress():
    """Analyze solver progress and provide estimates."""
    print("=" * 70)
    print("Six Pawn Chess Solver - Completion Estimate")
    print("=" * 70)

    data = parse_log()

    if not data:
        print("\nNo progress data found yet.")
        return

    print(f"\nData points collected: {len(data)}")

    last_enum, last_queue = data[-1]
    first_enum, first_queue = data[0]

    print(f"\nCurrent status:")
    print(f"  Enumerated: {last_enum:,} positions")
    print(f"  Queue size: {last_queue:,} positions")
    print(f"  Total discovered so far: {last_enum + last_queue:,}")

    # Calculate enumeration rate
    if len(data) >= 2:
        # Use recent data for rate calculation
        recent_start = max(0, len(data) - 10)
        positions_added = last_enum - data[recent_start][0]
        updates_elapsed = len(data) - recent_start

        # Each update is ~5 seconds
        seconds_elapsed = updates_elapsed * 5
        rate_per_sec = positions_added / seconds_elapsed if seconds_elapsed > 0 else 0

        print(f"\nEnumeration rate:")
        print(f"  ~{rate_per_sec:,.0f} positions/second")
        print(f"  ~{rate_per_sec * 60:,.0f} positions/minute")

        # Estimate completion
        result = estimate_total_positions(data)
        if result:
            estimated_total, note = result
            remaining = estimated_total - last_enum
            seconds_remaining = remaining / rate_per_sec if rate_per_sec > 0 else 0

            print(f"\nEstimates:")
            print(f"  {note}")
            print(f"  Estimated total positions: ~{estimated_total:,.0f}")
            print(f"  Remaining: ~{remaining:,.0f}")

            if seconds_remaining > 0:
                hours = seconds_remaining / 3600
                print(f"  Estimated time remaining: ~{hours:.1f} hours")

                # Check if queue is still growing significantly
                queue_ratio = last_queue / last_enum
                if queue_ratio > 1.0:
                    print(f"\n  WARNING: Queue ({last_queue:,}) is larger than enumerated ({last_enum:,})")
                    print(f"  This suggests the position space is very large.")
                    print(f"  The estimate above may be significantly underestimated.")

    # Analyze queue behavior
    if len(data) >= 10:
        print("\nQueue behavior (last 10 updates):")
        recent = data[-10:]
        for i, (enum, queue) in enumerate(recent):
            print(f"  {i+1}. Enum: {enum:>12,}  Queue: {queue:>12,}  Ratio: {queue/enum:.2f}")

    print("\n" + "=" * 70)

if __name__ == '__main__':
    analyze_progress()
