# Testing Guide

## Prerequisites
- Python 3.11 or higher
- Poetry for dependency management
- cloud-tasks-emulator (install from https://github.com/aertje/cloud-tasks-emulator)

## Environment Variables
Required environment variables for testing:
```bash
# Local development flag
IS_LOCAL=true

# Task emulator settings
CLOUD_TASKS_EMULATOR_URL=http://localhost:8123
TASK_LISTENER_BASE_URL=http://localhost:8000

# Task queue settings
TASK_PROJECT_ID=test-project
TASK_LOCATION=us-central1
TASK_QUEUE=test-queue
```

## Running Tests

1. Install dependencies:
```bash
poetry install --with test
```

2. Start the cloud-tasks-emulator:
```bash
cloud-tasks-emulator
```

3. Run tests:
```bash
# Run all tests
poetry run pytest

# Run with coverage report
poetry run pytest --cov=fastapi_gcp_tasks

# Run specific test file
poetry run pytest tests/test_delayed_route.py
```

## Test Structure

The test suite is organized into several key areas:

### Core Functionality Tests
- DelayedRouteBuilder
  * Basic task creation and execution
  * Queue auto-creation
  * Task options (countdown, task_id)
  * Error handling and validation

- ScheduledRouteBuilder
  * Basic job creation
  * Cron schedule validation
  * Time zone handling
  * Job updates and uniqueness

### Hook and Dependency Tests
- Task Hooks
  * OIDC token hooks
  * Deadline hooks
  * Chained hooks
  * Custom hook creation
- Dependencies
  * max_retries functionality
  * CloudTasksHeaders integration
  * Error propagation

### Example Implementation Tests
- Simple Example
  * Local mode functionality
  * Task queueing
  * Environment variable handling
  * Default settings

- Full Example
  * Chained hook configuration
  * Retry mechanisms
  * Scheduled tasks
  * Environment-specific behavior

### Environment-Specific Tests
- Local Development
  * Emulator integration
  * Default configurations
  * Environment variable handling

- Deployed Environment
  * OIDC token integration
  * Cloud Scheduler integration
  * Job scheduling
  * Production settings

## Contributing Tests

When adding new tests:
1. Follow existing test patterns
2. Ensure proper type hints are used
3. Run formatting and linting:
```bash
sh scripts/format.sh
sh scripts/lint.sh
```
4. Add appropriate docstrings for complex test cases
5. Consider edge cases and error scenarios
