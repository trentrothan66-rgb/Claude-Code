#!/usr/bin/env python3
"""
Monitor the six-pawn solver progress.
"""

import time
import os
import sys

def get_latest_progress():
    """Get the latest progress from solver log."""
    try:
        with open('solver_output.log', 'r') as f:
            lines = f.readlines()

        # Find the last enumeration line
        for line in reversed(lines):
            if 'Enumerated' in line and 'positions' in line:
                return line.strip()

        # Check if retrograde analysis started
        for line in reversed(lines):
            if 'Iteration' in line and 'solved' in line:
                return line.strip()

        # Check if completed
        for line in reversed(lines):
            if 'STARTING POSITION ANALYSIS' in line:
                return "SOLVER COMPLETED! Check log for results."

        return "No progress updates found yet..."
    except FileNotFoundError:
        return "Solver log file not found"
    except Exception as e:
        return f"Error reading log: {e}"

def get_solver_pid():
    """Get the PID of the running solver."""
    try:
        import subprocess
        result = subprocess.run(['pgrep', '-f', 'python3 six_pawn_solver'],
                              capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
        return None
    except:
        return None

def get_memory_usage(pid):
    """Get memory usage of a process in MB."""
    try:
        import subprocess
        result = subprocess.run(['ps', '-p', str(pid), '-o', 'rss='],
                              capture_output=True, text=True)
        if result.returncode == 0:
            rss_kb = int(result.stdout.strip())
            return rss_kb / 1024  # Convert to MB
        return None
    except:
        return None

def main():
    """Main monitoring loop."""
    print("=" * 70)
    print("Six Pawn Chess Solver - Progress Monitor")
    print("=" * 70)
    print("Press Ctrl+C to stop monitoring\n")

    try:
        while True:
            os.system('clear' if os.name != 'nt' else 'cls')

            print("=" * 70)
            print("Six Pawn Chess Solver - Progress Monitor")
            print("=" * 70)

            # Check if solver is running
            pid = get_solver_pid()
            if pid:
                print(f"Status: RUNNING (PID: {pid})")
                mem = get_memory_usage(pid)
                if mem:
                    print(f"Memory: {mem:.1f} MB")
            else:
                print("Status: NOT RUNNING")

            print()

            # Get latest progress
            progress = get_latest_progress()
            print(f"Latest progress:\n{progress}")

            print("\n" + "=" * 70)
            print("Refreshing every 5 seconds... (Ctrl+C to stop)")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\nMonitoring stopped.")
        sys.exit(0)

if __name__ == '__main__':
    main()
