# Rollback Procedure: Weekly Drift Review LLM Integration

## Quick Rollback Options

### Option 1: Per-Run Rollback (Immediate)
Use the `--no-use-llm` flag to disable LLM-based classification for a single run:

```bash
cd skills/openclaw-memory-governance/scripts
python3 weekly_drift_review.py --workspace /path/to/workspace --no-use-llm
```

### Option 2: Environment Variable (Session-Based)
Set the environment variable to force legacy mode:

```bash
export DRIFT_REVIEW_LEGACY_MODE=1
python3 weekly_drift_review.py --workspace /path/to/workspace
```

### Option 3: Configuration Change (Persistent)
Edit `weekly_drift_review.py` and change the default:

```python
# Change this line:
parser.add_argument("--use-llm", dest="use_llm", action="store_true", default=True)

# To this:
parser.add_argument("--use-llm", dest="use_llm", action="store_true", default=False)
```

### Option 4: Emergency Fallback (Automatic)
The script automatically falls back to legacy mode if:
- New components fail to import
- LLM is unavailable and `--no-fallback` is not set
- Critical errors occur during LLM initialization

## Verification After Rollback

1. Check output shows `mode=legacy`:
   ```
   weekly_drift_review supersedes=0 refines=0 reinforces=0 unrelated=0 changed=0 mode=legacy
   ```

2. Verify checkpoint version is NOT updated to "2.0"

3. Confirm drift log entries don't include confidence scores

## Full Reversion (Remove LLM Components)

If you need to completely remove the LLM integration:

1. Restore original `weekly_drift_review.py` from version control
2. Remove new component files:
   ```bash
   rm skills/openclaw-memory-governance/scripts/candidate_generator.py
   rm skills/openclaw-memory-governance/scripts/llm_contradiction_client.py
   rm skills/openclaw-memory-governance/scripts/classification_engine.py
   ```
3. Verify script runs without errors:
   ```bash
   python3 weekly_drift_review.py --dry-run --verbose
   ```

## Troubleshooting

### Issue: Script fails to import new components
**Solution:** The script automatically falls back to legacy mode. Check the error message for import details.

### Issue: LLM times out
**Solution:** Increase timeout with `--llm-timeout 60` or use `--no-use-llm`

### Issue: Too many candidates generated
**Solution:** Limit candidates with `--max-candidates 100` or reduce `--window-days`

### Issue: Checkpoint corruption
**Solution:** Delete `memory/state/drift-review-checkpoint.json` and re-run

## Contact

If rollback doesn't resolve your issue, check:
1. Integration test results: `tests/INTEGRATION_TEST_RESULTS.md`
2. Component documentation in source files
3. Skill documentation: `SKILL.md`
