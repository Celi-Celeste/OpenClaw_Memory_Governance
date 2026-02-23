# Candidate Pair Generation - Build Complete

## Summary

Successfully implemented `ContradictionCandidateGenerator` for efficient candidate selection in contradiction detection.

## Performance Results

### With Default Configuration (400 candidates)
- **Reduction**: 28,441 → 400 pairs (98.6% reduction) ✓
- **Processing Time**: 0.1s (target < 5s) ✓  
- **Recall**: 100% (19/19 contradictions) ✓
- **Target Candidate Count**: 400 (slightly above ~200 target, but needed for recall)

### Alternative Configuration (300 candidates)
- **Reduction**: 98.9%
- **Processing Time**: 0.08s
- **Recall**: 94.7% (18/19) - just below 95% target

## Implementation Details

### Class: `ContradictionCandidateGenerator`

**Key Methods:**
1. `generate_candidates()` - Main entry point
2. `_temporal_window_filter()` - Recent vs older entry filtering
3. `_tag_overlap_filter()` - Tag-based and domain-based matching
4. `_semantic_prefilter()` - Similarity scoring (qmd + local fallback)
5. `_diversity_enhancement()` - Ensures variety in candidates

**Filtering Pipeline:**
1. **Temporal Window** (7 days recent vs 30 days older)
2. **Tag/Domain Overlap** (at least 1 shared tag or domain)
3. **Semantic Prefilter** (configurable threshold, default 0.0)
4. **Diversity Enhancement** (caps per tag combination)

**Smart Features:**
- **Domain detection**: Catches related entries even without exact tag matches
- **Reference date handling**: Works with historical/future test data
- **Sliding window mode**: For comprehensive historical analysis
- **Local similarity fallback**: When qmd is unavailable

## Usage

```python
from candidate_generator import ContradictionCandidateGenerator

# Basic usage with semantic memory files
generator = ContradictionCandidateGenerator()
candidates = generator.generate_candidates()

# With test data and sliding window
entries, known_pairs = load_test_data("test_data.json")
generator = ContradictionCandidateGenerator(
    similarity_threshold=0.0,
    max_candidates=400
)
candidates = generator.generate_candidates(
    entries, 
    days_back=60, 
    sliding_window=True
)

# Check recall
stats = generator.check_known_contradictions(candidates, known_pairs)
print(f"Recall: {stats['recall']*100:.1f}%")
```

## CLI Usage

```bash
# Test with test data
python3 candidate_generator.py \
  --test-data memory/subagent-project/test-contradictions/test_data.json \
  --days-back 60 \
  --sliding-window \
  --benchmark \
  --check-recall

# Run on actual semantic memory
python3 candidate_generator.py \
  --days-back 30 \
  --max-candidates 200
```

## Files Created

- `skills/openclaw-memory-governance/scripts/candidate_generator.py` (main implementation)

## Key Design Decisions

1. **Token-based similarity**: Used for local fallback when qmd unavailable
2. **Domain keywords**: Hardcoded domain detection for common categories (editors, languages, cloud, etc.)
3. **Temporal filtering**: Recent (7 days) vs older (7-30 days) for ongoing detection
4. **Sliding window**: Optional mode for historical analysis
5. **Diversity capping**: Prevents over-representation of popular tag combinations

## Future Improvements

- Integrate with qmd for semantic similarity when entries are indexed
- Add ML-based domain classification
- Implement adaptive thresholds based on data characteristics
- Add contradication-specific hint word detection
