# Task List: Server Identity and Stale PID Reconciliation

## Wave 1: Foundation Task

### Task 1: Define canonical server identity and stale-state reconciliation

**Status**: In Progress

**Description**: 
Define the canonical server identity verification logic. Add functions to `src/pxq/server_pid.py` to:
- Detect actual pxq server process by port ownership and cmdline identity
- Clean up stale PID files automatically
- Guard against touching non-pxq processes

**Subtasks**:

- [x] Create design document (.tmp/design.md)
- [ ] Create task list (.tmp/task.md)
- [ ] Implement `get_pxq_server_pid()` function
  - Use `lsof -ti:{port}` to find process listening on server port
  - Verify process identity via cmdline check
  - Return None if no pxq server found or non-pxq process owns port
- [ ] Implement `is_pxq_server_running()` function
  - Wrapper around `get_pxq_server_pid()`
- [ ] Implement `cleanup_stale_pid()` function
  - Compare PID file with actual server PID
  - Remove stale PID file
- [ ] Add unit tests for new functions
  - Test stale PID reconciliation happy path
  - Test non-pxq listener failure guard
  - Test normal operation
  - Test no server running
- [ ] Run pytest and verify all tests pass
- [ ] Save pytest output to .sisyphus/evidence/
- [ ] Create learnings document

**Dependencies**: None (foundation task)

**Dependent Tasks**: 
- Task 2: TBD
- Task 3: TBD
- Task 4: TBD

**Files to Modify**:
- `src/pxq/server_pid.py` - Add new functions
- `tests/unit/test_server_pid.py` - Add test cases

**Test Commands**:
```bash
# Run all server_pid tests
uv run pytest tests/unit/test_server_pid.py -v

# Run specific test categories
uv run pytest tests/unit -k "server_pid or stale pid or listener" -q
```

**Acceptance Criteria**:
- [ ] `get_pxq_server_pid()` returns actual pxq server PID (not stale PID)
- [ ] `get_pxq_server_pid()` returns None for non-pxq process on port
- [ ] `is_pxq_server_running()` accurately reflects pxq server status
- [ ] `cleanup_stale_pid()` removes stale PID files
- [ ] All existing tests continue to pass (no regression)
- [ ] New tests cover all scenarios
- [ ] pytest output saved to .sisyphus/evidence/

## Notes

- Platform: macOS (primary), Linux (secondary)
- Default server port: 8765
- Server identity: process running `uvicorn pxq.server:app`
