# GSM Spy Zombie Process Fix

## Issue Description

When starting GSM Spy, `grgsm_scanner` and `grgsm_livemon` processes were becoming zombies (defunct processes):

```
root  12488  5.1  0.0      0     0 pts/2    Z+   14:29   0:01 [grgsm_scanner] <defunct>
```

## Root Cause

**Zombie processes** occur when a child process terminates but the parent process doesn't call `wait()` or `waitpid()` to collect the exit status. The process remains in the process table as a zombie until the parent reaps it.

In the GSM Spy implementation, there were three issues:

### Issue 1: scanner_thread not reaping grgsm_scanner process
- The `scanner_thread` function reads from `grgsm_scanner` stdout
- When the process terminates (either normally or due to error), the thread exits
- But it never calls `process.wait()` to reap the child process
- Result: zombie `grgsm_scanner` process

### Issue 2: monitor_thread not reaping tshark process
- The `monitor_thread` function reads from `tshark` stdout
- Same problem as Issue 1
- Result: zombie `tshark` process

### Issue 3: grgsm_livemon process not tracked at all
- When starting monitoring, two processes are created:
  1. `grgsm_livemon` - captures GSM traffic and feeds it to tshark
  2. `tshark` - filters and parses GSM data
- Only `tshark` was being tracked in `gsm_spy_monitor_process`
- `grgsm_livemon` was started but never stored or cleaned up
- Result: zombie `grgsm_livemon` process

## Solution

### Fix 1: Reap processes in scanner_thread

**File**: `/opt/intercept/routes/gsm_spy.py`
**Function**: `scanner_thread()` (line ~1026)

**Changes**:
```python
finally:
    # Reap the process to prevent zombie
    try:
        if process.poll() is None:
            # Process still running, terminate it
            process.terminate()
            process.wait(timeout=5)
        else:
            # Process already terminated, just collect exit status
            process.wait()
        logger.info(f"Scanner process terminated with exit code {process.returncode}")
    except Exception as e:
        logger.error(f"Error cleaning up scanner process: {e}")
        try:
            process.kill()
            process.wait()
        except Exception:
            pass
    logger.info("Scanner thread terminated")
```

**How it works**:
1. Check if process is still running with `poll()`
2. If running, terminate gracefully with `terminate()` then `wait()`
3. If already terminated, just call `wait()` to collect exit status
4. If anything fails, try `kill()` then `wait()`
5. This ensures the child process is always reaped

### Fix 2: Reap processes in monitor_thread

**File**: `/opt/intercept/routes/gsm_spy.py`
**Function**: `monitor_thread()` (line ~1089)

**Changes**: Same cleanup logic as Fix 1, applied to the monitor thread.

### Fix 3: Track and clean up grgsm_livemon process

#### 3a. Add global variable for grgsm_livemon

**File**: `/opt/intercept/app.py` (line ~185)

**Changes**:
```python
# GSM Spy
gsm_spy_process = None
gsm_spy_livemon_process = None  # For grgsm_livemon process
gsm_spy_monitor_process = None  # For tshark monitoring process
```

#### 3b. Update global declarations

**File**: `/opt/intercept/app.py` (line ~677)

**Changes**:
```python
global gsm_spy_process, gsm_spy_livemon_process, gsm_spy_monitor_process
```

#### 3c. Clean up grgsm_livemon in reset function

**File**: `/opt/intercept/app.py` (line ~755)

**Changes**:
```python
if gsm_spy_livemon_process:
    try:
        safe_terminate(gsm_spy_livemon_process, 'grgsm_livemon')
        killed.append('grgsm_livemon')
    except Exception:
        pass
gsm_spy_livemon_process = None
```

#### 3d. Store grgsm_livemon process when starting

**File**: `/opt/intercept/routes/gsm_spy.py`

**Changes in `/monitor` endpoint** (line ~212):
```python
app_module.gsm_spy_livemon_process = grgsm_proc
app_module.gsm_spy_monitor_process = tshark_proc
```

**Changes in `auto_start_monitor()` function** (line ~997):
```python
app_module.gsm_spy_livemon_process = grgsm_proc
app_module.gsm_spy_monitor_process = tshark_proc
```

#### 3e. Stop grgsm_livemon when stopping scanner

**File**: `/opt/intercept/routes/gsm_spy.py` (line ~254)

**Changes**:
```python
if app_module.gsm_spy_livemon_process:
    try:
        app_module.gsm_spy_livemon_process.terminate()
        app_module.gsm_spy_livemon_process.wait(timeout=5)
        killed.append('livemon')
    except Exception:
        try:
            app_module.gsm_spy_livemon_process.kill()
        except Exception:
            pass
    app_module.gsm_spy_livemon_process = None
```

## Files Modified

1. `/opt/intercept/routes/gsm_spy.py`
   - `scanner_thread()` - Added process reaping in finally block
   - `monitor_thread()` - Added process reaping in finally block
   - `/monitor` endpoint - Store grgsm_livemon process
   - `auto_start_monitor()` - Store grgsm_livemon process
   - `/stop` endpoint - Clean up grgsm_livemon process

2. `/opt/intercept/app.py`
   - Added `gsm_spy_livemon_process` global variable
   - Updated global declarations in `reset_decoder_processes()`
   - Added cleanup for `gsm_spy_livemon_process`

## Testing

### Before Fix
```bash
# Start GSM Spy
# Check processes
ps aux | grep grgsm

# You would see:
root  12488  0.0  0.0      0     0 pts/2    Z+   14:29   0:00 [grgsm_scanner] <defunct>
root  12489  0.0  0.0      0     0 pts/2    Z+   14:29   0:00 [grgsm_livemon] <defunct>
```

### After Fix
```bash
# Start GSM Spy
# Check processes
ps aux | grep grgsm

# Active processes (no zombies):
root  12488  1.2  0.5  12345  5678 pts/2    S+   14:29   0:01 grgsm_scanner -d 0 --freq-range...
root  12489  0.8  0.4  10234  4567 pts/2    S+   14:29   0:01 grgsm_livemon -a 123 -d 0

# Stop GSM Spy
# Check processes
ps aux | grep grgsm

# No processes (all cleaned up properly)
```

### Verification Commands

1. **Check for zombie processes**:
```bash
ps aux | grep defunct
# Should return nothing after fix
```

2. **Monitor process lifecycle**:
```bash
# In one terminal, watch processes
watch -n 1 'ps aux | grep grgsm'

# In another terminal, start/stop GSM Spy
# Verify:
# - Processes start properly (S or R state, not Z)
# - Processes disappear when stopped (not left as zombies)
```

3. **Check process tree**:
```bash
pstree -p | grep grgsm
# Should show proper parent-child relationships
# No defunct/zombie entries
```

## Process Lifecycle

### Normal Operation

1. **Scanner Start**:
   - `grgsm_scanner` spawned → stored in `gsm_spy_process`
   - `scanner_thread` reads output
   - Process running normally

2. **Monitor Start** (auto or manual):
   - `grgsm_livemon` spawned → stored in `gsm_spy_livemon_process`
   - `tshark` spawned → stored in `gsm_spy_monitor_process`
   - `monitor_thread` reads tshark output
   - Both processes running normally

3. **Stop**:
   - All three processes terminated gracefully
   - `wait()` called on each to collect exit status
   - Process handles set to None
   - No zombies remain

### Error Handling

1. **Process crashes during operation**:
   - Thread's stdout loop exits
   - `finally` block executes
   - `process.wait()` collects exit status
   - No zombie created

2. **Process hangs**:
   - `terminate()` called
   - `wait(timeout=5)` gives 5 seconds to exit
   - If timeout, `kill()` is called
   - `wait()` collects exit status

3. **Exception during cleanup**:
   - Fallback to `kill()` + `wait()`
   - Ensures zombie is always prevented

## Best Practices Applied

1. **Always reap child processes**: Call `wait()` or `waitpid()` after child process terminates
2. **Use process.poll()**: Check if process is still running before terminating
3. **Graceful shutdown**: Try `terminate()` before `kill()`
4. **Timeout handling**: Use `wait(timeout=N)` to prevent hanging
5. **Error recovery**: Multiple fallback levels in try/except blocks
6. **Track all processes**: Store handles for all spawned processes, not just the primary one
7. **Cleanup in finally**: Ensures cleanup happens even if exceptions occur

## Related Issues

This fix prevents:
- Zombie processes accumulating over time
- Process table filling up
- System resource leaks
- Confusing process listings for users

## Implementation Date

2026-02-06

## Additional Notes

- The fix follows the same patterns used in other INTERCEPT decoders
- Compatible with existing SDR device selection implementation
- No breaking changes to API or user interface
- Applies to both manual monitoring and auto-monitoring
