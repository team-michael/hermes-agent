# skill_view truncation output is not searchable with search_files

## Symptom

`skill_view(name="software-development/check", file_path="references/<x>.md")` on a
large reference file returns a truncation notice:

```
This tool result was too large (100,685 characters, 98.3 KB).
Full output saved to: /tmp/hermes-results/<id>.txt
Preview (first 1500 chars): ...
```

The saved `/tmp/hermes-results/<id>.txt` file is the **tool call's own JSON-wrapped
response**, not the raw markdown. The `content` field inside that JSON has its real
newlines escaped as literal `\n` characters, so from a line-oriented tool's point of
view the entire reference file is one single line.

## Why `search_files` fails here

`search_files` (ripgrep-backed) operates per physical line. Against the dump above it
either:
- returns exactly one match (line 1) for any pattern that exists anywhere in the file,
  because everything is on line 1, or
- returns a useless single-line "content" snippet that doesn't show the surrounding
  markdown structure you actually wanted.

Multi-line-context searches (`context=N`) are meaningless against this dump since there
is no line 2 to show as context.

## Fix

- Use `read_file` directly on the `/tmp/hermes-results/<id>.txt` path with `offset`/
  `limit` to page through the escaped JSON content field, or
- Just trust the `Preview` text already shown inline in the truncation notice if it
  already answers the question — it is the first ~1500 chars of the real reference
  content and is often sufficient for a quick classification lookup.
- If you truly need the full raw markdown searchable line-by-line, read the original
  skill file path directly (e.g. via `read_file` on the skill's on-disk `references/`
  path under `~/.hermes/profiles/<profile>/skills/...`) instead of going through the
  `skill_view` truncation artifact.
