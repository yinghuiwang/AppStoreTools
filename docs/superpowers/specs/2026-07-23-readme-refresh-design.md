# README Refresh Design

**Date:** 2026-07-23

## Goal

Refresh `README.md` and `README.zh-CN.md` as concise, newcomer-focused landing pages. A reader should understand what `asc` does, install it, configure one app, and run a safe preview without reading the full command reference.

## Audience and Scope

The primary audience is an App Store developer using `asc` for the first time. The README files will explain the supported workflows and guide readers to the existing tutorials for detailed data formats and advanced options.

This change updates documentation only. It does not change CLI behavior, tutorial content, package metadata, or application code.

## Information Architecture

Both language versions will use the same section order:

1. Project title, language switch, and concise positioning
2. Core capabilities
3. Requirements
4. Three-step quick start: install, configure, dry-run
5. Common workflows with representative commands
6. Configuration precedence and file locations
7. Tutorial index
8. Development and security notes
9. Troubleshooting

The README files will not duplicate the complete CLI reference. Readers will be directed to `asc --help`, `asc <command> --help`, and the task-specific tutorials for full details.

## Content Changes

- Remove the temporary feature-branch installation example.
- Consolidate the three overlapping installation sections into a recommended path plus compact alternatives.
- Keep commands that form a safe first-run path: installation, `asc install` or profile setup, `asc check`, and `asc upload --dry-run`.
- Group representative commands by user task rather than listing every command in one large block.
- Document current implemented capabilities that are absent from the landing pages: IAP review screenshots, LLM-assisted What's New translation, persistent Web tasks, and Webhook notifications.
- Move CSV schemas, screenshot folder mappings, build configuration examples, and exhaustive command details out of the main flow by linking to existing tutorials or command help.
- Retain essential platform constraints: Python 3.9+, macOS/Xcode for build and release operations, and App Store Connect API credentials.

## Bilingual Consistency

`README.md` and `README.zh-CN.md` will mirror each other section by section. Shell commands, paths, environment variable names, and option names will be identical. Prose and link targets will use the appropriate language-specific tutorial where one exists.

Project terminology will follow the CLI and existing documentation, including App Profile, Guard, What's New, IAP, TestFlight, and App Store Connect.

## Accuracy and Safety

Every documented capability and representative command will be checked against the current Typer command registration and command help. The quick start will favor `--dry-run` before any operation that can change App Store Connect state.

The documentation will continue to warn against committing `.p8` keys, `.env` files, local profiles, or generated credentials. It will clarify which configuration is global and which is project-local.

## Verification

After editing:

- Review the diff for English/Chinese structural parity.
- Check all relative Markdown links resolve to repository files.
- Compare documented top-level commands with `asc --help`.
- Spot-check option examples with the relevant `asc <command> --help` output.
- Scan for stale branch names, stale versions, placeholders, and unsupported claims.

## Out of Scope

- Rewriting the tutorial series
- Adding badges, screenshots, promotional artwork, or generated marketing claims
- Changing CLI output, commands, options, or configuration behavior
- Adding a generated command-reference document
