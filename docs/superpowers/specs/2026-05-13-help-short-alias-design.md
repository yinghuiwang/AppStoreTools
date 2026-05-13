# Design: Add `-h` Short Alias for `--help`

## Summary

Add `-h` as a short option alias for `--help` in the `asc` CLI.

## Change

**File:** `src/asc/cli.py`, line 56

```python
# Before
context_settings={"help_option_names": ["--help"], "max_content_width": 120},

# After
context_settings={"help_option_names": ["--help", "-h"], "max_content_width": 120},
```

## Scope

- **All levels:** The change applies to `asc` and all subcommands (e.g., `asc app add -h`, `asc upload -h`).
- **No other changes required.** Typer propagates context settings to subcommands automatically.

## Testing

Smoke test:
- `asc -h` — shows main help
- `asc app -h` — shows app subcommand help
- `asc app add -h` — shows add subcommand help
