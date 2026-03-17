# PyPI Release Guide

This document describes how to publish `pxq` to PyPI.

## Prerequisites

### 1. PyPI Account

Create a PyPI account at https://pypi.org/account/ if you don't have one.

### 2. Trusted Publisher Setup

Trusted Publisher allows publishing to PyPI without API tokens, using GitHub OIDC.

**Steps:**

1. Go to https://pypi.org/manage/account/publishing/
2. Click "Add a trusted publisher"
3. Select "GitHub Actions"
4. Fill in:
   - **Project name**: `pxq`
   - **Owner**: `takeru1205`
   - **Repository name**: `pxq`
   - **Workflow name**: `publish.yml`
   - **Environment**: `pypi` (or leave blank for all environments)
5. Click "Add"

### 3. Create PyPI Project (First Time Only)

For the first release:

1. Go to https://pypi.org/project/pxq/
2. If the project doesn't exist, create it with the name `pxq`
3. Add the Trusted Publisher you created above

## Release Process

### Step 1: Update Version

Update the version in `pyproject.toml`:

```toml
[project]
name = "pxq"
version = "0.1.0"  # Update this
```

**Versioning scheme**: Follow [Semantic Versioning](https://semver.org/)
- `0.1.0` - Initial release
- `0.1.1` - Bug fix
- `0.2.0` - New feature

### Step 2: Commit Changes

```bash
git add .
git commit -m "Bump version to 0.1.0"
git push origin main
```

### Step 3: Create GitHub Release

**Via GitHub Web UI:**

1. Go to https://github.com/takeru1205/pxq/releases
2. Click "Draft a new release"
3. Fill in:
   - **Tag version**: `v0.1.0` (match the version with `v` prefix)
   - **Release title**: `v0.1.0`
   - **Description**: Add release notes (see template below)
4. Click "Publish release"

**Via GitHub CLI:**

```bash
gh release create v0.1.0 \
  --title "v0.1.0" \
  --notes "Release notes here" \
  --generate-notes
```

### Step 4: Automatic PyPI Publish

Once the release is published:

1. GitHub Actions workflow `.github/workflows/publish.yml` is triggered automatically
2. The workflow builds the package and publishes to PyPI
3. Monitor the action at: https://github.com/takeru1205/pxq/actions

### Step 5: Verify Publication

Check that the package is published:

- **PyPI**: https://pypi.org/project/pxq/
- **Installation test**:
  ```bash
  pip install pxq
  pxq --version
  ```

## Release Notes Template

```markdown
## What's Changed

### New Features
- Feature description

### Bug Fixes
- Fix description

### Improvements
- Improvement description

## Installation

```bash
# From PyPI
pip install pxq

# Or with uv
uv tool install pxq

# From GitHub (latest)
uv tool install git+https://github.com/takeru1205/pxq.git
```

**Full Changelog**: https://github.com/takeru1205/pxq/compare/v0.0.0...v0.1.0
```

## Troubleshooting

### Workflow Fails

**Check the logs at**: https://github.com/takeru1205/pxq/actions

Common issues:
- **Trusted Publisher not configured**: Verify the publisher setup in PyPI
- **Version already exists**: Bump the version number
- **Build errors**: Check `uv build` output locally

### Package Name Already Taken

If `pxq` is already taken on PyPI:
- You cannot publish with the same name
- Consider a different name or contact the current owner

### Manual Publish (Fallback)

If Trusted Publisher fails, use API token:

```bash
# Add token as GitHub Secret: PYPI_TOKEN
# Then modify publish.yml to use:
- run: uv publish --token ${{ secrets.PYPI_TOKEN }}
```

## Version History

| Version | Date | Notes |
|---------|------|-------|
| 0.1.0 | TBD | Initial release |
