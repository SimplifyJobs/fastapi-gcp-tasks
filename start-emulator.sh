#!/bin/sh
set -e

# Start emulator binding to all interfaces
/emulator -host 0.0.0.0 -port 8123 -grpc_port 8123 -grpc_host 0.0.0.0 &
EMULATOR_PID=$!

# Function to cleanup processes
cleanup() {
    kill $EMULATOR_PID 2>/dev/null || true
}

# Set up trap
trap cleanup EXIT

# Wait for emulator to be ready
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8123/v1/projects/test-project/locations/us-central1/queues > /dev/null; then
        echo "Emulator is ready!"
        break
    fi
    echo "Waiting for emulator... attempt $i"
    sleep 1
done

# Keep the script running
wait $EMULATOR_PID
