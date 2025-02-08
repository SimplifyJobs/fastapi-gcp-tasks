#!/bin/sh
set -e

# Start socat in the background to forward external connections
socat TCP-LISTEN:8123,fork,reuseaddr,bind=0.0.0.0 TCP:127.0.0.1:8124 &
SOCAT_PID=$!

# Start emulator on internal port with gRPC binding
/emulator -port 8124 -grpc_port 8124 -grpc_host 0.0.0.0 &
EMULATOR_PID=$!

# Function to cleanup processes
cleanup() {
    kill $SOCAT_PID $EMULATOR_PID 2>/dev/null || true
}

# Set up trap
trap cleanup EXIT

# Wait for emulator to be ready
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:8124/v1/projects/test-project/locations/us-central1/queues > /dev/null; then
        echo "Emulator is ready on internal port!"
        if curl -s http://localhost:8123/v1/projects/test-project/locations/us-central1/queues > /dev/null; then
            echo "Emulator is accessible on external port!"
            break
        fi
    fi
    echo "Waiting for emulator... attempt $i"
    sleep 1
done

# Keep the script running
wait $EMULATOR_PID
