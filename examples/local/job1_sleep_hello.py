#!/usr/bin/env python3
"""Example local job that sleeps and prints hello message.

This script demonstrates a simple local job that:
- Waits for a few seconds
- Prints an identifiable hello message
- Exits with code 0
"""

import time
import sys


def main() -> int:
    """Execute the job: sleep, print hello, and exit."""
    # Wait for a few seconds (well within the 10-second limit)
    time.sleep(3)

    # Print identifiable hello message
    print("hello from local job1")

    # Exit with code 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
